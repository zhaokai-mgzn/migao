"""app/api/migration.py 单元测试 — 旧 ERP 客户表头 → 规范客户字段映射建议（issue #8295）。

覆盖：
- 提示词前 PII 脱敏：手机号 / 邮箱打码、超长值截断，原始值不进模型上下文
- 模型 JSON 解析：代码块 / 顶层数组兼容；未知目标字段、越界下标、重复源列 / 重复目标字段被丢弃；
  置信度钳到 0~1；`source_header` 取自请求而非模型回显
- 降级：模型异常 / 超时 / 工厂失败 / 非 JSON ⇒ HTTP 200 + `degraded=true` + 空映射 + 中文说明
- 入参非法（headers / fields 为空、超出提示词预算）⇒ 400 且**不调用**模型
"""
# case_ids: MIG-001, MIG-002, MIG-003

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.api.migration import (
    MAX_FIELDS,
    MAX_HEADERS,
    CustomerMappingRequest,
    _build_messages,
    _mask_value,
)
from app.llm.factory import LLMFactory
from app.utils.auth import verify_service_token

ENDPOINT = "/api/internal/migration/customer-mapping"

HEADERS = ["购货单位", "联系方式", "送货地址"]
SAMPLES = [["张三布行", "13800138000", "zhangsan@example.com"]]
FIELDS = [
    {
        "key": "externalId",
        "label": "旧系统客户ID",
        "required": True,
        "type": "string",
        "aliases": ["客户编号", "客户编码"],
    },
    {
        "key": "displayName",
        "label": "客户名称",
        "required": True,
        "type": "string",
        "aliases": ["客户名称", "购货单位"],
    },
    {
        "key": "contactPhone",
        "label": "联系电话",
        "required": False,
        "type": "string",
        "aliases": ["联系电话", "联系方式"],
    },
]


def _payload(**overrides):
    payload = {"headers": HEADERS, "samples": SAMPLES, "fields": FIELDS}
    payload.update(overrides)
    return payload


class _FakeLLM:
    """替身模型：记录收到的 messages，按需返回内容或抛异常。"""

    def __init__(self, content=None, raises=None):
        self.content = content
        self.raises = raises
        self.calls = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        if self.raises is not None:
            raise self.raises
        return SimpleNamespace(content=self.content)


def _fake_llm(monkeypatch, content=None, raises=None):
    fake = _FakeLLM(content=content, raises=raises)
    monkeypatch.setattr(LLMFactory, "create_mapping_llm", lambda: fake)
    return fake


def _raising_factory(monkeypatch, exc):
    def _factory(*args, **kwargs):
        raise exc

    monkeypatch.setattr(LLMFactory, "create_mapping_llm", _factory)


def _prompt_text(fake):
    return "\n".join(str(message.content) for message in fake.calls[0])


@pytest.fixture
def client(test_client):
    """复用 conftest 的 TestClient，并把 Service Token 认证换成直通（认证本身另有用例）。"""
    test_client.app.dependency_overrides[verify_service_token] = lambda: True
    yield test_client
    test_client.app.dependency_overrides.clear()


# ============ 1. 提示词前 PII 脱敏 ============


class TestPromptPiiMasking:
    def test_mask_value_phone_email_and_truncation(self):
        assert _mask_value("13800138000") == "138******00"
        assert _mask_value("zhangsan@example.com") == "***@***"
        long_value = "绍兴市柯桥区" * 10  # 60 字
        masked = _mask_value(long_value)
        assert masked == long_value[:20] + "…"
        assert len(masked) == 21
        assert _mask_value(None) == ""

    def test_masks_pii_before_prompt(self, client, monkeypatch):
        """MIG-002 的承载体判据名（`.github/cases/migration.yml` 按此名引用）。"""
        fake = _fake_llm(monkeypatch, content=json.dumps({"mappings": []}))
        resp = client.post(ENDPOINT, json=_payload())
        assert resp.status_code == 200

        prompt = _prompt_text(fake)
        assert "13800138000" not in prompt
        assert "138******00" in prompt
        assert "zhangsan@example.com" not in prompt
        assert "***@***" in prompt
        # 表头本身仍是判断列语义的依据，保留（它不是客户数据）。
        assert "购货单位" in prompt

    def test_logs_never_contain_raw_samples(self, client, monkeypatch):
        """MIG-002：日志只记表头数 / 映射数 / 降级态，样本原文不得进日志。"""
        from loguru import logger

        records = []
        sink_id = logger.add(lambda message: records.append(str(message)), level="DEBUG")
        try:
            _fake_llm(monkeypatch, content=json.dumps({"mappings": []}))
            resp = client.post(ENDPOINT, json=_payload())
        finally:
            logger.remove(sink_id)
        assert resp.status_code == 200
        log_text = "\n".join(records)
        assert "headers=" in log_text  # 聚合读数确实打了（不是「什么都没记」）
        for raw in ("13800138000", "zhangsan@example.com", "张三布行"):
            assert raw not in log_text, f"日志泄漏样本原文：{raw}"

    def test_long_sample_value_truncated_in_prompt(self, client, monkeypatch):
        fake = _fake_llm(monkeypatch, content=json.dumps({"mappings": []}))
        long_value = "绍兴市柯桥区" * 10
        client.post(ENDPOINT, json=_payload(samples=[[long_value, "13800138000", ""]]))
        prompt = _prompt_text(fake)
        assert long_value not in prompt
        assert long_value[:20] + "…" in prompt

    def test_messages_are_single_system_and_human(self):
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = _build_messages(CustomerMappingRequest(**_payload()))
        assert isinstance(messages[0], SystemMessage)
        assert isinstance(messages[1], HumanMessage)
        assert "target_field" in messages[0].content
        assert '"mappings"' in messages[0].content


# ============ 2. 模型 JSON 解析与过滤 ============


class TestMappingParsing:
    def test_valid_mappings_and_invalid_entries_filtered(self, client, monkeypatch):
        content = json.dumps(
            {
                "mappings": [
                    {"source_index": 0, "target_field": "displayName", "confidence": 0.95, "reason": "购货单位是客户名称的常见旧 ERP 表头"},
                    {"source_index": 1, "target_field": "contactPhone", "confidence": 1.7, "reason": "联系方式是电话"},
                    {"source_index": 2, "target_field": "inventedField", "confidence": 0.9, "reason": "编造的字段"},
                    {"source_index": 99, "target_field": "externalId", "confidence": 0.8, "reason": "越界的下标"},
                    {"source_index": 0, "target_field": "externalId", "confidence": 0.7, "reason": "同一源列重复映射"},
                    {"source_index": 2, "target_field": "displayName", "confidence": 0.6, "reason": "同一目标字段重复映射"},
                    {"source_index": 2, "target_field": "externalId", "confidence": -0.3, "reason": "负置信度"},
                ]
            },
            ensure_ascii=False,
        )
        _fake_llm(monkeypatch, content=content)
        resp = client.post(ENDPOINT, json=_payload())
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert set(body["data"]) == {"mappings", "degraded", "message"}
        assert body["data"]["degraded"] is False
        assert body["data"]["message"] == ""

        mappings = body["data"]["mappings"]
        assert [m["source_index"] for m in mappings] == [0, 1, 2]
        assert [m["target_field"] for m in mappings] == ["displayName", "contactPhone", "externalId"]
        assert mappings[0]["source_header"] == "购货单位"
        assert mappings[0]["reason"].startswith("购货单位")
        assert mappings[1]["confidence"] == 1.0  # 1.7 钳到 1
        assert mappings[2]["confidence"] == 0.0  # -0.3 钳到 0

    def test_code_fence_wrapped_top_level_list_accepted(self, client, monkeypatch):
        content = (
            "```json\n"
            + json.dumps(
                [{"source_index": 1, "target_field": "contactPhone", "confidence": 0.9}],
                ensure_ascii=False,
            )
            + "\n```"
        )
        _fake_llm(monkeypatch, content=content)
        body = client.post(ENDPOINT, json=_payload()).json()
        assert body["data"]["degraded"] is False
        assert body["data"]["mappings"] == [
            {
                "source_index": 1,
                "source_header": "联系方式",
                "target_field": "contactPhone",
                "confidence": 0.9,
                "reason": "",
            }
        ]

    def test_prose_wrapped_top_level_list_accepted(self, client, monkeypatch):
        """说明文字 + 裸数组（无代码块）：按出现位置取 JSON 片段，不误取先出现的噪声。"""
        content = (
            "参考列号 [0] 与 [1] 后，映射结果如下：\n"
            + json.dumps([{"source_index": 0, "target_field": "displayName", "confidence": 0.8}])
            + "\n以上。"
        )
        _fake_llm(monkeypatch, content=content)
        body = client.post(ENDPOINT, json=_payload()).json()
        assert body["data"]["degraded"] is False
        assert [m["target_field"] for m in body["data"]["mappings"]] == ["displayName"]

    def test_source_header_comes_from_request_not_model(self, client, monkeypatch):
        content = json.dumps(
            {
                "mappings": [
                    {
                        "source_index": 0,
                        "source_header": "模型自己编的列名",
                        "target_field": "displayName",
                        "confidence": 0.8,
                    }
                ]
            },
            ensure_ascii=False,
        )
        _fake_llm(monkeypatch, content=content)
        body = client.post(ENDPOINT, json=_payload()).json()
        assert body["data"]["mappings"][0]["source_header"] == "购货单位"

    def test_bool_source_index_not_treated_as_int(self, client, monkeypatch):
        content = json.dumps(
            {"mappings": [{"source_index": True, "target_field": "displayName", "confidence": 0.5}]}
        )
        _fake_llm(monkeypatch, content=content)
        body = client.post(ENDPOINT, json=_payload()).json()
        assert body["data"]["mappings"] == []
        assert body["data"]["degraded"] is True


# ============ 3. 失败降级（绝不允许 500） ============


class TestDegradation:
    @pytest.mark.parametrize(
        "scenario",
        ["llm_exception", "timeout", "factory_exception", "not_json"],
    )
    def test_failure_returns_200_degraded_with_empty_mappings(self, client, monkeypatch, scenario):
        if scenario == "llm_exception":
            _fake_llm(monkeypatch, raises=RuntimeError("provider down"))
        elif scenario == "timeout":
            _fake_llm(monkeypatch, raises=asyncio.TimeoutError())
        elif scenario == "factory_exception":
            _raising_factory(monkeypatch, RuntimeError("LLM_API_KEY missing"))
        else:
            _fake_llm(monkeypatch, content="抱歉，我无法完成这个映射任务。")

        resp = client.post(ENDPOINT, json=_payload())
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["mappings"] == []
        assert body["data"]["degraded"] is True
        assert body["data"]["message"].strip(), "降级必须带一句中文说明，不能静默空表"
        assert any("\u4e00" <= ch <= "\u9fff" for ch in body["data"]["message"]), (
            "降级说明必须是中文（面向商家/运维）"
        )

    def test_unparseable_json_message_mentions_parse(self, client, monkeypatch):
        _fake_llm(monkeypatch, content="{这不是 JSON")
        body = client.post(ENDPOINT, json=_payload()).json()
        assert body["data"]["degraded"] is True
        assert "解析" in body["data"]["message"]

    def test_json_without_mappings_degrades(self, client, monkeypatch):
        _fake_llm(monkeypatch, content=json.dumps({"mappings": []}))
        body = client.post(ENDPOINT, json=_payload()).json()
        assert body["data"]["degraded"] is True
        assert body["data"]["mappings"] == []


# ============ 4. 入参非法 ⇒ 400 且不调用模型 ============


class TestRequestValidation:
    @pytest.mark.parametrize(
        "payload",
        [
            {"headers": [], "samples": [], "fields": FIELDS},
            {"headers": HEADERS, "samples": [], "fields": []},
            {"headers": HEADERS + ["多余表头"] * MAX_HEADERS, "samples": [], "fields": FIELDS},
            {
                "headers": HEADERS,
                "samples": [],
                "fields": FIELDS * (MAX_FIELDS // len(FIELDS) + 1),
            },
        ],
        ids=["empty_headers", "empty_fields", "too_many_headers", "too_many_fields"],
    )
    def test_bad_request_returns_400_without_llm_call(self, client, monkeypatch, payload):
        calls = []
        monkeypatch.setattr(LLMFactory, "create_mapping_llm", lambda: calls.append(1) or _FakeLLM())

        resp = client.post(ENDPOINT, json=payload)
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert detail["success"] is False
        assert detail["error"]["code"] == "MIGRATION_CUSTOMER_MAPPING_INVALID_INPUT"
        assert calls == [], "入参非法时不得调用模型（空跑一次就是白花钱）"


# ============ 5. 认证与路由 ============


class TestEndpointContract:
    def test_requires_service_token(self, test_client):
        """未带 Service Token ⇒ 401（与 /internal/registration/review 同款 fail-closed）。"""
        resp = test_client.post(ENDPOINT, json=_payload())
        assert resp.status_code == 401
        assert "AUTH_REQUIRED" in resp.text

    def test_non_mapping_keys_not_returned(self, client, monkeypatch):
        """响应 data 只允许三个键 —— 不回传客户样本、不含落库痕迹。"""
        _fake_llm(
            monkeypatch,
            content=json.dumps(
                {"mappings": [{"source_index": 1, "target_field": "contactPhone", "confidence": 0.9}]}
            ),
        )
        data = client.post(ENDPOINT, json=_payload()).json()["data"]
        assert set(data) == {"mappings", "degraded", "message"}
        assert "samples" not in json.dumps(data, ensure_ascii=False)

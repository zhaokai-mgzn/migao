# case_ids: MC-129
"""LLM 主凭据失效（401）必须是**可观测事件**，而不是一句静默兜底（issue #8084）。

## 病（2026-10-29 15:29 +08 线上实测，逐字读数见 issue #8084）

DeepSeek 主凭据在供应商侧失效（一轮 10 条 `401 AuthenticationError`、0 条 `LLM done`）时：

- 黄金策 / 元元 / 意图分类 / 会话标题 / 视觉识别**共用一把** `Settings.PRIMARY_API_KEY`
  ⇒ 一把 key 失效 = 全 AI 面 100% 不可用；
- 主循环把它当「不可重试」（正确），但**每轮**只落一条普通 ERROR、**没有告警面**；
- `/ready` 只探 DB + Redis ⇒ 200 全绿、容器 `healthy`、`docker ps` 一路绿；
- 用户只看到通用兜底句「刚才这轮没成功，请您再说一次」，靠人肉发现故障。

## 判据面（每条都能被"把实现删掉"打红）

| # | 判据 | 红证注入（改哪一行 ⇒ 红） |
|---|---|---|
| 1 | 确定性凭据失败（401）⇒ 进程级 `broken` 标志；**连续多次**失败只落**恰好 1 条** `[llm_health]` ERROR，且带 `error_class=` / `status=` / `PRIMARY_API_KEY` 可行动提示 | 删 `app/llm/factory.py::_LLMHealthChatModel.ainvoke` 的 `note_llm_failure(exc)` ⇒ 标志不置、0 条日志 ⇒ 红；把 `if _broken: return` 去掉 ⇒ 3 条日志 ⇒ 红 |
| 2 | 401 ⇒ `GET /internal/llm-health` 返回 **503** + `{ok:false,last_error_class:"authentication_error"}`（服务活着 ≠ AI 可用） | 端点恒 200，或 `ok` 恒 true ⇒ 红 |
| 3 | 真实成功调用 ⇒ `ok:true` / 200 / `last_ok_at` 有值 / **0 条** `[llm_health]` ERROR（真成功路径与兜底路径**分开断言**） | 成功也置 broken 或也打 ERROR ⇒ 红 |
| 4 | 探针 60s 缓存：同一分钟内连打三次只发**一次**真实调用；`force=True` 才再发一次 | 去掉缓存 ⇒ 计数 3 ⇒ 红 |
| 5 | 恢复自愈：401 → 成功 ⇒ 清标志（探针转绿）；再 401 ⇒ **重新**落一条（跃变语义，不是"只报一次终身"） | 成功不清标志（探针永久红）/ 清标志但不 rearm ⇒ 红 |
| 6 | `/ready` 语义**不变**（本单不允许把 LLM 状态塞进 `/ready` ⇒ 不许把供应商抖动放大成容器 unhealthy → 重启 churn） | 在 `/ready` 里调 LLM / 探针 ⇒ 红 |
| 7 | 接线：两个模型类（`_PassthroughOpenAI` / `_PassthroughDeepSeek`）都必须真的挂上混入（`ainvoke` 解析到混入实现，`ChatDeepSeek` 仍先于 `ChatOpenAI`） | 把混入从 bases 里摘掉 ⇒ 红（"判据绿但没接线"的形态） |
| 8 | 兜底句路径 vs 真成功路径（`execute_skill` 真入口）：401 ⇒ 用户仍看到兜底句**且**留痕；真成功 ⇒ **不**回兜底句**且**不留痕 | 兜底分支被改成"静默成功" ⇒ 红；成功路径误报 broken ⇒ 红 |
| 9 | **类级元守卫**：`app/main.py` 的每个应用层探针都必须登记「它到底探什么」（`/ready` 只探 DB+Redis 这件事写成台账，不许再被当成"AI 可用"） | 新增一个未登记的探针端点 / 摘掉已登记的沙 ⇒ 红 |

## 边界（照实登记）

- **不跑真实 LLM**（#4262 口径：评测只在用户显式要求时集中跑）：全部用替身 ——
  `ChatOpenAI.ainvoke` 被替换成「抛 401」/「返回 AIMessage」的桩，零网络、零配额；
- 本文件证的是**端点语义与接线**，不证「线上配置里真有探针在打」：那把端点接进 compose/探针
  属部署面，见 PR body 的「未做」清单；
- 只裁**确定性**类（401 / 402）；超时 / 5xx / 429 不进标志（那已有 `call_with_retry` + 熔断）。
"""

from __future__ import annotations

import pathlib
import re
from contextlib import contextmanager, suppress
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai import ChatOpenAI
from loguru import logger
from fastapi.testclient import TestClient

import app.graph.skills.base_skill as base_skill
import app.utils.llm_health as llm_health
from app import main as main_module
from app.llm import factory as factory_module
from app.graph.skills.base_skill import execute_skill

#: 用户可见兜底话术（#3810 起的口径，本单**不改**）
FALLBACK_TEXT = "刚才这轮没成功，请您再说一次，我继续为您办理。"
#: 凭据事件的日志检索锚
LOG_MARK = "[llm_health]"


class _ProviderAuthError(RuntimeError):
    """模拟 `openai.AuthenticationError`（401 `InvalidApiKey`）：带 `status_code`。

    消息逐字取线上形态（issue #8084 的容器日志）。**不走**类名兜底（类名兜底另有一条判据）——
    这里走的是 `status_code=401` 这条真实主路径。
    """

    status_code = 401

    def __init__(self, message: str = (
        "Error code: 401 - {'error': {'message': 'Authentication Fails, "
        "Your api key: ****a2ae is invalid'}}"
    )) -> None:
        super().__init__(message)


@pytest.fixture(autouse=True)
def _clean_llm_health_state():
    """进程级状态是**模块全局**的：用例之间必须复位，否则前后顺序会互相污染。"""
    llm_health.reset_llm_health()
    try:
        yield
    finally:
        llm_health.reset_llm_health()


@contextmanager
def _capture_error_records():
    """捕获 loguru ERROR 记录（显式 sink 而不是 caplog：只有拿到真 record 才能证"一行 = 一条事件"）。

    ⚠️ `create_app()` 会走 `app.log_config.setup_logging()`，它 `logger.remove()` 清掉既有 sink
    ⇒ 依赖端点的用例必须**建完 app 之后**再开捕获窗口，并且摘 sink 时容忍「已被清掉」。
    """
    records: list = []
    sink_id = logger.add(lambda m: records.append(m.record), level="ERROR", format="{message}")
    try:
        yield records
    finally:
        # 已被 `app.log_config.setup_logging()` 的 `logger.remove()` 清掉时，重复摘会抛 ValueError
        with suppress(ValueError):
            logger.remove(sink_id)


@pytest.fixture
def health_records():
    """捕获 loguru ERROR 记录（显式 sink 而不是 caplog：只有拿到真 record 才能证"一行 = 一条事件"）。"""
    with _capture_error_records() as records:
        yield records


def _health_lines(records) -> list:
    return [r for r in records if LOG_MARK in r["message"]]


def _real_model(cls_name: str = "_PassthroughOpenAI"):
    """真的工厂模型实例（**混入在 MRO 里**）—— 不用 MagicMock，否则测不到接线。

    `ci-dummy` / 空 key 都无所谓：本文件从不发真实请求（`ChatOpenAI.ainvoke` 全被替换）。
    """
    cls = getattr(factory_module, cls_name)
    return cls(
        model="deepseek-flash",
        api_key="sk-invalid",
        base_url="http://127.0.0.1:9/v1",
        temperature=0,
    )


def _llm_raises(exc: BaseException):
    """替换**基类**的 `ainvoke` ⇒ 混入层的 `super().ainvoke` 命中桩（保留真实 MRO）。"""
    return patch.object(ChatOpenAI, "ainvoke", AsyncMock(side_effect=exc))


def _llm_returns(content: str = "pong"):
    return patch.object(ChatOpenAI, "ainvoke", AsyncMock(return_value=AIMessage(content=content)))


# 端点测试用的 app：不启 lifespan（`TestClient(app)` 不做上下文管理就不跑 startup）
def _app(monkeypatch, *, api_key_model: str = "_PassthroughOpenAI"):
    fake_settings = type(
        "S",
        (),
        {
            "APP_NAME": "ai-agent-service",
            "APP_VERSION": "1.0.0",
            "DEBUG": True,
            "API_PREFIX": "/api",
            "CORS_ALLOWED_ORIGINS": "http://localhost:3001",
        },
    )()
    monkeypatch.setattr(main_module, "settings", fake_settings)
    # 探针走 `LLMFactory.create_intent_llm()`：换成真实混入模型（不依赖环境里的 key 是否可用）
    monkeypatch.setattr(
        factory_module.LLMFactory,
        "create_intent_llm",
        staticmethod(lambda: _real_model(api_key_model)),
    )
    return main_module.create_app()


# ── 判据 1：401 ⇒ 进程级标志 + 恰好一条可行动 ERROR ────────────────────────────

class TestCredentialFailureBecomesOneObservableEvent:
    async def test_401_sets_flag_and_logs_exactly_one_actionable_error(self, health_records):
        llm = _real_model()

        with _llm_raises(_ProviderAuthError()):
            for _ in range(3):  # 线上形态：同一轮里意图分类 / 主循环 / 标题各自命中
                with pytest.raises(_ProviderAuthError):
                    await llm.ainvoke([HumanMessage(content="有哪些售后工单还没处理？")])

        assert llm_health.is_llm_auth_broken() is True, "401 必须置进程级标志（否则探针无从判断）"
        lines = _health_lines(health_records)
        assert len(lines) == 1, (
            f"确定性凭据失败只许落**恰好 1 条**事件日志（跃变语义），实得 {len(lines)}："
            f"{[r['message'] for r in lines]}"
        )
        message = lines[0]["message"]
        # 结构化字段（可 grep / 可聚合）
        assert "error_class=authentication_error" in message, message
        assert "status=401" in message, message
        # 可行动提示：不写「需更换 PRIMARY_API_KEY」= 运维只能继续翻日志（改前的病）
        assert "PRIMARY_API_KEY" in message, message
        assert "action=" in message, message
        # 一行 = 一条事件（多行异常消息会把检索撕开）
        assert "\n" not in message, message

    async def test_quota_402_is_the_same_deterministic_class(self, health_records):
        class _QuotaExceeded(RuntimeError):
            status_code = 402

        with _llm_raises(_QuotaExceeded("Error code: 402 - Insufficient Balance")):
            with pytest.raises(_QuotaExceeded):
                await _real_model().ainvoke([HumanMessage(content="今天经营怎么样？")])

        assert llm_health.is_llm_auth_broken() is True
        message = _health_lines(health_records)[0]["message"]
        assert "error_class=quota_exceeded" in message and "status=402" in message, message

    async def test_transient_errors_do_not_flip_the_flag(self, health_records):
        """供应商抖动（超时 / 5xx）**不进**本标志：那已有重试 + 熔断，混进来会变成抖动放大器。"""
        class _ServerError(RuntimeError):
            status_code = 503

        with _llm_raises(_ServerError("upstream 503")):
            with pytest.raises(_ServerError):
                await _real_model().ainvoke([HumanMessage(content="你好")])

        assert llm_health.is_llm_auth_broken() is False
        assert _health_lines(health_records) == []


# ── 判据 2 / 3：探针把「服务活着但 LLM 不可用」说清楚 ─────────────────────────

class TestReadOnlyProbe:
    def test_401_makes_the_probe_503_with_a_readable_snapshot(self, monkeypatch):
        app = _app(monkeypatch)

        with _llm_raises(_ProviderAuthError()):
            response = TestClient(app).get("/internal/llm-health")

        assert response.status_code == 503, "主凭据不可用时探针必须非 200"
        body = response.json()
        assert set(body) == {"ok", "last_error_class", "last_ok_at", "cached_at"}, body
        assert body["ok"] is False
        assert body["last_error_class"] == "authentication_error"
        assert body["last_ok_at"] is None, "从未成功过 ⇒ 不许伪造时间戳"

    def test_healthy_key_is_200_without_breaking_the_alarm(self, monkeypatch):
        app = _app(monkeypatch)  # 建 app 会重配 loguru ⇒ 捕获窗口必须开在它之后

        with _capture_error_records() as health_records, _llm_returns("pong"):
            response = TestClient(app).get("/internal/llm-health")

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["last_error_class"] is None
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", body["last_ok_at"] or "")
        assert _health_lines(health_records) == [], "真成功路径不许落凭据 ERROR"

    async def test_probe_is_cached_for_a_minute(self, monkeypatch):
        calls = AsyncMock(return_value=AIMessage(content="pong"))
        app = _app(monkeypatch)

        with patch.object(ChatOpenAI, "ainvoke", calls):
            client = TestClient(app)
            first = client.get("/internal/llm-health")
            second = client.get("/internal/llm-health")
            third = client.get("/internal/llm-health")
            assert calls.await_count == 1, f"60s 窗口内只许发 1 次真实调用，实得 {calls.await_count}"
            assert first.json()["ok"] is second.json()["ok"] is third.json()["ok"] is True

            # `force=True` 是运维手工复探的出口：必须真的再打一次
            await llm_health.llm_health_snapshot(force=True)
            assert calls.await_count == 2


# ── 判据 5：恢复自愈 + 事件可重新武装 ─────────────────────────────────────────

class TestRecovery:
    async def test_success_clears_the_flag(self):
        llm = _real_model()
        with _llm_raises(_ProviderAuthError()):
            with pytest.raises(_ProviderAuthError):
                await llm.ainvoke([HumanMessage(content="x")])
        assert llm_health.is_llm_auth_broken() is True

        with _llm_returns("pong"):
            await llm.ainvoke([HumanMessage(content="x")])

        assert llm_health.is_llm_auth_broken() is False, "恢复成功必须清标志（换 key 后不必重启探针）"

    async def test_a_new_failure_after_recovery_logs_again(self, health_records):
        """跃变语义：第二次故障是**新事件**，必须重新落一条（否则漏掉第二次事故）。"""
        llm = _real_model()
        with _llm_raises(_ProviderAuthError()):
            with pytest.raises(_ProviderAuthError):
                await llm.ainvoke([HumanMessage(content="x")])
        with _llm_returns("pong"):
            await llm.ainvoke([HumanMessage(content="x")])
        with _llm_raises(_ProviderAuthError()):
            with pytest.raises(_ProviderAuthError):
                await llm.ainvoke([HumanMessage(content="x")])

        assert len(_health_lines(health_records)) == 2


# ── 判据 6：`/ready` 语义不变（不许放大成容器 unhealthy → 重启 churn）───────────

class TestReadySemanticsUnchanged:
    def test_ready_stays_200_and_never_probes_the_llm(self, monkeypatch):
        app = _app(monkeypatch)
        readiness = AsyncMock(return_value=True)
        probe = AsyncMock(return_value=AIMessage(content="pong"))

        with patch("app.utils.health.check_readiness", readiness), \
                patch.object(ChatOpenAI, "ainvoke", probe):
            body = TestClient(app).get("/ready").json()

        assert body == {"status": "ready", "service": "ai-agent-service"}
        # `/ready` 一旦探 LLM ⇒ 供应商抖动会打红容器探针（本单明确不做那一形态）
        probe.assert_not_awaited()

    def test_ready_body_has_no_llm_degraded_field(self, monkeypatch):
        """选型是**独立端点**，不是「`/ready` 带 degraded 字段」——口径要在判据里钉死，防止两边都做。"""
        app = _app(monkeypatch)

        with patch("app.utils.health.check_readiness", AsyncMock(return_value=True)):
            body = TestClient(app).get("/ready").json()

        assert set(body) == {"status", "service"}


# ── 判据 7：接线（"判据绿但没接线"的形态）─────────────────────────────────────

class TestWiring:
    @pytest.mark.parametrize("cls_name", ["_PassthroughOpenAI", "_PassthroughDeepSeek"])
    def test_both_model_classes_carry_the_health_mixin(self, cls_name):
        cls = getattr(factory_module, cls_name)
        assert issubclass(cls, factory_module._LLMHealthChatModel), (
            f"{cls_name} 没挂凭据健康混入 ⇒ 该路径的 401 永远不会变成可观测事件"
        )
        assert cls.ainvoke is factory_module._LLMHealthChatModel.ainvoke, (
            "`ainvoke` 没解析到混入实现 ⇒ 记账被架空（判据绿但没接线）"
        )

    def test_mro_keeps_chatdeepseek_before_chatopenai(self):
        """混入插在前面不许破坏既有的 payload 口径（`tests/test_llm_message_payload.py` 同族）。"""
        from app.llm.message_payload import ReasoningPassthroughChatModel
        from langchain_deepseek import ChatDeepSeek

        mro = factory_module._PassthroughDeepSeek.__mro__
        assert mro[1] is ReasoningPassthroughChatModel, [c.__name__ for c in mro]
        assert mro.index(ChatDeepSeek) < mro.index(ChatOpenAI), [c.__name__ for c in mro]


# ── 判据 8：兜底句路径 vs 真成功路径（真入口 `execute_skill`）─────────────────

def _make_state(session_id: str = "sess_8084") -> dict:
    return {
        "messages": [HumanMessage(content="有哪些售后工单还没处理？")],
        "tenant_id": 46,
        "user_id": 100,
        "session_id": session_id,
        "role": "merchant",
        "intent_result": None,
        "route_decision": None,
        "entities": {},
        "intent_chain": [],
        "stage": "initial",
        "cached_answer": None,
        "final_answer": "",
        "skill_used": "",
    }


async def _run_one_turn(llm) -> dict:
    """跑一轮真入口 `execute_skill`；LLM 用真的工厂模型（混入在链上），行为由 `ChatOpenAI.ainvoke` 桩决定。"""
    registry = MagicMock()
    registry.get_langchain_tools.return_value = []
    registry.get_names.return_value = []

    breaker = MagicMock()

    async def _passthrough(fn):
        return await fn()

    breaker.call = _passthrough

    with patch.object(base_skill, "create_skill_registry", return_value=registry), \
            patch.object(base_skill, "set_tool_context"), \
            patch.object(base_skill, "get_skill_llm", return_value=llm), \
            patch.object(base_skill, "get_breaker", return_value=breaker):
        return await execute_skill(
            state=_make_state(),
            skill_name="customer_order",
            tool_names=[],
            system_prompt="你是测试助手",
        )


class TestFallbackPathVsSuccessPath:
    async def test_401_keeps_the_fallback_text_and_leaves_a_trace(self, health_records):
        with _llm_raises(_ProviderAuthError()):
            result = await _run_one_turn(_real_model())

        # ① 用户侧**不变**：仍是那句可重试的兜底（本单不改产品可见面）
        assert result["final_answer"] == FALLBACK_TEXT
        # ② 但这次失败**必须**留痕（"降级成通用兜底句而不留痕"正是本单要治的）
        assert llm_health.is_llm_auth_broken() is True
        assert len(_health_lines(health_records)) == 1

    async def test_real_success_path_does_not_report_a_credential_event(self, health_records):
        with _llm_returns("您好，有 3 张售后工单待处理。"):
            result = await _run_one_turn(_real_model())

        assert result["final_answer"] != FALLBACK_TEXT, "真成功路径不许回兜底句"
        assert "3 张售后工单" in result["final_answer"]
        assert llm_health.is_llm_auth_broken() is False
        assert _health_lines(health_records) == []


# ── 判据 9：类级元守卫 —— 探针必须声明「它到底探什么」─────────────────────────

#: 应用层探针台账（`app/main.py` 里的 `@app.get("/…")` 面）。
#: **新增探针未登记即红**：改前的病正是「`/ready` 只探 DB，却被当成人/编排眼里『AI 可用』的判据」
#: （issue #8084）—— 台账把「这条探针探的是什么」变成必须回答的问题，而不是靠读实现猜。
APP_LEVEL_PROBES = {
    "/health": "进程活着（恒 200，不探任何依赖）",
    "/ready": "DB + Redis（**不**探 LLM：供应商抖动会放大成容器 unhealthy → 重启 churn）",
    "/internal/llm-health": "LLM 主凭据（401 / 402 ⇒ ok=false + 503；60s 缓存一次最小真实调用）",
    "/version": "构建身份 sha / builtAt（空串 = 探不到，issue #8203）",
    "/api/version": "同上（与 /version 同一响应，运维只有一条命名口径）",
}


class TestProbeDeclarations:
    """**类级**守卫（不是单点）：探针是可以「看起来绿、其实没探到关键东西」的机制。"""

    def test_every_app_level_probe_is_declared(self):
        source = pathlib.Path(main_module.__file__).read_text(encoding="utf-8")
        registered = set(re.findall(r'@app\.get\("(/[^"]+)"\)', source))

        assert registered == set(APP_LEVEL_PROBES), (
            "应用层探针台账与实现不一致 —— 新增/删除探针必须同时改 APP_LEVEL_PROBES，"
            "并写清它**到底探什么**（`/ready` 只探 DB 却冒充 AI 可用就是本单的病）。"
            f"未登记={sorted(registered - set(APP_LEVEL_PROBES))} "
            f"已登记但实现里没有={sorted(set(APP_LEVEL_PROBES) - registered)}"
        )

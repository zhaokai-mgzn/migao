"""`app/api/migration.py` 模块镜像测试（issue #8295）—— 路由注册面 + 模型实例口径。

为什么单独一个文件而不是全塞进 `tests/test_customer_mapping.py`（本端点的行为测试）：
`tests/test_api_coverage.py` 要求**每个 `app/api/*.py` 业务模块**都有按模块名镜像的测试
（`tests/test_<模块名>.py`），模块叫 `migration` 而行为测试叫 `test_customer_mapping` ⇒
镜像判据会判「migration.py 缺测试」。两个文件各守一半，**不复制**同一批断言：
- 本文件：端点是否注册在**精确路径** / 不重复前缀；`create_mapping_llm` 的实例参数口径；
- `tests/test_customer_mapping.py`：脱敏、解析过滤、降级、入参校验等行为契约。
"""
# case_ids: MIG-001, MIG-002, MIG-003

import pytest

from app.config import settings
from app.llm.factory import LLMFactory

ENDPOINT = "/api/internal/migration/customer-mapping"


class TestRouteRegistration:
    def test_route_registered_at_exact_path(self):
        from app.main import create_app

        # 用 OpenAPI 的 paths 表判注册面：FastAPI 0.141 的 `app.routes` 里混有 `_IncludedRouter`
        # 这类无 `path` 属性的登记项，直接取 `route.path` 会 AttributeError。
        paths = set(create_app().openapi()["paths"])
        assert ENDPOINT in paths, f"端点未注册在 {ENDPOINT}"
        # 不重复前缀：/internal/migration/internal/... 这类形态不应存在
        assert not any(path.startswith("/api/internal/migration/internal") for path in paths)

    def test_existing_internal_routes_untouched(self):
        """新 include 不得挤掉既有内部端点（同一 `internal` tag 下的存量面）。"""
        from app.main import create_app

        paths = set(create_app().openapi()["paths"])
        assert "/api/internal/registration/review" in paths
        assert "/api/internal/tools/execute" in paths


class TestMappingLlmConfig:
    def test_config_matches_contract(self, monkeypatch):
        """temperature=0 / max_completion_tokens=1000 / thinking disabled / 复用 INTENT_MODEL。

        用替身截获 `_new_chat_model` 的入参：不构造真模型（测试环境没有真 Key、更不联网）。
        """
        import app.llm.factory as factory_module

        captured = {}
        sentinel = object()

        def _fake_new_chat_model(**kwargs):
            captured.update(kwargs)
            return sentinel

        monkeypatch.setattr(factory_module, "_new_chat_model", _fake_new_chat_model)
        llm = LLMFactory.create_mapping_llm()

        assert llm is sentinel
        assert captured["temperature"] == 0
        assert captured["max_completion_tokens"] == 1000
        assert captured["extra_body"] == {"thinking": {"type": "disabled"}}
        # 必须小于 admin-api `CustomerImportAiClient` 的 30s 读超时（否则上游先断、拿不到降级体）
        assert captured["request_timeout"] == 25
        assert captured["model"] == settings.INTENT_MODEL
        # 与 create_registration_review_llm 同一条「模型 / base_url / key」来源
        assert captured["api_key"] == factory_module.LLM_API_KEY
        assert captured["base_url"] == factory_module.LLM_BASE_URL

    def test_factory_is_static_and_requires_no_args(self):
        with pytest.raises(TypeError):
            LLMFactory.create_mapping_llm("unexpected-positional-arg")  # type: ignore[call-arg]

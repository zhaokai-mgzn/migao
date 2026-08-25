# case_ids: MC-007
"""配置单元测试（app/config.py）

覆盖：Settings 默认值 / MINIMAX_* & DASHSCOPE_* 向后兼容 / validate_production_secrets。
"""
import pytest

from app.config import Settings


def _make_settings(**overrides):
    """构造 Settings，注入全部必填字段，缺省给合法值。"""
    base = dict(
        DEBUG=False,
        HOST="0.0.0.0",
        PORT=8000,
        SERVICE_TOKEN="svc-token",
        JWT_PUBLIC_KEY="jwt-key",
        LOGISTICS_API_URL="https://wuliu.example.com",
        LOGISTICS_APPCODE="appcode",
        SSE_TIMEOUT=300,
        SSE_PING_INTERVAL=30,
        CORS_ALLOWED_ORIGINS="http://localhost:3000",
    )
    base.update(overrides)
    return Settings(**base)


class TestDefaults:
    def test_app_defaults(self):
        s = _make_settings()
        assert s.APP_NAME == "ai-agent-service"
        assert s.APP_VERSION == "1.0.0"
        assert s.DEBUG is False
        assert s.API_PREFIX == "/api"
        assert s.HOST == "0.0.0.0"
        assert s.PORT == 8000

    def test_llm_defaults(self):
        s = _make_settings()
        assert s.LLM_MODEL_PRIMARY == "deepseek-v4-pro"
        assert s.LLM_MODEL_FAST == "deepseek-v4-flash"
        assert s.INTENT_MODEL == "deepseek-v4-flash"
        assert s.LLM_ENABLE_MODEL_ROUTING is True
        assert s.LLM_COST_TRACKING_ENABLED is True
        assert s.LLM_MONTHLY_BUDGET_CNY == 500.0
        assert s.LLM_RETRY_MAX_ATTEMPTS == 2
        assert s.LLM_RETRY_BASE_DELAY_S == 0.5


class TestBackwardCompat:
    def test_minimax_api_key_primary_first(self):
        s = _make_settings(PRIMARY_API_KEY="p-key", VISION_API_KEY="v-key")
        assert s.MINIMAX_API_KEY == "p-key"

    def test_minimax_api_key_vision_fallback(self):
        s = _make_settings(PRIMARY_API_KEY="", VISION_API_KEY="v-key")
        assert s.MINIMAX_API_KEY == "v-key"

    def test_minimax_base_url_primary_first(self):
        s = _make_settings(PRIMARY_BASE_URL="p-url", VISION_BASE_URL="v-url")
        assert s.MINIMAX_BASE_URL == "p-url"

    def test_minimax_model_primary_first(self):
        s = _make_settings(PRIMARY_MODEL="p-model", VISION_MODEL="v-model")
        assert s.MINIMAX_MODEL == "p-model"

    def test_minimax_model_vision_fallback(self):
        s = _make_settings(PRIMARY_MODEL="", VISION_MODEL="v-model")
        assert s.MINIMAX_MODEL == "v-model"

    def test_dashscope_api_key_setter_writes_primary(self):
        s = _make_settings()
        s.DASHSCOPE_API_KEY = "dash-key"
        assert s.PRIMARY_API_KEY == "dash-key"

    def test_dashscope_base_url_setter_writes_vision(self):
        s = _make_settings()
        s.DASHSCOPE_BASE_URL = "dash-url"
        assert s.VISION_BASE_URL == "dash-url"

    def test_dashscope_model_setter_writes_primary(self):
        s = _make_settings()
        s.DASHSCOPE_MODEL = "dash-model"
        assert s.PRIMARY_MODEL == "dash-model"

    def test_dashscope_getters_match_primary_fallback(self):
        s = _make_settings(PRIMARY_API_KEY="p-key", PRIMARY_MODEL="p-model")
        assert s.DASHSCOPE_API_KEY == "p-key"
        assert s.DASHSCOPE_MODEL == "p-model"


class TestValidateProductionSecrets:
    def test_missing_jwt_public_key_raises(self):
        with pytest.raises(ValueError):
            _make_settings(DEBUG=False, JWT_PUBLIC_KEY="")

    def test_missing_service_token_raises(self):
        with pytest.raises(ValueError):
            _make_settings(DEBUG=False, SERVICE_TOKEN="")

    def test_debug_true_bypasses(self):
        s = _make_settings(DEBUG=True, JWT_PUBLIC_KEY="", SERVICE_TOKEN="")
        assert s.DEBUG is True

    def test_all_present_passes(self):
        s = _make_settings(DEBUG=False, JWT_PUBLIC_KEY="k", SERVICE_TOKEN="t")
        assert s.JWT_PUBLIC_KEY == "k"
        assert s.SERVICE_TOKEN == "t"

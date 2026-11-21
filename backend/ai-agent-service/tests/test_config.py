# case_ids: MC-007
"""配置单元测试（app/config.py）

覆盖：Settings 默认值 / LLM_* & DASHSCOPE_* 统一读取（原 MINIMAX_* 语义，已去品牌命名）/
validate_production_secrets。
"""
from pathlib import Path

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
        assert s.LLM_MODEL_PRIMARY == "deepseek-flash"
        assert s.LLM_MODEL_FAST == "deepseek-flash"
        assert s.INTENT_MODEL == "deepseek-flash"
        assert s.LLM_ENABLE_MODEL_ROUTING is True
        assert s.LLM_COST_TRACKING_ENABLED is True
        assert s.LLM_MONTHLY_BUDGET_CNY == 500.0
        assert s.LLM_RETRY_MAX_ATTEMPTS == 2
        assert s.LLM_RETRY_BASE_DELAY_S == 0.5
    def test_vision_defaults_deepseek(self):
        """视觉模型为 deepseek-flash（V4.1-Flash 原生多模态，2026-09-10 起统一模型名）"""
        s = _make_settings()
        assert s.VISION_MODEL == "deepseek-flash"
        assert s.VISION_BASE_URL == "https://api.deepseek.com/v1"
        assert s.VISION_ENABLED is True

    def test_audio_and_image_defaults_point_to_maas(self):
        """语音识别 / 商品生图 = 阿里云 MaaS token-plan（issue #7661，用户 2026-10-24 裁定）

        🔴 **主推理 / 视觉不动**：这两行断言就是「只切换语音与生图」的机器口径 ——
        有人顺手把 PRIMARY_MODEL 也换掉时，上面 `test_vision_defaults_deepseek` 先红。
        """
        s = _make_settings()
        assert s.ASR_MODEL == "qwen-audio-3.0-realtime-plus"
        assert s.ASR_WEBSOCKET_BASE_URL == (
            "wss://token-plan.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference"
        )
        assert s.IMAGE_GEN_MODELS == "qwen-image-3.0-pro"
        assert s.IMAGE_GEN_BASE_URL == (
            "https://token-plan.cn-beijing.maas.aliyuncs.com/api/v1/services/aigc/"
            "multimodal-generation/generation"
        )


class TestLlmCredentialAliases:
    """LLM_* 统一读取（PRIMARY 优先，VISION 兜底 —— 原 MINIMAX_* 语义）"""

    def test_llm_api_key_primary_first(self):
        s = _make_settings(PRIMARY_API_KEY="p-key", VISION_API_KEY="v-key")
        assert s.LLM_API_KEY == "p-key"

    def test_llm_api_key_vision_fallback(self):
        s = _make_settings(PRIMARY_API_KEY="", VISION_API_KEY="v-key")
        assert s.LLM_API_KEY == "v-key"

    def test_llm_base_url_primary_first(self):
        s = _make_settings(PRIMARY_BASE_URL="p-url", VISION_BASE_URL="v-url")
        assert s.LLM_BASE_URL == "p-url"

    def test_llm_model_primary_first(self):
        s = _make_settings(PRIMARY_MODEL="p-model", VISION_MODEL="v-model")
        assert s.LLM_MODEL == "p-model"

    def test_llm_model_vision_fallback(self):
        s = _make_settings(PRIMARY_MODEL="", VISION_MODEL="v-model")
        assert s.LLM_MODEL == "v-model"

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


# ══════════════════════════════════════════════════════════════════════════
# `JWT_PUBLIC_KEY` 支持 `file:<路径>`（issue #8976）
#
# 病（2026-11-21 生产实测）：admin-api 用 `.env.admin-api` 的 `JWT_*`
# （`file:/opt/migao-deploy/jwt/*.pem`）签发，ai-agent 用 compose 里**硬编码的 PEM** 验签
# ⇒ 同一个 token 两把钥匙 ⇒ 生产 AI 接口**全部 401**（`TOKEN_INVALID: Signature verification failed`），
# 且两侧都不报错、永远不会自己好。修法 = 密钥**单一来源**：ai-agent 也只给路径。
#
# 判据（每条都能单独变红）：
#   ① `file:` 解析成**内容**（= 那份文件里的 PEM）—— 删掉解析器 ⇒ 值是字面量 `file:…` ⇒ 红；
#   ② **兼容**：直接给 PEM 内容（本地 .env / CI 的既有形态）必须**原样**返回 —— 顺手改坏 ⇒ 红；
#   ③ **fail-closed**：文件不存在 / 不是公钥 PEM ⇒ 启动即抛 —— 静默放行 ⇒ 红
#      （放行 = 拿着一把错钥匙继续给所有请求回 401，那读起来像产品鉴权缺陷）。
# ⚠️ 判据用的是**入仓**的 admin-api 公钥（`backend/admin-api/src/main/resources/rsa/public.pem`）
#    —— 它就是两侧必须对齐的那份真值，不另造夹具（造一份就等于又长出第二个来源）。
# ══════════════════════════════════════════════════════════════════════════

REPO_ROOT = Path(__file__).resolve().parents[3]
COMMITTED_PUBLIC_PEM = REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "resources" / "rsa" / "public.pem"


def _committed_public_pem() -> str:
    assert COMMITTED_PUBLIC_PEM.is_file(), (
        f"入仓公钥不存在：{COMMITTED_PUBLIC_PEM} —— 判据无从行使（不得读成通过）"
    )
    return COMMITTED_PUBLIC_PEM.read_text(encoding="utf-8")


class TestJwtPublicKeyFilePrefix:
    def test_file_prefix_resolves_to_pem_content(self, tmp_path):
        """判据 ①：`file:<路径>` ⇒ 值是**文件内容**（且是公钥 PEM）。"""
        pem = _committed_public_pem()
        key_file = tmp_path / "public.pem"
        key_file.write_text(pem, encoding="utf-8")

        s = _make_settings(JWT_PUBLIC_KEY=f"file:{key_file}")

        assert "BEGIN PUBLIC KEY" in s.JWT_PUBLIC_KEY, (
            f"`file:` 没有被解析：值仍是 {s.JWT_PUBLIC_KEY[:24]!r} ⇒ ai-agent 会拿这个字符串去验签 ⇒ 全 401"
        )
        assert s.JWT_PUBLIC_KEY.strip() == pem.strip()

    def test_inline_pem_is_kept_verbatim(self):
        """判据 ②：直接给 PEM 内容（既有部署形态）⇒ **原样**返回，行为不变。"""
        pem = _committed_public_pem()
        assert _make_settings(JWT_PUBLIC_KEY=pem).JWT_PUBLIC_KEY == pem
        # 非 PEM 的历史值也不许被改写（既有单测用 "jwt-key" 这类占位值）
        assert _make_settings(JWT_PUBLIC_KEY="jwt-key").JWT_PUBLIC_KEY == "jwt-key"

    def test_missing_file_fails_closed(self, tmp_path):
        """判据 ③（a）：文件不存在 ⇒ **启动即失败**（不许静默降级）。"""
        missing = tmp_path / "nope" / "public.pem"
        with pytest.raises(ValueError) as exc:
            _make_settings(JWT_PUBLIC_KEY=f"file:{missing}")
        assert str(missing) in str(exc.value), f"报错必须点名那个路径（可行动）：{exc.value}"

    def test_non_pem_file_fails_closed(self, tmp_path):
        """判据 ③（b）：文件在、但不是公钥 PEM ⇒ **启动即失败**。"""
        bad = tmp_path / "public.pem"
        bad.write_text("not a pem\n", encoding="utf-8")
        with pytest.raises(ValueError):
            _make_settings(JWT_PUBLIC_KEY=f"file:{bad}")

    def test_private_pem_is_rejected(self, tmp_path):
        """判据 ③（c）：把**私钥**当公钥挂进来 ⇒ 判红（那是密钥泄漏面，不是「配错了也没事」）。"""
        # gitleaks 的 `private-key` 规则**只认 PEM 形状、不认内容真假**（`AAAA` 也命中）
        # ⇒ 标志必须**运行时拼**，源码里不得出现连续的一整段（也不许往 .gitleaksignore 塞指纹：
        #   那会让这条判据以后对真泄漏也失明）。
        dash5 = "-" * 5
        tag = dash5 + "BEGIN" + " " + "PRIVATE" + " KEY" + dash5
        end_tag = dash5 + "END" + " " + "PRIVATE" + " KEY" + dash5
        key_file = tmp_path / "public.pem"
        key_file.write_text(f"{tag}\nAAAA\n{end_tag}\n", encoding="utf-8")
        with pytest.raises(ValueError):
            _make_settings(JWT_PUBLIC_KEY=f"file:{key_file}")

"""
AI 智能客服系统 - AI Agent 服务配置
"""

from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """应用配置"""

    # 应用基础配置
    APP_NAME: str = "ai-agent-service"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    API_PREFIX: str = "/api"

    # ── DEBUG 降级身份的**目标租户**（issue #6288）─────────────────────────────
    # 单一真值：`app/utils/auth.py` 的 DEBUG 降级身份（C 端 customer / B 端管理员）
    # 与 `tests/agent_eval/local_runner.py` 的前置复位 / db 校验 SQL 都读本变量
    # （同一个环境变量名，两处**不得**再各写一份字面量）。
    # 取值真值（2026-10-19，issue #7340 收口）：评测租户统一为 **tenant 1**
    # （= 本地/CI 栈内种子租户；`fixtures/*_eval_seed.sql` 逐行写 tenant_id=1）。
    # 2026-10-04 曾把云测试租户改到 25；2026-10-19 共享库只剩 tenant 46，25 不存在
    # ⇒ 建会话 `sessions_tenant_id_fkey` 违例（#7340 实测）。现把本地栈、post-deploy-eval、
    # agent-eval 三处收敛到同一个 seed 租户 1，避免“服务端 1 / runner 25”再次分叉。
    # ⚠️ 本变量**不放宽**任何安全边界：它只决定「DEBUG 降级身份落到哪个租户」，
    # 非 DEBUG 分支（生产）仍然**只**从 JWT payload 取租户、不读本值（护栏见
    # `tests/unit_ci_workflows/test_eval_tenant_single_source.py`）。
    EVAL_TENANT_ID: int = 1

    # 服务器配置
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # PostgreSQL 配置
    DATABASE_URL: str = "postgresql+asyncpg://app_user:@localhost:5432/ai_customer_service"

    # Redis 配置
    REDIS_URL: str = "redis://localhost:6379/0"

    # ===== 必须由 SWAS 容器环境 / .env 注入（无默认值，漏配即报错）=====

    # 主 LLM（OpenAI 兼容接口，支持 DeepSeek/MiniMax/Qwen 等）
    PRIMARY_API_KEY: str = ""
    PRIMARY_BASE_URL: str = ""
    PRIMARY_MODEL: str = ""

    # 视觉多模态 LLM（图片识别）
    # 2026-09-10 起 DeepSeek-V4.1-Flash 原生多模态，模型名统一为 deepseek-flash
    # （旧的 deepseek-v4-flash-vision-exp 为临时兼容路由，随时可能下线）。
    # 与主模型共用 DeepSeek API key（推理/视觉同 key）
    VISION_API_KEY: str = ""
    VISION_BASE_URL: str = "https://api.deepseek.com/v1"
    VISION_MODEL: str = "deepseek-flash"
    VISION_ENABLED: bool = True

    # === 主 LLM 凭据统一读取（PRIMARY 优先，VISION 兜底 —— 原 MINIMAX_* 语义，已去品牌命名）===
    @property
    def LLM_API_KEY(self) -> str:
        return self.PRIMARY_API_KEY or self.VISION_API_KEY
    @property
    def LLM_BASE_URL(self) -> str:
        return self.PRIMARY_BASE_URL or self.VISION_BASE_URL
    @property
    def LLM_MODEL(self) -> str:
        return self.PRIMARY_MODEL or self.VISION_MODEL

    # === 向后兼容：旧 DASHSCOPE_* 配置作为 fallback（测试 monkeypatch 需要）===
    @property
    def DASHSCOPE_API_KEY(self) -> str:
        return self.PRIMARY_API_KEY or self.VISION_API_KEY
    @DASHSCOPE_API_KEY.setter
    def DASHSCOPE_API_KEY(self, value: str):
        self.PRIMARY_API_KEY = value

    @property
    def DASHSCOPE_BASE_URL(self) -> str:
        return self.PRIMARY_BASE_URL or self.VISION_BASE_URL
    @DASHSCOPE_BASE_URL.setter
    def DASHSCOPE_BASE_URL(self, value: str):
        self.VISION_BASE_URL = value

    @property
    def DASHSCOPE_MODEL(self) -> str:
        return self.PRIMARY_MODEL or self.VISION_MODEL
    @DASHSCOPE_MODEL.setter
    def DASHSCOPE_MODEL(self, value: str):
        self.PRIMARY_MODEL = value

    # 内部服务通信（由 main.tf locals 管理）
    ADMIN_API_BASE_URL: str = "http://localhost:8080"
    SERVICE_TOKEN: str
    JWT_PUBLIC_KEY: str

    # 物流查询 API（由 main.tf locals 管理）
    LOGISTICS_API_URL: str
    LOGISTICS_APPCODE: str

    # SSE / CORS / 图片 URL 重写（由 main.tf locals 管理）
    SSE_TIMEOUT: int
    SSE_PING_INTERVAL: int
    CORS_ALLOWED_ORIGINS: str
    IMAGE_URL_REWRITE_FROM: str = ""
    IMAGE_URL_REWRITE_TO: str = ""

    # ===== 功能开关与模型参数（有合理默认值，无需外部注入）=====

    # ===== 语音识别（ASR）+ 商品生图：阿里云 MaaS（token-plan 订阅）=====
    # 🔴 2026-10-24 用户裁定（issue #7661）：这两面切到 MaaS host，**主推理 / 视觉（DeepSeek）不动**。
    # **旧百炼 key 退役**：语音不再回落 PRIMARY_API_KEY（那是 DeepSeek 的 key，打到百炼只会 401）；
    # 未配置 ASR_API_KEY ⇒ 语音直接 fail-closed（503「未配置」），不静默拿错 key 去试。
    # 端点形态不是自创：dashscope SDK 的 MaaS 形态（dashscope/common/env.py）即
    #   http  → https://<host>/api/v1        实时 → wss://<host>/api-ws/v1/inference
    ASR_API_KEY: str = ""                                  # MaaS API Key（语音/生图共用；空 ⇒ fail-closed）
    ASR_MODEL: str = "qwen-audio-3.0-realtime-plus"        # 实时语音识别模型
    ASR_WEBSOCKET_BASE_URL: str = (
        "wss://token-plan.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference"
    )                                                      # 空 ⇒ 用 SDK 默认端点（回滚口）
    ASR_LANGUAGE_HINTS: str = "zh"                         # 默认语言/方言

    # 商品图生成（issue #7335）— MaaS 图生图（qwen-image 系列，原生多模态端点）。
    # Key 未单独配置时复用 ASR_API_KEY（同一个 MaaS 账号）；**不回落 PRIMARY_API_KEY**（DeepSeek Key）。
    # 模型按顺序轮换：配额类错误与「模型接不了该请求」才切下一个（见 app/images/generator.py 的边界 2）。
    IMAGE_GEN_ENABLED: bool = True
    IMAGE_GEN_API_KEY: str = ""
    # 2026-10-24 用户裁定（issue #7661）：qwen-image-3.0-pro（随 MaaS token-plan 一并开通）。
    # 改这一行请**同时**更新 .env.example、tests/test_generator.py 的裁定断言与
    # .github/cases/ui.yml 的 UI-129 判据 3 —— 四处同一个口径，缺一处就是漂移。
    IMAGE_GEN_MODELS: str = "qwen-image-3.0-pro"
    IMAGE_GEN_BASE_URL: str = (
        "https://token-plan.cn-beijing.maas.aliyuncs.com/api/v1/services/aigc/"
        "multimodal-generation/generation"
    )
    IMAGE_GEN_TIMEOUT: int = 180                           # 单次生图读超时（实测 30~60s）

    # ── 工具执行预算（issue #7707）───────────────────────────────────────
    # `_execute_tool_safe` 原来写死 30s（`asyncio.wait_for`）—— 生图是**慢工具**
    # （实测成功路径 30~60s）⇒ 评测/线上都会在 30s 被截成 `error="timeout"`。
    # 口径：全局默认 + 按工具名覆盖（`name=秒,name2=秒`），**只放宽慢工具**，
    # 不抬全局预算（那会把所有卡死工具都拖长一倍）。
    TOOL_TIMEOUT_S: float = 30.0
    TOOL_TIMEOUT_OVERRIDES: str = "product_image_generate=120"

    DASHSCOPE_EMBEDDING_MODEL: str = "text-embedding-v3"
    INTENT_MODEL: str = "deepseek-flash"                 # 意图分类/摘要（快速模型）

    # LLM 模型路由常量 — 所有模型名统一在 config.py 管理
    # 2026-09-10 DeepSeek-V4.1-Flash 发布，canonical 模型名 = deepseek-flash
    # （官方文档：deepseek-v4-flash / deepseek-v4-flash-vision-exp 已下线，
    #   仅作临时兼容路由指向 V4.1-Flash，禁止再作为新配置值）
    LLM_MODEL_PRIMARY: str = "deepseek-flash"            # 复杂推理 / 多工具 / 默认
    LLM_MODEL_FAST: str = "deepseek-flash"               # 轻量快速（意图路由、分类、摘要）

    LLM_ENABLE_MODEL_ROUTING: bool = True
    LLM_COST_TRACKING_ENABLED: bool = True
    LLM_MONTHLY_BUDGET_CNY: float = 500.0
    LLM_RETRY_MAX_ATTEMPTS: int = 2
    LLM_RETRY_BASE_DELAY_S: float = 0.5

    model_config = {"env_file": ".env", "case_sensitive": True, "extra": "ignore"}

    @model_validator(mode='after')
    def validate_production_secrets(self) -> 'Settings':
        """非 DEBUG 模式下强制验证关键安全配置不为空"""
        if not self.DEBUG:
            missing = []
            if not self.JWT_PUBLIC_KEY:
                missing.append('JWT_PUBLIC_KEY')
            if not self.SERVICE_TOKEN:
                missing.append('SERVICE_TOKEN')
            if missing:
                raise ValueError(
                    f"生产环境必须设置以下环境变量：{', '.join(missing)}。"
                    f"若在本地开发，请在 .env 文件中设置 DEBUG=true 绕过此校验。"
                )
        return self


settings = Settings()

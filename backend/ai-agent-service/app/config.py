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

    # 服务器配置
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # PostgreSQL 配置
    DATABASE_URL: str = "postgresql+asyncpg://app_user:@localhost:5432/ai_customer_service"

    # Redis 配置
    REDIS_URL: str = "redis://localhost:6379/0"

    # ===== 必须由 SAE / .env 注入（无默认值，漏配即报错）=====

    # 主 LLM（OpenAI 兼容接口，支持 DeepSeek/MiniMax/Qwen 等）
    PRIMARY_API_KEY: str = ""
    PRIMARY_BASE_URL: str = ""
    PRIMARY_MODEL: str = ""

    # 视觉多模态 LLM（独立配置，可不同于主模型）
    VISION_API_KEY: str = ""
    VISION_BASE_URL: str = ""
    VISION_MODEL: str = "MiniMax-M3"

    # === 向后兼容：旧 MINIMAX_* 配置作为 fallback ===
    @property
    def MINIMAX_API_KEY(self) -> str:
        return self.PRIMARY_API_KEY or self.VISION_API_KEY
    @property
    def MINIMAX_BASE_URL(self) -> str:
        return self.PRIMARY_BASE_URL or self.VISION_BASE_URL
    @property
    def MINIMAX_MODEL(self) -> str:
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
    ADMIN_API_BASE_URL: str
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

    INTENT_MODEL: str = "deepseek-v4-flash"              # 意图分类/摘要（快速模型）
    MINIMAX_VISION_MODEL: str = "MiniMax-M3"            # 图片识别（M3 原生多模态）
    MINIMAX_VISION_ENABLED: bool = True

    # LLM 模型路由常量 — 所有模型名统一在 config.py 管理
    LLM_MODEL_PRIMARY: str = "deepseek-v4-pro"           # 复杂推理 / 多工具 / 视觉 / 默认
    LLM_MODEL_FAST: str = "deepseek-v4-flash"            # 轻量快速（意图路由、分类、摘要）

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

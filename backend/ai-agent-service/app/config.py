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

    # MiniMax M3 LLM（OpenAI 兼容接口）
    MINIMAX_API_KEY: str
    MINIMAX_BASE_URL: str
    MINIMAX_MODEL: str

    # 内部服务通信（由 main.tf locals 管理）
    ADMIN_API_BASE_URL: str
    SERVICE_TOKEN: str
    JWT_PUBLIC_KEY: str

    # 物流查询 API（由 main.tf locals 管理）
    LOGISTICS_API_URL: str
    LOGISTICS_APPCODE: str

    # SSE / CORS（由 main.tf locals 管理）
    SSE_TIMEOUT: int
    SSE_PING_INTERVAL: int
    CORS_ALLOWED_ORIGINS: str

    # ===== 功能开关与模型参数（有合理默认值，无需外部注入）=====

    INTENT_MODEL: str = "MiniMax-M2.7-highspeed"        # 意图分类/摘要（快速模型）
    MINIMAX_VISION_MODEL: str = "MiniMax-M3"            # 图片识别（M3 原生多模态）
    MINIMAX_VISION_ENABLED: bool = True

    # LLM 模型路由常量 — 所有模型名统一在 config.py 管理
    LLM_MODEL_PRIMARY: str = "MiniMax-M3"               # 复杂推理 / 多工具 / 视觉 / 默认
    LLM_MODEL_FAST: str = "MiniMax-M2.7-highspeed"      # 轻量快速（意图路由、分类、摘要）

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

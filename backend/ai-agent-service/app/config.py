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

    # CORS 允许的前端域名（逗号分隔）
    CORS_ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:3001,http://127.0.0.1:3000,http://127.0.0.1:3001"

    # 服务器配置
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # PostgreSQL 配置
    DATABASE_URL: str = "postgresql+asyncpg://app_user:@localhost:5432/ai_customer_service"

    # Redis 配置
    REDIS_URL: str = "redis://localhost:6379/0"

    # ===== 必须由 SAE / .env 注入（无默认值，漏配即报错）=====

    # 阿里云百炼 LLM（由 main.tf locals 管理）
    DASHSCOPE_API_KEY: str
    DASHSCOPE_BASE_URL: str
    DASHSCOPE_MODEL: str
    DASHSCOPE_EMBEDDING_MODEL: str

    # DashVector 向量库（由 main.tf locals 管理）
    DASHVECTOR_API_KEY: str
    DASHVECTOR_ENDPOINT: str
    DASHVECTOR_COLLECTION: str

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

    INTENT_MODEL: str = "qwen3.6-flash"                  # 意图分类模型（轻量快速，关闭思考模式）
    DASHSCOPE_VISION_MODEL: str = "qwen3.6-flash"       # 图片识别模型（轻量推理 + 视觉理解）
    DASHSCOPE_VISION_ENABLED: bool = True

    # LLM 模型路由常量 — 所有模型名统一在 config.py 管理，禁止在其他文件中硬编码
    # 当百炼下线/更名模型时，只需修改此处
    LLM_MODEL_MAX: str = "qwen3.7-max"       # 复杂推理 / 多工具协同
    LLM_MODEL_PLUS: str = "qwen3.6-plus"     # 默认平衡档
    LLM_MODEL_LITE: str = "qwen3.6-flash"   # 轻量快速（简单意图路由、分类等低延迟场景）
    LLM_MODEL_FLASH: str = "qwen3.6-flash"   # 极简任务（最低延迟场景）

    SEMANTIC_CACHE_ENABLED: bool = False  # Embedding API key 未就绪，暂时关闭
    SEMANTIC_CACHE_SIMILARITY_THRESHOLD: float = 0.95
    SEMANTIC_CACHE_MAX_ENTRIES: int = 1000

    RERANK_ENABLED: bool = True
    RERANK_MODEL: str = "gte-rerank"
    RERANK_TOP_K: int = 3
    RETRIEVAL_TOP_K: int = 10

    LLM_ENABLE_MODEL_ROUTING: bool = True
    LLM_COST_TRACKING_ENABLED: bool = True
    LLM_MONTHLY_BUDGET_CNY: float = 500.0
    LLM_RETRY_MAX_ATTEMPTS: int = 2
    LLM_RETRY_BASE_DELAY_S: float = 0.5

    # 图片 URL 重写：CDN 域名 → OSS 公网域名
    # DashScope Vision API 需要公网可访问的 HTTPS URL，
    # 但 admin-api 返回的图片 URL 使用 CDN 域名（如 https://admin.migaozn.com），
    # 该域名可能未正确配置 DNS/CDN，导致 DashScope 无法访问。
    # 配置后将自动替换：IMAGE_URL_REWRITE_FROM → IMAGE_URL_REWRITE_TO
    IMAGE_URL_REWRITE_FROM: str = ""  # e.g., "https://admin.migaozn.com"
    IMAGE_URL_REWRITE_TO: str = ""    # e.g., "https://youke-admin-dev.oss-cn-hangzhou.aliyuncs.com"

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

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

    # 阿里云百炼 Embedding（RAG 仍用百炼）
    DASHSCOPE_API_KEY: str
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

    INTENT_MODEL: str = "MiniMax-M2.7-highspeed"       # 意图分类/摘要（快速模型，不开思考）
    MINIMAX_VISION_MODEL: str = "MiniMax-M3"           # 图片识别（M3 原生多模态）
    MINIMAX_VISION_ENABLED: bool = True

    # LLM 模型路由常量 — 所有模型名统一在 config.py 管理，禁止在其他文件中硬编码
    LLM_MODEL_PRIMARY: str = "MiniMax-M3"              # 复杂推理 / 多工具协同 / 默认
    LLM_MODEL_FAST: str = "MiniMax-M2.7-highspeed"     # 轻量快速（意图路由、分类、摘要等低延迟场景）

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
    # Vision API 需要公网可访问的 HTTPS URL，
    # 但 admin-api 返回的图片 URL 使用 CDN 域名（如 https://admin.migaozn.com），
    # 该域名可能未正确配置 DNS/CDN，导致 Vision API 无法访问。
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

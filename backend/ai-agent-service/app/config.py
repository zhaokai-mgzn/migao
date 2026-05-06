"""
AI 智能客服系统 - AI Agent 服务配置
"""

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

    # 阿里云百炼 LLM 配置
    DASHSCOPE_API_KEY: str = ""
    DASHSCOPE_MODEL: str = "qwen3.6-plus"
    DASHSCOPE_EMBEDDING_MODEL: str = "text-embedding-v3"

    # 意图分类小模型配置
    INTENT_MODEL: str = "qwen-turbo"

    # DashVector 配置
    DASHVECTOR_API_KEY: str = ""
    DASHVECTOR_ENDPOINT: str = ""
    DASHVECTOR_COLLECTION: str = "ai_customer_service"

    # Admin API 服务地址（内部调用）
    ADMIN_API_BASE_URL: str = "http://admin-api:8080"

    # Service Token（用于调用 admin-api）
    SERVICE_TOKEN: str = ""

    # JWT 公钥（用于验证用户 Token）
    JWT_PUBLIC_KEY: str = ""

    # 物流查询 API 配置（阿里云市场）
    LOGISTICS_API_URL: str = "https://wuliu.market.alicloudapi.com/kdi"
    LOGISTICS_APPCODE: str = ""

    # 语义缓存配置
    SEMANTIC_CACHE_ENABLED: bool = True
    SEMANTIC_CACHE_SIMILARITY_THRESHOLD: float = 0.95
    SEMANTIC_CACHE_MAX_ENTRIES: int = 1000

    # Reranker 配置
    RERANK_ENABLED: bool = True
    RERANK_MODEL: str = "gte-rerank"
    RERANK_TOP_K: int = 3
    RETRIEVAL_TOP_K: int = 10

    # SSE 配置
    SSE_TIMEOUT: int = 300  # 5 分钟
    SSE_PING_INTERVAL: int = 30  # 30 秒心跳

    model_config = {"env_file": ".env", "case_sensitive": True, "extra": "ignore"}


settings = Settings()

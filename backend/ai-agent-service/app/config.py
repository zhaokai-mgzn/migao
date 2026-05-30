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

    # 阿里云百炼 LLM 配置
    DASHSCOPE_API_KEY: str = ""
    DASHSCOPE_MODEL: str = "qwen3.7-max"
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

    # LLM 管道配置（Factory / Router / CostTracker / Retry）
    LLM_ENABLE_MODEL_ROUTING: bool = True       # 模型路由开关（默认开启，按场景智能路由）
    LLM_COST_TRACKING_ENABLED: bool = True      # 成本追踪开关
    LLM_MONTHLY_BUDGET_CNY: float = 500.0       # 月预算（元），<=0 表示不限
    LLM_RETRY_MAX_ATTEMPTS: int = 2             # 最大重试次数（不含首次调用）
    LLM_RETRY_BASE_DELAY_S: float = 0.5         # 重试基础延迟（秒），指数退避基数

    # --- 多模态视觉模型配置 ---
    DASHSCOPE_VISION_MODEL: str = "qwen-vl-plus"
    DASHSCOPE_VISION_ENABLED: bool = True

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

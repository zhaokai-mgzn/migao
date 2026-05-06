"""应用配置管理"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """应用配置"""
    
    # 应用配置
    APP_NAME: str = "AI Customer Service"
    APP_ENV: str = "development"
    DEBUG: bool = True
    SECRET_KEY: str = "dev-secret-key"
    
    # 阿里云百炼配置
    DASHSCOPE_API_KEY: str
    DASHSCOPE_MODEL: str = "qwen-turbo"
    
    # 数据库配置
    DATABASE_URL: str = "postgresql+asyncpg://user:password@localhost:5432/ai_customer_service"
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Celery 配置
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    
    # 日志配置
    LOG_LEVEL: str = "DEBUG"
    LOG_FILE: str = "logs/app.log"
    
    # 向量数据库配置
    VECTOR_DB_TYPE: str = "faiss"
    VECTOR_DB_PATH: str = "data/vector_store"
    
    # 知识库配置
    KNOWLEDGE_BASE_PATH: str = "knowledge_base"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()


settings = get_settings()

"""  
AI 智能客服系统 - 数据库连接模块

使用 SQLAlchemy 2.0 async + asyncpg 实现异步数据库操作
"""

from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool, QueuePool
from loguru import logger

from app.config import settings

# 根据环境选择连接池
# 开发环境：NullPool 简化配置
# 生产环境：QueuePool 提高性能
is_dev = settings.DEBUG

if is_dev:
    # 开发环境使用 NullPool
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=settings.DEBUG,  # 调试模式下打印 SQL
        future=True,
        poolclass=NullPool,
    )
    logger.info("Database engine created with NullPool (development mode)")
else:
    # 生产环境使用 QueuePool
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        future=True,
        pool_size=20,  # 连接池大小
        max_overflow=10,  # 最大溢出连接数
        pool_timeout=30,  # 获取连接超时时间（秒）
        pool_recycle=3600,  # 连接回收时间（秒）
        pool_pre_ping=True,  # 使用前检查连接是否有效
    )
    logger.info("Database engine created with QueuePool (production mode)")

# 创建异步会话工厂
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# 声明性基类
Base = declarative_base()


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    获取数据库会话的依赖注入函数
    
    使用方式：
        @router.get("/items")
        async def get_items(db: AsyncSession = Depends(get_db_session)):
            result = await db.execute(select(Item))
            return result.scalars().all()
    
    Yields:
        AsyncSession: SQLAlchemy 异步会话
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error(f"Database session error: {e}")
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """
    初始化数据库连接
    
    在应用启动时调用，验证数据库连接是否正常
    """
    try:
        from sqlalchemy import text
        async with engine.begin() as conn:
            # 测试连接
            await conn.execute(text("SELECT 1"))
        logger.info("Database connection initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database connection: {e}")
        raise


async def close_db() -> None:
    """
    关闭数据库连接
    
    在应用关闭时调用，释放所有连接池资源
    """
    await engine.dispose()
    logger.info("Database connection closed")

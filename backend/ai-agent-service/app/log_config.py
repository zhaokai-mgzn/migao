# app/log_config.py
import sys
from pathlib import Path
from loguru import logger


def setup_logging(debug: bool = False):
    """初始化日志系统"""

    # 移除默认处理器
    logger.remove()

    # 控制台输出
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="DEBUG" if debug else "INFO",
    )

    # 文件输出（按日期轮转）
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    logger.add(
        log_dir / "ai_agent_{time:YYYY-MM-DD}.log",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
        rotation="500 MB",
        retention="30 days",
        level="DEBUG" if debug else "INFO",
        compression="zip",
    )

    # 错误日志单独输出
    logger.add(
        log_dir / "ai_agent_error_{time:YYYY-MM-DD}.log",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
        level="ERROR",
        rotation="500 MB",
        retention="30 days",
        compression="zip",
    )

    logger.info("Logging system initialized (debug={})", debug)

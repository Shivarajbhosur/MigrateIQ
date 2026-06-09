"""
Logging configuration for Validation Agent.
"""

import sys
from loguru import logger

import config


def setup_logger():
    """Configure logger."""
    
    # Remove default handler
    logger.remove()
    
    # Console output
    logger.add(
        sys.stdout,
        level=config.LOG_LEVEL,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan> - <level>{message}</level>",
        colorize=True,
    )
    
    # File output
    log_file = config.LOGS_PATH / "validation_agent.log"
    logger.add(
        log_file,
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name} - {message}",
        rotation="1 day",
        retention="7 days",
    )
    
    return logger


# Initialize logger
setup_logger()


def get_logger(name: str = "validation_agent"):
    """Get a logger instance."""
    return logger.bind(name=name)
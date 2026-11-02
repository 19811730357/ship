"""
统一的日志配置模块
提供彩色、格式化的日志输出
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

# ANSI 颜色代码
class LogColors:
    RESET = '\033[0m'
    BOLD = '\033[1m'

    # 前景色
    BLACK = '\033[30m'
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    WHITE = '\033[37m'

    # 背景色
    BG_RED = '\033[41m'
    BG_GREEN = '\033[42m'
    BG_YELLOW = '\033[43m'
    BG_BLUE = '\033[44m'


class ColoredFormatter(logging.Formatter):
    """彩色日志格式化器"""

    FORMATS = {
        logging.DEBUG: LogColors.CYAN + '%(levelname)-8s' + LogColors.RESET + ' [%(name)s] %(message)s',
        logging.INFO: LogColors.GREEN + '%(levelname)-8s' + LogColors.RESET + ' [%(name)s] %(message)s',
        logging.WARNING: LogColors.YELLOW + '%(levelname)-8s' + LogColors.RESET + ' [%(name)s] %(message)s',
        logging.ERROR: LogColors.RED + '%(levelname)-8s' + LogColors.RESET + ' [%(name)s] %(message)s',
        logging.CRITICAL: LogColors.BG_RED + LogColors.WHITE + '%(levelname)-8s' + LogColors.RESET + ' [%(name)s] %(message)s',
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)


def setup_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """
    设置日志记录器

    Args:
        name: 日志记录器名称（通常是模块名）
        level: 日志级别

    Returns:
        配置好的日志记录器
    """
    logger = logging.getLogger(name)

    # 避免重复添加 handler
    if logger.handlers:
        return logger

    logger.setLevel(level)

    # 控制台输出
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(ColoredFormatter())
    logger.addHandler(console_handler)

    # 文件输出（可选）
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    file_handler = logging.FileHandler(
        log_dir / f"billing_agent_{datetime.now().strftime('%Y%m%d')}.log",
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            '%(asctime)s - %(name)-20s - %(levelname)-8s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    )
    logger.addHandler(file_handler)

    return logger


def log_section(logger: logging.Logger, title: str, level: int = logging.INFO):
    """
    输出带分隔线的章节标题

    Args:
        logger: 日志记录器
        title: 章节标题
        level: 日志级别
    """
    separator = "=" * 70
    logger.log(level, f"\n{separator}")
    logger.log(level, f"{title}")
    logger.log(level, separator)


def log_dict(logger: logging.Logger, data: dict, title: str = None, level: int = logging.INFO):
    """
    格式化输出字典内容

    Args:
        logger: 日志记录器
        data: 要输出的字典
        title: 标题
        level: 日志级别
    """
    if title:
        logger.log(level, f"\n{title}:")

    import json
    formatted = json.dumps(data, indent=2, ensure_ascii=False, default=str)
    for line in formatted.split('\n'):
        logger.log(level, f"  {line}")


def log_list(logger: logging.Logger, items: list, title: str = None, level: int = logging.INFO):
    """
    格式化输出列表内容

    Args:
        logger: 日志记录器
        items: 要输出的列表
        title: 标题
        level: 日志级别
    """
    if title:
        logger.log(level, f"\n{title}:")

    for i, item in enumerate(items, 1):
        logger.log(level, f"  {i}. {item}")


# 预定义的模块日志记录器
def get_parser_logger():
    """解析器日志"""
    return setup_logger("📄 Parser")


def get_ocr_logger():
    """OCR日志"""
    return setup_logger("👁️  OCR")


def get_agent_logger():
    """Agent日志"""
    return setup_logger("🤖 Agent")


def get_validator_logger():
    """验证器日志"""
    return setup_logger("🔍 Validator")


def get_crud_logger():
    """CRUD执行器日志"""
    return setup_logger("💾 CRUD")


def get_database_logger():
    """数据库日志"""
    return setup_logger("🗄️  Database")


def get_workflow_logger():
    """工作流日志"""
    return setup_logger("⚙️  Workflow")

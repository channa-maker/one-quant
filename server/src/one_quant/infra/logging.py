"""
ONE量化 - 结构化日志

JSON 格式日志 + 中文摘要 + log_mask 脱敏。
敏感信息（API Key、密码、Token）永不进日志。
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
from typing import Any


# 需要脱敏的字段名模式
_SENSITIVE_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|password|token|passphrase|private[_-]?key)"),
]


def log_mask(value: str) -> str:
    """对敏感字符串脱敏。

    保留前 4 位和后 4 位，中间用 *** 替代。

    Args:
        value: 原始字符串。

    Returns:
        脱敏后的字符串。
    """
    if len(value) <= 8:
        return "***"
    return value[:4] + "***" + value[-4:]


def _mask_dict(obj: Any, depth: int = 0) -> Any:
    """递归脱敏字典中的敏感字段。"""
    if depth > 10:
        return obj

    if isinstance(obj, dict):
        result = {}
        for key, val in obj.items():
            if any(p.search(key) for p in _SENSITIVE_PATTERNS):
                result[key] = "***MASKED***"
            else:
                result[key] = _mask_dict(val, depth + 1)
        return result
    elif isinstance(obj, list):
        return [_mask_dict(item, depth + 1) for item in obj]
    return obj


class StructuredFormatter(logging.Formatter):
    """结构化 JSON 日志格式化器。

    输出格式：
    {
        "timestamp": "2024-01-01T00:00:00.000Z",
        "level": "INFO",
        "logger": "one_quant.xxx",
        "message": "中文摘要",
        "extra": {...}
    }
    """

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {
            "timestamp": time.strftime(
                "%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # 附加额外字段
        if hasattr(record, "extra_data"):
            log_data["extra"] = _mask_dict(record.extra_data)

        # 异常信息
        if record.exc_info and record.exc_info[1]:
            log_data["exception"] = str(record.exc_info[1])

        return json.dumps(log_data, ensure_ascii=False, default=str)


def setup_logging(level: str = "INFO", json_format: bool = True) -> None:
    """配置全局日志。

    Args:
        level: 日志级别。
        json_format: 是否使用 JSON 格式。
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # 清除已有 handler
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    if json_format:
        handler.setFormatter(StructuredFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )

    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """获取日志器。

    Args:
        name: 日志器名称。

    Returns:
        日志器实例。
    """
    return logging.getLogger(name)

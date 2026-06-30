"""
ONE量化 - 结构化日志

基于 structlog 实现 JSON 格式结构化日志。
内置敏感字段脱敏处理器，确保密钥等敏感信息不会泄露到日志。
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional, Sequence

import structlog


# ---------------------------------------------------------------------------
# 默认脱敏字段列表
# ---------------------------------------------------------------------------
_DEFAULT_MASK_KEYS: frozenset[str] = frozenset({
    "api_key",
    "apikey",
    "api-key",
    "secret",
    "secret_key",
    "secretkey",
    "secret-key",
    "token",
    "access_token",
    "refresh_token",
    "password",
    "passwd",
    "pwd",
    "private_key",
    "privatekey",
    "private-key",
    "passphrase",
    "authorization",
    "x-api-key",
})


# ---------------------------------------------------------------------------
# 脱敏函数
# ---------------------------------------------------------------------------
def log_mask(
    data: dict[str, Any],
    mask_keys: Optional[Sequence[str]] = None,
    replacement: str = "***",
) -> dict[str, Any]:
    """
    对字典中的敏感字段进行脱敏处理。

    递归遍历嵌套字典，将匹配的键值替换为 ``replacement``。

    Args:
        data: 待脱敏的字典数据
        mask_keys: 需要脱敏的键名列表。为 None 时使用默认列表。
        replacement: 替换文本，默认 ``"***"``

    Returns:
        脱敏后的新字典（不修改原字典）

    示例::

        >>> log_mask({"api_key": "sk-abc123", "name": "test"})
        {"api_key": "***", "name": "test"}
    """
    keys_to_mask = set(mask_keys) if mask_keys is not None else _DEFAULT_MASK_KEYS
    return _mask_recursive(data, keys_to_mask, replacement)


def _mask_recursive(
    obj: Any,
    keys_to_mask: set[str],
    replacement: str,
) -> Any:
    """递归脱敏辅助函数"""
    if isinstance(obj, dict):
        result: dict[str, Any] = {}
        for key, value in obj.items():
            # 键名匹配（不区分大小写，去除首尾空格和连字符后比较）
            normalized = key.strip().lower().replace("-", "_").replace(" ", "_")
            if normalized in keys_to_mask:
                result[key] = replacement
            else:
                result[key] = _mask_recursive(value, keys_to_mask, replacement)
        return result
    elif isinstance(obj, (list, tuple)):
        return type(obj)(_mask_recursive(item, keys_to_mask, replacement) for item in obj)
    else:
        return obj


# ---------------------------------------------------------------------------
# structlog 处理器: 中文摘要
# ---------------------------------------------------------------------------
def _chinese_summary_processor(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """
    中文摘要处理器。

    如果事件中包含 ``summary_zh`` 字段，将其提升为 ``msg`` 的前缀，
    便于中文日志检索。
    """
    summary = event_dict.pop("summary_zh", None)
    if summary is not None:
        original_msg = event_dict.get("event", "")
        event_dict["event"] = f"[{summary}] {original_msg}" if original_msg else summary
    return event_dict


# ---------------------------------------------------------------------------
# structlog 处理器: 自动脱敏
# ---------------------------------------------------------------------------
def _auto_mask_processor(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """
    自动脱敏处理器。

    对 event_dict 中所有顶层键进行脱敏检查。
    """
    return log_mask(event_dict)


# ---------------------------------------------------------------------------
# structlog 配置
# ---------------------------------------------------------------------------
def setup_logging(
    level: str = "INFO",
    mask_keys: Optional[Sequence[str]] = None,
) -> None:
    """
    初始化 structlog 全局配置。

    配置链:
    1. 添加日志级别、时间戳
    2. 执行中文摘要处理器
    3. 执行自动脱敏处理器
    4. 格式化为 JSON 输出

    Args:
        level: 日志级别，默认 INFO
        mask_keys: 自定义脱敏键名列表，None 使用默认列表
    """
    # 如果传入了自定义脱敏键，更新模块级默认值
    if mask_keys is not None:
        global _DEFAULT_MASK_KEYS
        _DEFAULT_MASK_KEYS = frozenset(mask_keys)

    structlog.configure(
        processors=[
            # 添加日志级别
            structlog.stdlib.add_log_level,
            # 添加时间戳 (ISO 格式)
            structlog.processors.TimeStamper(fmt="iso"),
            # 中文摘要处理器
            _chinese_summary_processor,
            # 自动脱敏
            _auto_mask_processor,
            # 如果在标准库 logger 中，添加调用者信息
            structlog.stdlib.add_logger_name,
            structlog.stdlib.PositionalArgumentsFormatter(),
            # 堆栈信息
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            # Unicode 处理
            structlog.processors.UnicodeDecoder(),
            # JSON 渲染
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # 同步配置标准库 logging，确保 structlog 与标准库共存
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, level.upper(), logging.INFO),
    )


# ---------------------------------------------------------------------------
# 工厂函数
# ---------------------------------------------------------------------------
def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """
    获取结构化日志实例。

    Args:
        name: 日志器名称，通常为模块路径，如 ``"one_quant.infra.config"``

    Returns:
        structlog 绑定日志器实例

    使用示例::

        logger = get_logger(__name__)
        logger.info("策略启动", strategy="momentum_v1", symbols=100)
        logger.warning("风控触发", summary_zh="回撤超过阈值", drawdown=0.18)
    """
    return structlog.get_logger(name)

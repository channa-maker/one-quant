"""
ONE量化 - 基础设施层

提供配置、日志、消息信封、插件注册表等基础组件。
"""

from one_quant.infra.config import (
    AISettings,
    DatabaseSettings,
    ExchangeSettings,
    RedisSettings,
    RiskSettings,
    Settings,
    get_settings,
)
from one_quant.infra.logging import get_logger, log_mask, setup_logging
from one_quant.infra.message_envelope import MessageEnvelope, create_envelope
from one_quant.infra.registry import (
    ALGO_REGISTRY,
    AGENT_REGISTRY,
    FACTOR_REGISTRY,
    SOURCE_REGISTRY,
    STRATEGY_REGISTRY,
    Registry,
    register_agent,
    register_algo,
    register_factor,
    register_source,
    register_strategy,
)

__all__ = [
    # 配置
    "AISettings",
    "DatabaseSettings",
    "ExchangeSettings",
    "RedisSettings",
    "RiskSettings",
    "Settings",
    "get_settings",
    # 日志
    "get_logger",
    "log_mask",
    "setup_logging",
    # 消息信封
    "MessageEnvelope",
    "create_envelope",
    # 注册表
    "ALGO_REGISTRY",
    "AGENT_REGISTRY",
    "FACTOR_REGISTRY",
    "SOURCE_REGISTRY",
    "STRATEGY_REGISTRY",
    "Registry",
    "register_agent",
    "register_algo",
    "register_factor",
    "register_source",
    "register_strategy",
]

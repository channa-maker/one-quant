"""基础设施模块 — 配置、日志、EventBus、注册表、消息信封、持久化、指标"""

from one_quant.infra.config import Settings, get_settings
from one_quant.infra.event_bus import EventBus, InMemoryEventBus, RedisEventBus
from one_quant.infra.logging import get_logger, setup_logging
from one_quant.infra.message_envelope import MessageEnvelope, create_envelope
from one_quant.infra.metrics import (
    DATA_BRONZE_WRITES,
    DATA_QUALITY_ALERTS,
    DATA_QUALITY_CHECKS,
    EVENTBUS_CONSUME_LATENCY,
    EVENTBUS_CONSUME_TOTAL,
    EVENTBUS_PUBLISH_TOTAL,
    FILLS_TOTAL,
    MARKET_DATA_AGE_SECONDS,
    MARKET_GATEWAY_CONNECTED,
    MARKET_GATEWAY_RECONNECTS,
    MARKET_MESSAGES_TOTAL,
    ORDERS_TOTAL,
    PORTFOLIO_VALUE,
    RISK_DECISION_LATENCY,
    RISK_DECISIONS_TOTAL,
    UNREALIZED_PNL,
)
from one_quant.infra.registry import (
    FACTOR_REGISTRY,
    STRATEGY_REGISTRY,
    Registry,
    register_factor,
    register_strategy,
)
from one_quant.infra.stream_persistence import StreamPersistence

__all__ = [
    "Settings",
    "get_settings",
    "setup_logging",
    "get_logger",
    "EventBus",
    "InMemoryEventBus",
    "RedisEventBus",
    "StreamPersistence",
    "MessageEnvelope",
    "create_envelope",
    "Registry",
    "STRATEGY_REGISTRY",
    "FACTOR_REGISTRY",
    "register_strategy",
    "register_factor",
    # metrics
    "MARKET_MESSAGES_TOTAL",
    "MARKET_DATA_AGE_SECONDS",
    "MARKET_GATEWAY_CONNECTED",
    "MARKET_GATEWAY_RECONNECTS",
    "EVENTBUS_PUBLISH_TOTAL",
    "EVENTBUS_CONSUME_TOTAL",
    "EVENTBUS_CONSUME_LATENCY",
    "DATA_BRONZE_WRITES",
    "DATA_QUALITY_CHECKS",
    "DATA_QUALITY_ALERTS",
    "RISK_DECISIONS_TOTAL",
    "RISK_DECISION_LATENCY",
    "ORDERS_TOTAL",
    "FILLS_TOTAL",
    "PORTFOLIO_VALUE",
    "UNREALIZED_PNL",
]

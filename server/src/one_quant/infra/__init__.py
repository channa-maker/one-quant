"""
ONE量化 - 基础设施层

提供配置、日志、消息信封、插件注册表、运维成熟度等基础组件。
"""

from one_quant.infra.capacity import CapacityManager
from one_quant.infra.change_management import (
    ChangeManager,
    ChangeStatus,
    ChangeType,
    DRMetrics,
    RiskLevel,
)
from one_quant.infra.config import (
    AISettings,
    DatabaseSettings,
    ExchangeSettings,
    RedisSettings,
    RiskSettings,
    Settings,
    get_settings,
)
from one_quant.infra.disaster_recovery import DisasterRecovery, DRScenario
from one_quant.infra.event_bus import EventBus, InMemoryEventBus, RedisEventBus

# ── 健康检查 ──────────────────────────────────────────────────
from one_quant.infra.healthcheck import (
    ComponentHealth,
    HealthChecker,
    HealthStatus,
    SystemHealth,
)
from one_quant.infra.incident import IncidentManager, IncidentStatus
from one_quant.infra.logging import get_logger, log_mask, setup_logging
from one_quant.infra.message_envelope import MessageEnvelope, create_envelope

# ── 多渠道通知 ──────────────────────────────────────────────────
from one_quant.infra.notification_channels import (
    FeishuChannel,
    NotificationRouter,
    TelegramChannel,
    WeComChannel,
    build_default_router,
)
from one_quant.infra.notifier import MultiChannelNotifier
from one_quant.infra.registry import (
    AGENT_REGISTRY,
    ALGO_REGISTRY,
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
from one_quant.infra.runbook import RunbookManager, RunbookStep, Severity
from one_quant.infra.self_heal import HealResult, SelfHealStrategy

# ── 密钥管理 ──────────────────────────────────────────────────
from one_quant.infra.vault import (
    EnvProvider,
    OnePasswordProvider,
    SecretManager,
    SecretProvider,
    VaultProvider,
    create_secret_manager,
)

# ── 运维成熟度模块 ──────────────────────────────────────────────
from one_quant.infra.watchdog import ProcessInfo, ProcessStatus, Watchdog

__all__ = [
    # 配置
    "AISettings",
    "DatabaseSettings",
    "ExchangeSettings",
    "RedisSettings",
    "RiskSettings",
    "Settings",
    "get_settings",
    # 事件总线
    "EventBus",
    "InMemoryEventBus",
    "RedisEventBus",
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
    # 运维成熟度 - 看门狗
    "Watchdog",
    "ProcessInfo",
    "ProcessStatus",
    # 运维成熟度 - 自愈策略
    "SelfHealStrategy",
    "HealResult",
    # 运维成熟度 - 灾备
    "DisasterRecovery",
    "DRScenario",
    # 运维成熟度 - Runbook
    "RunbookManager",
    "RunbookStep",
    "Severity",
    # 运维成熟度 - 变更管理
    "ChangeManager",
    "ChangeType",
    "RiskLevel",
    "ChangeStatus",
    "DRMetrics",
    # 运维成熟度 - 事故管理
    "IncidentManager",
    "IncidentStatus",
    # 运维成熟度 - 容量管理
    "CapacityManager",
    # 密钥管理
    "SecretProvider",
    "VaultProvider",
    "OnePasswordProvider",
    "EnvProvider",
    "SecretManager",
    "create_secret_manager",
    # 健康检查
    "HealthStatus",
    "ComponentHealth",
    "SystemHealth",
    "HealthChecker",
    # 多渠道通知
    "FeishuChannel",
    "WeComChannel",
    "TelegramChannel",
    "NotificationRouter",
    "MultiChannelNotifier",
    "build_default_router",
]

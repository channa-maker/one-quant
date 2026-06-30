"""
ONE量化 - 风控包

导出风控决策类型、规则协议、四层规则和风控引擎。

四层风控：
  - L1: 静态限额（白名单、名义金额、可交易性、价格合理性）
  - L2: 实时敞口（持仓限额、下单频率、杠杆上限）
  - L3: 后台回撤（最大回撤、日内止损、保证金率）
  - L4: 熔断器（三态状态机）
"""

from one_quant.risk.audit import RiskAuditLog
from one_quant.risk.contracts import RiskCheckResult, RiskDecision, RiskRule
from one_quant.risk.engine import RiskEngine
from one_quant.risk.rules import (
    CircuitBreakerState,
    L1StaticLimitRule,
    L2RealtimeExposureRule,
    L3DrawdownRule,
    L4CircuitBreaker,
)

__all__ = [
    # 合约
    "RiskDecision",
    "RiskCheckResult",
    "RiskRule",
    # 引擎
    "RiskEngine",
    # 规则
    "L1StaticLimitRule",
    "L2RealtimeExposureRule",
    "L3DrawdownRule",
    "L4CircuitBreaker",
    "CircuitBreakerState",
    # 审计
    "RiskAuditLog",
]

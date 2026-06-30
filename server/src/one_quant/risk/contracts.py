"""
ONE量化 - 风控合约（决策类型与规则协议）

风控规则实现 RiskRule 协议，返回四态决策：
  - APPROVE: 批准下单
  - REJECT:  拒绝下单
  - REDUCE:  要求减仓后批准
  - FLATTEN: 强制全部平仓

规范：
  - 风控规则应尽量无状态，依赖入参而非内部缓存
  - reason 字段使用中文，便于人工审查
  - 风控优先级由外部编排器决定，规则本身不关心执行顺序
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel

from one_quant.core.types import Order, PositionState


class RiskDecision(StrEnum):
    """风控决策枚举"""

    APPROVE = "APPROVE"  # 批准
    REJECT = "REJECT"  # 拒绝
    REDUCE = "REDUCE"  # 减仓后批准
    FLATTEN = "FLATTEN"  # 强制平仓


class RiskCheckResult(BaseModel, frozen=True):
    """风控检查结果

    Attributes:
        decision: 风控决策
        rule_name: 触发的规则名称
        reason: 中文原因说明
        timestamp_ns: 纳秒时间戳
    """

    decision: RiskDecision
    rule_name: str
    reason: str
    timestamp_ns: int


class RiskRule(Protocol):
    """风控规则协议。

    实现此协议的类必须提供 ``check`` 方法，接收待下单订单和当前持仓列表，
    返回 ``RiskCheckResult`` 决策结果。

    Attributes:
        name: 规则名称（唯一标识，用于日志和决策溯源）

    Example::

        class MaxPositionRule:
            name = "max_position"
            max_qty = Decimal("10")

            def check(self, order: Order, positions: list[PositionState]) -> RiskCheckResult:
                total = sum(abs(p.quantity) for p in positions)
                if total + order.quantity > self.max_qty:
                    return RiskCheckResult(
                        decision=RiskDecision.REJECT,
                        rule_name=self.name,
                        reason=f"持仓总量 {total} + 委托 {order.quantity} 超过上限 {self.max_qty}",
                        timestamp_ns=time.time_ns(),
                    )
                return RiskCheckResult(
                    decision=RiskDecision.APPROVE,
                    rule_name=self.name,
                    reason="持仓检查通过",
                    timestamp_ns=time.time_ns(),
                )
    """

    name: str

    def check(self, order: Order, positions: list[PositionState]) -> RiskCheckResult:
        """执行风控检查。

        Args:
            order: 待下单订单
            positions: 当前所有持仓快照

        Returns:
            风控检查结果（四态决策）
        """
        ...

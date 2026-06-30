"""
ONE量化 - L1 静态限额规则

检查项：
  - 白名单：标的是否在可交易白名单内
  - 单笔最小/最大名义金额
  - 可交易性：标的是否活跃、是否停牌
  - 价格合理性：价格是否为正数、是否在合理范围

所有阈值硬编码，不读 .env / DB。
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal

from one_quant.core.types import Order, PositionState
from one_quant.risk.contracts import RiskCheckResult, RiskDecision

logger = logging.getLogger(__name__)

# ──────────────────── 硬编码常量 ────────────────────

# 单笔最大名义 10 万 USDT
MAX_ORDER_NOTIONAL = Decimal("100000")

# 单笔最小名义 10 USDT
MIN_ORDER_NOTIONAL = Decimal("10")

# 价格偏离最新价 10% 以内
MAX_PRICE_DEVIATION = Decimal("0.10")

# 可交易白名单（硬编码）
TRADABLE_SYMBOLS: frozenset[str] = frozenset(
    {
        "BTC/USDT",
        "ETH/USDT",
        "SOL/USDT",
        "BNB/USDT",
        "XRP/USDT",
        "DOGE/USDT",
        "ADA/USDT",
        "AVAX/USDT",
        "DOT/USDT",
        "MATIC/USDT",
        "LINK/USDT",
        "UNI/USDT",
        "ATOM/USDT",
        "LTC/USDT",
        "FIL/USDT",
        "AAPL",
        "MSFT",
        "GOOGL",
        "AMZN",
        "TSLA",
        "NVDA",
        "META",
    }
)

# 停牌/不可交易标的（硬编码）
SUSPENDED_SYMBOLS: frozenset[str] = frozenset(
    {
        "LUNA/USDT",
        "FTT/USDT",
        "UST/USDT",
    }
)

# 价格上限（防止错误报价）
MAX_ABSOLUTE_PRICE = Decimal("10000000")  # 单价上限 1000 万


class L1StaticLimitRule:
    """L1 静态限额检查。

    检查项：
    - 白名单：标的是否在可交易白名单内
    - 单笔最小/最大名义金额
    - 可交易性：标的是否活跃、是否停牌
    - 价格合理性：价格是否为正数、是否在合理范围

    硬编码常量（不读 .env/DB）：
    - MAX_ORDER_NOTIONAL = 100000  # 单笔最大名义 10 万 USDT
    - MIN_ORDER_NOTIONAL = 10      # 单笔最小名义 10 USDT
    - MAX_PRICE_DEVIATION = 0.10   # 价格偏离最新价 10% 以内
    """

    name: str = "L1_静态限额"

    def check(
        self,
        order: Order,
        positions: list[PositionState],
        latest_price: Decimal | None = None,
    ) -> RiskCheckResult:
        """L1 静态限额检查。

        Args:
            order: 待检查订单。
            positions: 当前持仓列表（L1 不使用，保持接口一致）。
            latest_price: 标的最新价格，用于价格偏离检查。可选。

        Returns:
            风控检查结果。
        """
        ts = time.time_ns()

        # 1. 白名单检查
        if order.symbol in SUSPENDED_SYMBOLS:
            return RiskCheckResult(
                decision=RiskDecision.REJECT,
                rule_name=self.name,
                reason=f"标的 {order.symbol} 已停牌/不可交易",
                timestamp_ns=ts,
            )

        if order.symbol not in TRADABLE_SYMBOLS:
            return RiskCheckResult(
                decision=RiskDecision.REJECT,
                rule_name=self.name,
                reason=f"标的 {order.symbol} 不在可交易白名单内",
                timestamp_ns=ts,
            )

        # 2. 数量必须大于 0
        if order.quantity <= 0:
            return RiskCheckResult(
                decision=RiskDecision.REJECT,
                rule_name=self.name,
                reason=f"委托数量 {order.quantity} 必须大于 0",
                timestamp_ns=ts,
            )

        # 3. 价格合理性检查
        if order.price is not None:
            if order.price <= 0:
                return RiskCheckResult(
                    decision=RiskDecision.REJECT,
                    rule_name=self.name,
                    reason=f"委托价格 {order.price} 必须为正数",
                    timestamp_ns=ts,
                )
            if order.price > MAX_ABSOLUTE_PRICE:
                return RiskCheckResult(
                    decision=RiskDecision.REJECT,
                    rule_name=self.name,
                    reason=f"委托价格 {order.price} 超过绝对上限 {MAX_ABSOLUTE_PRICE}",
                    timestamp_ns=ts,
                )

        if order.stop_price is not None:
            if order.stop_price <= 0:
                return RiskCheckResult(
                    decision=RiskDecision.REJECT,
                    rule_name=self.name,
                    reason=f"止损价格 {order.stop_price} 必须为正数",
                    timestamp_ns=ts,
                )

        # 4. 价格偏离检查（限价单）
        if latest_price is not None and latest_price > 0 and order.price is not None:
            deviation = abs(order.price - latest_price) / latest_price
            if deviation > MAX_PRICE_DEVIATION:
                return RiskCheckResult(
                    decision=RiskDecision.REJECT,
                    rule_name=self.name,
                    reason=(
                        f"委托价格 {order.price} 偏离最新价 {latest_price} "
                        f"{deviation:.2%}，超过阈值 {MAX_PRICE_DEVIATION:.0%}"
                    ),
                    timestamp_ns=ts,
                )

        # 5. 名义金额检查
        notional = self._calc_notional(order)
        if notional > 0 and notional < MIN_ORDER_NOTIONAL:
            return RiskCheckResult(
                decision=RiskDecision.REJECT,
                rule_name=self.name,
                reason=f"名义价值 {notional} 低于最小限额 {MIN_ORDER_NOTIONAL}",
                timestamp_ns=ts,
            )

        if notional > MAX_ORDER_NOTIONAL:
            return RiskCheckResult(
                decision=RiskDecision.REJECT,
                rule_name=self.name,
                reason=f"名义价值 {notional} 超过最大限额 {MAX_ORDER_NOTIONAL}",
                timestamp_ns=ts,
            )

        return RiskCheckResult(
            decision=RiskDecision.APPROVE,
            rule_name=self.name,
            reason="L1 静态限额检查通过",
            timestamp_ns=ts,
        )

    @staticmethod
    def _calc_notional(order: Order) -> Decimal:
        """计算订单名义价值。"""
        if order.price is not None:
            return order.quantity * order.price
        if order.stop_price is not None:
            return order.quantity * order.stop_price
        # 市价单无法计算名义值
        return Decimal("0")

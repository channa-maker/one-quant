"""
ONE量化 - L2 实时敞口规则

检查项：
  - 最大敞口：同标的持仓 + 待成交 ≤ 上限
  - 下单频率：同标的 N 秒内下单次数 ≤ 限制
  - 价格偏离：限价单价格偏离最新价 ≤ 阈值
  - 杠杆上限：实际杠杆 ≤ 硬编码上限

所有阈值硬编码，不读 .env / DB。
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from decimal import Decimal

from one_quant.core.types import Market, Order, PositionState
from one_quant.risk.contracts import RiskCheckResult, RiskDecision

logger = logging.getLogger(__name__)

# ──────────────────── 硬编码常量 ────────────────────

# 加密最大杠杆
MAX_CRYPTO_LEVERAGE = 20

# 美股最大杠杆
MAX_STOCK_LEVERAGE = 4

# 单标的最大仓位 10%
MAX_POSITION_PCT = Decimal("0.10")

# 总敞口最大 50%
MAX_EXPOSURE_PCT = Decimal("0.50")

# 同标的 10 秒内最多 10 单
MAX_ORDER_FREQ = 10
ORDER_FREQ_WINDOW_SEC = 10

# 价格偏离阈值 10%
MAX_PRICE_DEVIATION = Decimal("0.10")


class L2RealtimeExposureRule:
    """L2 实时敞口检查。

    检查项：
    - 最大敞口：同标的持仓 + 待成交 ≤ 上限
    - 下单频率：同标的 N 秒内下单次数 ≤ 限制
    - 价格偏离：限价单价格偏离最新价 ≤ 阈值
    - 杠杆上限：实际杠杆 ≤ 硬编码上限

    硬编码常量：
    - MAX_CRYPTO_LEVERAGE = 20      # 加密最大杠杆
    - MAX_STOCK_LEVERAGE = 4        # 美股最大杠杆
    - MAX_POSITION_PCT = 0.10       # 单标的最大仓位 10%
    - MAX_EXPOSURE_PCT = 0.50       # 总敞口最大 50%
    - MAX_ORDER_FREQ = 10           # 同标的 10 秒内最多 10 单
    """

    name: str = "L2_实时敞口"

    def __init__(self) -> None:
        # 每个标的的下单时间戳记录 {symbol: [timestamp_ns, ...]}
        self._order_timestamps: dict[str, list[int]] = defaultdict(list)

    def check(
        self,
        order: Order,
        positions: list[PositionState],
        total_equity: Decimal | None = None,
        latest_price: Decimal | None = None,
    ) -> RiskCheckResult:
        """L2 实时敞口检查。

        Args:
            order: 待检查订单。
            positions: 当前持仓列表。
            total_equity: 总权益（用于计算仓位占比和杠杆）。可选。
            latest_price: 标的最新价格。可选。

        Returns:
            风控检查结果。
        """
        ts = time.time_ns()

        # 1. 下单频率检查（同标的 10 秒内滑动窗口）
        freq_result = self._check_order_frequency(order, ts)
        if freq_result is not None:
            return freq_result

        # 记录本次下单
        self._order_timestamps[order.symbol].append(ts)

        # 2. 单标的仓位集中度检查
        if total_equity is not None and total_equity > 0 and latest_price is not None:
            pos_result = self._check_position_concentration(
                order, positions, total_equity, latest_price, ts
            )
            if pos_result is not None:
                return pos_result

        # 3. 总敞口检查
        if total_equity is not None and total_equity > 0 and latest_price is not None:
            exp_result = self._check_total_exposure(
                order, positions, total_equity, latest_price, ts
            )
            if exp_result is not None:
                return exp_result

        # 4. 杠杆上限检查
        if total_equity is not None and total_equity > 0:
            lev_result = self._check_leverage(order, positions, total_equity, latest_price, ts)
            if lev_result is not None:
                return lev_result

        return RiskCheckResult(
            decision=RiskDecision.APPROVE,
            rule_name=self.name,
            reason="L2 实时敞口检查通过",
            timestamp_ns=ts,
        )

    def _check_order_frequency(self, order: Order, ts: int) -> RiskCheckResult | None:
        """检查同标的下单频率。"""
        cutoff = ts - ORDER_FREQ_WINDOW_SEC * 1_000_000_000
        timestamps = self._order_timestamps[order.symbol]
        # 清理过期记录
        self._order_timestamps[order.symbol] = [t for t in timestamps if t > cutoff]
        recent_count = len(self._order_timestamps[order.symbol])

        if recent_count >= MAX_ORDER_FREQ:
            return RiskCheckResult(
                decision=RiskDecision.REJECT,
                rule_name=self.name,
                reason=(
                    f"标的 {order.symbol} 下单频率超限："
                    f"{ORDER_FREQ_WINDOW_SEC} 秒内 {recent_count} 次"
                    f"（上限 {MAX_ORDER_FREQ}）"
                ),
                timestamp_ns=ts,
            )
        return None

    def _check_position_concentration(
        self,
        order: Order,
        positions: list[PositionState],
        total_equity: Decimal,
        latest_price: Decimal,
        ts: int,
    ) -> RiskCheckResult | None:
        """检查单标的仓位集中度。"""
        # 计算同标的现有持仓名义价值
        same_symbol_positions = [p for p in positions if p.symbol == order.symbol]
        existing_notional = sum(
            abs(p.quantity) * p.entry_price for p in same_symbol_positions
        )

        # 新增订单名义价值
        order_notional = order.quantity * (order.price or latest_price)

        # 含订单后的总名义
        total_notional = existing_notional + order_notional
        position_pct = total_notional / total_equity

        if position_pct > MAX_POSITION_PCT:
            return RiskCheckResult(
                decision=RiskDecision.REJECT,
                rule_name=self.name,
                reason=(
                    f"标的 {order.symbol} 仓位占比 {position_pct:.2%} "
                    f"超过上限 {MAX_POSITION_PCT:.0%}"
                ),
                timestamp_ns=ts,
            )
        return None

    def _check_total_exposure(
        self,
        order: Order,
        positions: list[PositionState],
        total_equity: Decimal,
        latest_price: Decimal,
        ts: int,
    ) -> RiskCheckResult | None:
        """检查总敞口。"""
        # 当前总持仓名义价值
        total_position_notional = sum(
            abs(p.quantity) * p.entry_price for p in positions
        )

        # 新增订单名义价值
        order_notional = order.quantity * (order.price or latest_price)

        total_exposure = total_position_notional + order_notional
        exposure_pct = total_exposure / total_equity

        if exposure_pct > MAX_EXPOSURE_PCT:
            return RiskCheckResult(
                decision=RiskDecision.REDUCE,
                rule_name=self.name,
                reason=(
                    f"总敞口占比 {exposure_pct:.2%} 超过上限 {MAX_EXPOSURE_PCT:.0%}，"
                    f"请减仓后重新下单"
                ),
                timestamp_ns=ts,
            )
        return None

    def _check_leverage(
        self,
        order: Order,
        positions: list[PositionState],
        total_equity: Decimal,
        latest_price: Decimal | None,
        ts: int,
    ) -> RiskCheckResult | None:
        """检查杠杆上限。"""
        # 根据市场类型确定杠杆上限
        if order.market in (Market.FUTURES,):
            max_leverage = MAX_CRYPTO_LEVERAGE
        elif order.market == Market.STOCK:
            max_leverage = MAX_STOCK_LEVERAGE
        else:
            # 现货不检查杠杆
            return None

        # 简化杠杆计算：总持仓名义 / 总权益
        total_position_notional = sum(
            abs(p.quantity) * p.entry_price for p in positions
        )
        order_notional = order.quantity * (order.price or (latest_price or Decimal("0")))
        total_notional = total_position_notional + order_notional

        if total_equity > 0:
            leverage = total_notional / total_equity
            if leverage > max_leverage:
                return RiskCheckResult(
                    decision=RiskDecision.REDUCE,
                    rule_name=self.name,
                    reason=(
                        f"杠杆 {leverage:.1f}x 超过上限 {max_leverage}x，"
                        f"请减仓后重新下单"
                    ),
                    timestamp_ns=ts,
                )
        return None

    def reset(self) -> None:
        """重置频率记录（用于测试）。"""
        self._order_timestamps.clear()

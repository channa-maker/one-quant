"""
EMS — 执行管理器
"""

from __future__ import annotations

import logging
from decimal import Decimal

from one_quant.core.types import Fill, Order
from one_quant.exchange.contracts import ExchangeAdapter
from one_quant.execution.ems.base import ExecutionAlgo, _time_ns

logger = logging.getLogger(__name__)


class _InstantAlgo(ExecutionAlgo):
    """即时执行算法（小单直接下单，不拆分）。"""

    @property
    def name(self) -> str:
        return "INSTANT"

    async def execute(self, order: Order, adapter: ExchangeAdapter) -> list[Fill]:
        """直接提交订单，不拆分。"""
        try:
            exchange_order_id = await adapter.submit_order(order)  # noqa: F841

            fill = Fill(
                order_id=order.client_order_id,
                symbol=order.symbol,
                side=order.side,
                price=order.price or order.stop_price or Decimal("0"),
                quantity=order.quantity,
                fee=Decimal("0"),
                fee_currency="USDT",
                exchange=order.exchange,
                timestamp_ns=_time_ns(),
            )

            logger.info(
                "INSTANT 执行: %s %s %s @ %s",
                order.side,
                order.quantity,
                order.symbol,
                order.price or "市价",
            )

            return [fill]

        except Exception as e:
            logger.error("INSTANT 执行失败: %s", e)
            return []


class ExecutionManager:
    """执行管理器（EMS 核心）。

    职责：
      1. 根据订单特征选择最优执行算法
      2. 调度算法执行
      3. 汇总成交结果，回调 OMS
      4. 执行指标统计
    """

    TWAP_NOTIONAL_THRESHOLD = Decimal("10000")
    VWAP_NOTIONAL_THRESHOLD = Decimal("50000")
    POV_NOTIONAL_THRESHOLD = Decimal("100000")

    def __init__(self, adapter: ExchangeAdapter) -> None:
        self._adapter = adapter
        self._execution_count = 0
        self._total_fills = 0

    async def execute(
        self,
        order: Order,
        algo: ExecutionAlgo | None = None,
    ) -> list[Fill]:
        """执行订单。"""
        self._execution_count += 1

        if algo is None:
            algo = self._select_algo(order)

        logger.info(
            "EMS 执行订单: %s %s %s，算法=%s",
            order.client_order_id[:8],
            order.side,
            order.symbol,
            algo.name,
        )

        fills = await algo.execute(order, self._adapter)
        self._total_fills += len(fills)

        return fills

    def _select_algo(self, order: Order) -> ExecutionAlgo:
        """根据订单特征选择最优算法。"""
        from one_quant.execution.ems.pov import POVAlgo
        from one_quant.execution.ems.twap import TWAPAlgo
        from one_quant.execution.ems.vwap import VWAPAlgo

        notional = self._estimate_notional(order)

        if notional >= self.POV_NOTIONAL_THRESHOLD:
            return POVAlgo(participation_rate=0.1)
        elif notional >= self.VWAP_NOTIONAL_THRESHOLD:
            return VWAPAlgo(lookback_intervals=20, participation_rate=0.1)
        elif notional >= self.TWAP_NOTIONAL_THRESHOLD:
            return TWAPAlgo(duration_sec=300, slice_count=10)
        else:
            return _InstantAlgo()

    @staticmethod
    def _estimate_notional(order: Order) -> Decimal:
        """估算订单名义价值。"""
        price = order.price or order.stop_price or Decimal("0")
        return order.quantity * price

    @property
    def stats(self) -> dict[str, int]:
        """执行统计。"""
        return {
            "executions": self._execution_count,
            "total_fills": self._total_fills,
        }

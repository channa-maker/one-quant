"""
EMS — VWAP 算法
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal

from one_quant.core.types import Fill, Order
from one_quant.exchange.contracts import ExchangeAdapter
from one_quant.execution.ems.base import ExecutionAlgo, _round_to_lot, _time_ns

logger = logging.getLogger(__name__)


class VWAPAlgo(ExecutionAlgo):
    """VWAP 算法：成交量加权平均价格。

    按历史成交量分布拆单，跟随市场节奏。
    """

    def __init__(
        self,
        lookback_intervals: int = 20,
        participation_rate: float = 0.1,
    ) -> None:
        if lookback_intervals <= 0:
            raise ValueError(f"回看窗口数必须大于 0，当前: {lookback_intervals}")
        if not 0 < participation_rate <= 1:
            raise ValueError(f"参与率必须在 (0, 1] 之间，当前: {participation_rate}")

        self._lookback = lookback_intervals
        self._participation_rate = participation_rate

    @property
    def name(self) -> str:
        return "VWAP"

    async def execute(self, order: Order, adapter: ExchangeAdapter) -> list[Fill]:
        """执行 VWAP 算法。"""
        fills: list[Fill] = []
        total_qty = order.quantity

        volume_profile = await self._get_volume_profile(adapter, order.symbol)

        if not volume_profile:
            logger.warning("VWAP: 无法获取成交量分布，回退到 TWAP")
            from one_quant.execution.ems.twap import TWAPAlgo

            fallback = TWAPAlgo(duration_sec=self._lookback * 60, slice_count=self._lookback)
            return await fallback.execute(order, adapter)

        total_volume = sum(volume_profile)
        if total_volume <= 0:
            logger.warning("VWAP: 历史成交量为 0，回退到 TWAP")
            from one_quant.execution.ems.twap import TWAPAlgo

            fallback = TWAPAlgo(duration_sec=self._lookback * 60, slice_count=self._lookback)
            return await fallback.execute(order, adapter)

        remaining = total_qty

        logger.info(
            "VWAP 开始: %s %s %s，参与率 %.1f%%，%d 个时间窗口",
            order.side,
            order.quantity,
            order.symbol,
            self._participation_rate * 100,
            len(volume_profile),
        )

        for i, vol in enumerate(volume_profile):
            if remaining <= 0:
                break

            ratio = vol / total_volume
            slice_qty = _round_to_lot(total_qty * ratio, Decimal("0.001"))

            if i == len(volume_profile) - 1:
                slice_qty = remaining

            slice_qty = min(slice_qty, remaining)
            if slice_qty <= 0:
                continue

            try:
                child_order = Order(
                    client_order_id=str(uuid.uuid4()),
                    symbol=order.symbol,
                    market=order.market,
                    side=order.side,
                    order_type="market",
                    quantity=slice_qty,
                    price=None,
                    stop_price=None,
                    status="pending",
                    exchange=order.exchange,
                    timestamp_ns=_time_ns(),
                )

                exchange_order_id = await adapter.submit_order(child_order)  # noqa: F841

                fill = Fill(
                    order_id=order.client_order_id,
                    symbol=order.symbol,
                    side=order.side,
                    price=Decimal("0"),
                    quantity=slice_qty,
                    fee=Decimal("0"),
                    fee_currency="USDT",
                    exchange=order.exchange,
                    timestamp_ns=_time_ns(),
                )
                fills.append(fill)
                remaining -= slice_qty

                logger.debug(
                    "VWAP 窗口 %d: 成交 %s（占比 %.1f%%），剩余 %s",
                    i,
                    slice_qty,
                    ratio * 100,
                    remaining,
                )

            except Exception as e:
                logger.warning("VWAP 窗口 %d 下单失败: %s", i, e)

        total_filled = sum(f.quantity for f in fills)
        logger.info(
            "VWAP 完成: 总成交 %s/%s，成交笔数 %d",
            total_filled,
            total_qty,
            len(fills),
        )

        return fills

    async def _get_volume_profile(self, adapter: ExchangeAdapter, symbol: str) -> list[Decimal]:
        """获取历史成交量分布。"""
        volume_profile: list[Decimal] = []

        get_klines = getattr(adapter, "get_klines", None)
        if callable(get_klines):
            try:
                klines = await get_klines(
                    symbol=symbol,
                    interval="1m",
                    limit=self._lookback,
                )
                for kline in klines:
                    vol = getattr(kline, "volume", None)
                    if vol is not None:
                        volume_profile.append(Decimal(str(vol)))
                if volume_profile:
                    logger.debug(
                        "VWAP: 通过适配器获取 %d 个窗口的成交量 (symbol=%s)",
                        len(volume_profile),
                        symbol,
                    )
                    return volume_profile
            except Exception as exc:
                logger.warning("VWAP: 通过适配器获取 K 线失败: %s", exc)

        try:
            ticker = await adapter.get_ticker(symbol)
            vol_per_interval = ticker.volume_24h / Decimal(str(self._lookback))
            volume_profile = [vol_per_interval] * self._lookback
            logger.debug(
                "VWAP: 使用 ticker 24h 成交量均匀估算 (symbol=%s, vol_per_window=%s)",
                symbol,
                vol_per_interval,
            )
            return volume_profile
        except Exception as exc:
            logger.warning("VWAP: 获取 ticker 成交量失败: %s", exc)

        logger.debug("VWAP: 使用默认均匀成交量分布 (symbol=%s)", symbol)
        return [Decimal("1000")] * self._lookback

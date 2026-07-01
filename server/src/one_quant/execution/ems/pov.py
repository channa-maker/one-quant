"""
EMS — POV 算法
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from decimal import Decimal

from one_quant.core.types import Fill, Order
from one_quant.exchange.contracts import ExchangeAdapter
from one_quant.execution.ems.base import ExecutionAlgo, _round_to_lot, _time_ns

logger = logging.getLogger(__name__)


class POVAlgo(ExecutionAlgo):
    """POV 算法：参与率算法（Percentage of Volume）。

    按市场成交量的固定比例下单，实时跟踪市场节奏。
    """

    def __init__(
        self,
        participation_rate: float = 0.1,
        volume_threshold: Decimal = Decimal("100"),
        max_duration_sec: int = 600,
    ) -> None:
        if not 0 < participation_rate <= 1:
            raise ValueError(f"参与率必须在 (0, 1] 之间，当前: {participation_rate}")
        if volume_threshold <= 0:
            raise ValueError(f"成交量阈值必须大于 0，当前: {volume_threshold}")

        self._participation_rate = participation_rate
        self._volume_threshold = volume_threshold
        self._max_duration = max_duration_sec

    @property
    def name(self) -> str:
        return "POV"

    async def execute(self, order: Order, adapter: ExchangeAdapter) -> list[Fill]:
        """执行 POV 算法。"""
        fills: list[Fill] = []
        remaining = order.quantity
        start_time = time.time()

        logger.info(
            "POV 开始: %s %s %s，参与率 %.1f%%，阈值 %s",
            order.side,
            order.quantity,
            order.symbol,
            self._participation_rate * 100,
            self._volume_threshold,
        )

        accumulated_volume = Decimal("0")

        while remaining > 0:
            elapsed = time.time() - start_time
            if elapsed >= self._max_duration:
                logger.warning(
                    "POV 超时: 已执行 %.1fs，剩余 %s，强制结束",
                    elapsed,
                    remaining,
                )
                break

            try:
                market_volume = await self._get_market_volume(adapter, order.symbol)
                accumulated_volume += market_volume

                if accumulated_volume >= self._volume_threshold:
                    slice_qty = _round_to_lot(
                        accumulated_volume * Decimal(str(self._participation_rate)),
                        Decimal("0.001"),
                    )
                    slice_qty = min(slice_qty, remaining)

                    if slice_qty > 0:
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
                            "POV 下单: %s，市场累积量 %s，剩余 %s",
                            slice_qty,
                            accumulated_volume,
                            remaining,
                        )

                    accumulated_volume = Decimal("0")

                await asyncio.sleep(1.0)

            except Exception as e:
                logger.warning("POV 执行异常: %s", e)
                await asyncio.sleep(2.0)

        total_filled = sum(f.quantity for f in fills)
        logger.info(
            "POV 完成: 总成交 %s/%s，成交笔数 %d，耗时 %.1fs",
            total_filled,
            order.quantity,
            len(fills),
            time.time() - start_time,
        )

        return fills

    async def _get_market_volume(self, adapter: ExchangeAdapter, symbol: str) -> Decimal:
        """获取当前市场成交量（增量）。"""
        ws_client = getattr(adapter, "ws", None) or getattr(adapter, "_ws", None)
        if ws_client is not None:
            get_volume = getattr(ws_client, "get_recent_volume", None) or getattr(
                ws_client, "get_last_trade_volume", None
            )
            if callable(get_volume):
                try:
                    volume = await get_volume(symbol)
                    if volume is not None and volume > 0:
                        return Decimal(str(volume))
                except Exception as exc:
                    logger.debug("POV: WebSocket 获取成交量失败: %s", exc)

        get_trades = getattr(adapter, "get_trades", None)
        if callable(get_trades):
            try:
                trades = await get_trades(symbol, limit=100)
                total_vol = sum(
                    (Decimal(str(getattr(t, "quantity", 0))) for t in trades), Decimal("0")
                )
                if total_vol > 0:
                    return total_vol
            except Exception as exc:
                logger.debug("POV: 通过 get_trades 获取成交量失败: %s", exc)

        try:
            ticker = await adapter.get_ticker(symbol)
            vol_per_second = ticker.volume_24h / Decimal("86400")
            return vol_per_second
        except Exception as exc:
            logger.debug("POV: 通过 get_ticker 获取成交量失败: %s", exc)

        return self._volume_threshold / Decimal("5")

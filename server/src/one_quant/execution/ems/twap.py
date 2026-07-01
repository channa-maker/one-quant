"""
EMS — TWAP 算法
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from decimal import Decimal

from one_quant.core.types import Fill, Order
from one_quant.exchange.contracts import ExchangeAdapter
from one_quant.execution.ems.base import ExecutionAlgo, _round_to_lot, _time_ns

logger = logging.getLogger(__name__)


class TWAPAlgo(ExecutionAlgo):
    """TWAP 算法：时间加权平均价格。

    将大单按时间均匀拆分，每间隔固定时间下一笔子单。
    """

    def __init__(
        self,
        duration_sec: int = 300,
        slice_count: int = 10,
        price_limit: Decimal | None = None,
        max_retries: int = 3,
    ) -> None:
        if duration_sec <= 0:
            raise ValueError(f"执行时长必须大于 0，当前: {duration_sec}")
        if slice_count <= 0:
            raise ValueError(f"拆分数量必须大于 0，当前: {slice_count}")

        self._duration = duration_sec
        self._slice_count = slice_count
        self._price_limit = price_limit
        self._max_retries = max_retries

    @property
    def name(self) -> str:
        return "TWAP"

    async def execute(self, order: Order, adapter: ExchangeAdapter) -> list[Fill]:
        """执行 TWAP 算法。"""
        fills: list[Fill] = []
        total_qty = order.quantity

        slice_qty = _round_to_lot(total_qty / self._slice_count, Decimal("0.001"))
        if slice_qty <= 0:
            logger.error("TWAP: 子单数量为 0，总量=%s，拆分数=%s", total_qty, self._slice_count)
            return fills

        interval_sec = self._duration / self._slice_count
        remaining = total_qty

        logger.info(
            "TWAP 开始: %s %s %s，拆分 %d 笔，每笔 %s，间隔 %.1fs",
            order.side,
            order.quantity,
            order.symbol,
            self._slice_count,
            slice_qty,
            interval_sec,
        )

        for i in range(self._slice_count):
            if i == self._slice_count - 1:
                current_qty = remaining
            else:
                current_qty = min(slice_qty, remaining)

            if current_qty <= 0:
                break

            child_fills = await self._execute_slice(
                order=order,
                adapter=adapter,
                quantity=current_qty,
                slice_index=i,
            )

            fills.extend(child_fills)

            filled_qty = sum(f.quantity for f in child_fills)
            remaining -= filled_qty

            logger.info(
                "TWAP 子单 %d/%d: 成交 %s，剩余 %s",
                i + 1,
                self._slice_count,
                filled_qty,
                remaining,
            )

            if remaining <= 0:
                break

            if i < self._slice_count - 1:
                await asyncio.sleep(interval_sec)

        total_filled = sum(f.quantity for f in fills)
        logger.info(
            "TWAP 完成: 总成交 %s/%s，成交笔数 %d",
            total_filled,
            total_qty,
            len(fills),
        )

        return fills

    async def _execute_slice(
        self,
        order: Order,
        adapter: ExchangeAdapter,
        quantity: Decimal,
        slice_index: int,
    ) -> list[Fill]:
        """执行单笔子单，带重试逻辑。"""
        fills: list[Fill] = []

        for attempt in range(self._max_retries):
            try:
                child_order = Order(
                    client_order_id=str(uuid.uuid4()),
                    symbol=order.symbol,
                    market=order.market,
                    side=order.side,
                    order_type="limit" if self._price_limit else "market",
                    quantity=quantity,
                    price=self._price_limit,
                    stop_price=None,
                    status="pending",
                    exchange=order.exchange,
                    timestamp_ns=_time_ns(),
                )

                exchange_order_id = await adapter.submit_order(child_order)
                logger.debug(
                    "TWAP 子单 %d 提交成功: exchange_id=%s, qty=%s",
                    slice_index,
                    exchange_order_id,
                    quantity,
                )

                fill_price = self._price_limit or order.price or Decimal("0")
                fill = Fill(
                    order_id=order.client_order_id,
                    symbol=order.symbol,
                    side=order.side,
                    price=fill_price,
                    quantity=quantity,
                    fee=Decimal("0"),
                    fee_currency="USDT",
                    exchange=order.exchange,
                    timestamp_ns=_time_ns(),
                )
                fills.append(fill)
                return fills

            except Exception as e:
                logger.warning(
                    "TWAP 子单 %d 第 %d 次失败: %s",
                    slice_index,
                    attempt + 1,
                    e,
                )
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(1.0 * (attempt + 1))

        logger.error("TWAP 子单 %d 重试 %d 次均失败", slice_index, self._max_retries)
        return fills

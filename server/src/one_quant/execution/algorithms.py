"""EMS 算法拆单 — TWAP / VWAP / 冰山单"""

from __future__ import annotations

import asyncio
import time
import uuid
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any

from one_quant.core.types import Order
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class ExecutionAlgo(ABC):
    """执行算法基类"""

    name: str

    @abstractmethod
    async def execute(
        self,
        parent_order: Order,
        submit_fn: Any,  # async callable
        cancel_fn: Any,  # async callable
    ) -> list[Order]:
        """执行拆单算法

        Args:
            parent_order: 母单
            submit_fn: 下单函数
            cancel_fn: 撤单函数

        Returns:
            子单列表
        """
        ...


class TWAPAlgo(ExecutionAlgo):
    """TWAP (时间加权平均价格) 算法。

    将大单均匀拆分为 N 个子单，每隔固定时间间隔下单。
    适合降低时间维度的冲击。
    """

    name = "twap"

    def __init__(
        self,
        slices: int = 10,
        interval_sec: float = 60.0,
    ) -> None:
        self._slices = slices
        self._interval = interval_sec

    async def execute(
        self,
        parent_order: Order,
        submit_fn: Any,
        cancel_fn: Any,
    ) -> list[Order]:
        slice_qty = parent_order.quantity / self._slices
        child_orders: list[Order] = []

        logger.info(
            "TWAP 开始执行: %s %s %s, 分 %d 片, 间隔 %.1fs",
            parent_order.side,
            parent_order.quantity,
            parent_order.symbol,
            self._slices,
            self._interval,
        )

        for i in range(self._slices):
            child = Order(
                client_order_id=str(uuid.uuid4()),
                symbol=parent_order.symbol,
                market=parent_order.market,
                side=parent_order.side,
                order_type="limit",
                quantity=slice_qty,
                price=parent_order.price,
                stop_price=None,
                status="pending",
                exchange=parent_order.exchange,
                timestamp_ns=time.time_ns(),
            )

            try:
                await submit_fn(child)
                child = child.model_copy(update={"status": "submitted"})
            except Exception:
                logger.exception("TWAP 子单 %d/%d 提交失败", i + 1, self._slices)
                child = child.model_copy(update={"status": "rejected"})

            child_orders.append(child)

            if i < self._slices - 1:
                await asyncio.sleep(self._interval)

        logger.info("TWAP 执行完成: %d/%d 子单已提交", len(child_orders), self._slices)
        return child_orders


class VWAPAlgo(ExecutionAlgo):
    """VWAP (成交量加权平均价格) 算法。

    根据历史成交量分布拆单，在高成交量时段多下，低成交量时段少下。
    """

    name = "vwap"

    def __init__(
        self,
        slices: int = 10,
        interval_sec: float = 60.0,
        volume_profile: list[float] | None = None,
    ) -> None:
        self._slices = slices
        self._interval = interval_sec
        # 默认均匀分布
        self._volume_profile = volume_profile or [1.0 / slices] * slices

    async def execute(
        self,
        parent_order: Order,
        submit_fn: Any,
        cancel_fn: Any,
    ) -> list[Order]:
        # 归一化 volume profile
        total_weight = sum(self._volume_profile)
        weights = [w / total_weight for w in self._volume_profile[: self._slices]]

        child_orders: list[Order] = []

        logger.info(
            "VWAP 开始执行: %s %s %s, 分 %d 片",
            parent_order.side,
            parent_order.quantity,
            parent_order.symbol,
            self._slices,
        )

        for i, weight in enumerate(weights):
            slice_qty = parent_order.quantity * Decimal(str(weight))
            if slice_qty <= 0:
                continue

            child = Order(
                client_order_id=str(uuid.uuid4()),
                symbol=parent_order.symbol,
                market=parent_order.market,
                side=parent_order.side,
                order_type="limit",
                quantity=slice_qty,
                price=parent_order.price,
                stop_price=None,
                status="pending",
                exchange=parent_order.exchange,
                timestamp_ns=time.time_ns(),
            )

            try:
                await submit_fn(child)
                child = child.model_copy(update={"status": "submitted"})
            except Exception:
                logger.exception("VWAP 子单 %d 提交失败", i + 1)

            child_orders.append(child)
            if i < len(weights) - 1:
                await asyncio.sleep(self._interval)

        return child_orders


class IcebergAlgo(ExecutionAlgo):
    """冰山单算法。

    每次只暴露少量订单，成交后再挂下一批。
    隐藏真实委托量，减少市场冲击。
    """

    name = "iceberg"

    def __init__(
        self,
        visible_qty_pct: Decimal = Decimal("0.1"),  # 每次显示 10%
        max_retries: int = 3,
    ) -> None:
        self._visible_pct = visible_qty_pct
        self._max_retries = max_retries

    async def execute(
        self,
        parent_order: Order,
        submit_fn: Any,
        cancel_fn: Any,
    ) -> list[Order]:
        remaining = parent_order.quantity
        visible_size = parent_order.quantity * self._visible_pct
        child_orders: list[Order] = []
        batch = 0

        logger.info(
            "冰山单开始执行: %s %s %s, 每批 %s",
            parent_order.side,
            parent_order.quantity,
            parent_order.symbol,
            visible_size,
        )

        while remaining > 0:
            batch += 1
            qty = min(visible_size, remaining)

            child = Order(
                client_order_id=str(uuid.uuid4()),
                symbol=parent_order.symbol,
                market=parent_order.market,
                side=parent_order.side,
                order_type="limit",
                quantity=qty,
                price=parent_order.price,
                stop_price=None,
                status="pending",
                exchange=parent_order.exchange,
                timestamp_ns=time.time_ns(),
            )

            try:
                await submit_fn(child)
                child = child.model_copy(update={"status": "submitted"})
                remaining -= qty
            except Exception:
                logger.exception("冰山单第 %d 批提交失败", batch)
                child = child.model_copy(update={"status": "rejected"})

            child_orders.append(child)
            await asyncio.sleep(1)  # 短暂等待

        logger.info("冰山单执行完成: %d 批", batch)
        return child_orders

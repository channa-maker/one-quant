"""
EMS — 辅助函数与算法基类
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from decimal import ROUND_DOWN, Decimal

from one_quant.core.types import Fill, Order
from one_quant.exchange.contracts import ExchangeAdapter


def _round_to_lot(quantity: Decimal, lot_size: Decimal) -> Decimal:
    """将数量取整到最小下单单位。"""
    if lot_size <= 0:
        return quantity
    return (quantity / lot_size).to_integral_value(rounding=ROUND_DOWN) * lot_size


def _time_ns() -> int:
    """获取当前纳秒时间戳。"""
    return time.time_ns()


class ExecutionAlgo(ABC):
    """执行算法基类。

    所有拆单算法必须继承此类并实现 execute() 方法。
    """

    @abstractmethod
    async def execute(self, order: Order, adapter: ExchangeAdapter) -> list[Fill]:
        """执行订单，返回成交列表。"""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """算法名称。"""
        ...

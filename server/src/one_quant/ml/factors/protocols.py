"""
因子库 — 协议、结果类型与辅助函数
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Factor(Protocol):
    """因子协议：所有因子实现此接口。"""

    name: str

    def update(self, *args: Any, **kwargs: Any) -> FactorResult: ...


@dataclass(frozen=True)
class FactorResult:
    """因子计算结果。

    Attributes:
        name: 因子名称。
        value: 因子值（None 表示数据不足或 NaN）。
        timestamp_ns: 计算时刻的时间戳。
        metadata: 附加元数据（窗口大小、样本数等）。
    """

    name: str
    value: float | None
    timestamp_ns: int
    metadata: dict[str, Any]


def _now_ns() -> int:
    """当前时间戳（纳秒）。"""
    return time.time_ns()


def _safe_float(val: Decimal | float | None) -> float | None:
    """将 Decimal/float 转为 float，NaN 或异常返回 None。"""
    if val is None:
        return None
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (InvalidOperation, OverflowError, ValueError):
        return None


def _safe_decimal(val: float | Decimal | None) -> Decimal | None:
    """将 float/Decimal 转为 Decimal，NaN 或异常返回 None。"""
    if val is None:
        return None
    try:
        d = Decimal(str(val)) if not isinstance(val, Decimal) else val
        if d.is_nan() or d.is_infinite():
            return None
        return d
    except (InvalidOperation, ValueError):
        return None

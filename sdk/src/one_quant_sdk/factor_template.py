"""因子模板 — 快速定义技术指标因子

用法:
    MyFactor = create_factor(
        name="my_rsi",
        category="momentum",
        compute=lambda prices, period=14: calculate_rsi(prices, period)
    )
"""

from __future__ import annotations
from typing import Callable, Any


def create_factor(
    name: str,
    category: str,
    compute: Callable[..., Any],
    description: str = "",
) -> type:
    """快速创建因子类

    Args:
        name: 因子名称（如 momentum_rsi_14）
        category: 因子类别（momentum/volatility/flow/sentiment）
        compute: 计算函数
        description: 描述

    Returns:
        因子类
    """
    attrs = {
        "name": name,
        "category": category,
        "description": description or f"{category}_{name} 因子",
        "compute": staticmethod(compute),
    }

    factor_class = type(f"Factor_{name}", (object,), attrs)
    return factor_class

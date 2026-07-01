"""
因子库 — 资金流因子
"""

from __future__ import annotations

import logging
import math
from decimal import Decimal
from typing import Any

from one_quant.ml.factors.protocols import _safe_decimal, _safe_float

logger = logging.getLogger(__name__)


class FlowCVDFactor:
    """累计成交量差 CVD（Cumulative Volume Delta）。

    命名：flow_cvd
    计算：sum(买方成交量 - 卖方成交量)
    """

    def __init__(self) -> None:
        self.name = "flow_cvd"

    def compute(self, trades: list[dict[str, Any]]) -> Decimal | None:
        """计算 CVD。

        Args:
            trades: 交易列表，每条含 "side"（buy/sell）和 "qty"（数量）。

        Returns:
            累计成交量差，数据为空返回 None。
        """
        if not trades:
            return None

        cvd = Decimal("0")
        for trade in trades:
            side = trade.get("side", "")
            qty = _safe_decimal(trade.get("qty", 0))
            if qty is None:
                continue
            if side == "buy":
                cvd += qty
            elif side == "sell":
                cvd -= qty
            else:
                # 未知方向，跳过
                logger.warning("未知交易方向: %s，跳过", side)

        return cvd


class FlowFundingRateFactor:
    """资金费率因子。

    命名：flow_funding_rate
    计算：资金费率的符号和幅度，正费率 → 看多拥挤，负费率 → 看空拥挤
    """

    def __init__(self) -> None:
        self.name = "flow_funding_rate"

    def compute(self, rate: Decimal) -> float | None:
        """计算资金费率因子。

        Args:
            rate: 当前资金费率。

        Returns:
            归一化因子值，极端费率信号更强。
        """
        rate_f = _safe_float(rate)
        if rate_f is None:
            return None

        # 使用 tanh 归一化，放大极端值信号
        # 资金费率通常在 [-0.01, 0.01]，乘以 100 映射到 [-1, 1] 区间
        return round(math.tanh(rate_f * 100), 4)


class FlowLargeOrderNetFactor:
    """大单净流入因子。

    命名：flow_large_order_net
    计算：大单（超过阈值）的净买入量
    """

    def __init__(self) -> None:
        self.name = "flow_large_order_net"

    def compute(self, trades: list[dict[str, Any]], threshold: Decimal) -> Decimal | None:
        """计算大单净流入。

        Args:
            trades: 交易列表，每条含 "side" 和 "qty"。
            threshold: 大单阈值（qty >= threshold 视为大单）。

        Returns:
            大单净流入量，无大单返回 None。
        """
        if not trades:
            return None

        net = Decimal("0")
        count = 0
        for trade in trades:
            qty = _safe_decimal(trade.get("qty", 0))
            if qty is None or qty < threshold:
                continue
            side = trade.get("side", "")
            if side == "buy":
                net += qty
                count += 1
            elif side == "sell":
                net -= qty
                count += 1

        if count == 0:
            return None  # 无大单

        return net

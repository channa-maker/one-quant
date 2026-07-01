"""
因子库 — 波动因子
"""

from __future__ import annotations

import math
from decimal import Decimal

from one_quant.ml.factors.protocols import FactorResult, _now_ns


class VolatilityATRFactor:
    """ATR 波动因子（Average True Range）。

    命名：volatility_atr_{period}
    计算：EMA(True Range, period)
    """

    def __init__(self, period: int = 14) -> None:
        if period <= 0:
            raise ValueError(f"周期必须大于 0，当前: {period}")
        self.name = f"volatility_atr_{period}"
        self.period = period

    def compute(
        self,
        highs: list[Decimal],
        lows: list[Decimal],
        closes: list[Decimal],
    ) -> Decimal | None:
        """计算 ATR。

        Args:
            highs: 最高价序列。
            lows: 最低价序列。
            closes: 收盘价序列。

        Returns:
            ATR 值，数据不足返回 None。
        """
        n = min(len(highs), len(lows), len(closes))
        if n < self.period + 1:
            return None

        # 计算 True Range
        trs: list[Decimal] = []
        for i in range(n - self.period, n):
            high = highs[i]
            low = lows[i]
            prev_close = closes[i - 1]

            tr1 = high - low
            tr2 = abs(high - prev_close)
            tr3 = abs(low - prev_close)
            tr = max(tr1, tr2, tr3)
            trs.append(tr)

        # Wilder 平滑 ATR
        atr = trs[0]
        for tr in trs[1:]:
            atr = (atr * (self.period - 1) + tr) / self.period

        return atr


class VolatilityRealizedFactor:
    """已实现波动率因子。

    命名：volatility_realized_{window}
    计算：std(returns) * sqrt(365)（年化）
    """

    def __init__(self, window: int = 20) -> None:
        if window <= 0:
            raise ValueError(f"窗口大小必须大于 0，当前: {window}")
        self.name = f"volatility_realized_{window}"
        self.window = window

    def compute(self, returns: list[Decimal]) -> Decimal | None:
        """计算已实现波动率。

        Args:
            returns: 收益率序列（至少 window 个）。

        Returns:
            年化已实现波动率，数据不足返回 None。
        """
        if len(returns) < self.window:
            return None

        recent = returns[-self.window :]
        n = len(recent)

        # 计算均值
        mean: Decimal = sum(recent) / Decimal(str(n))

        # 计算样本标准差
        variance: Decimal = sum((r - mean) ** 2 for r in recent) / Decimal(str(n - 1))
        std = variance.sqrt() if variance > 0 else Decimal("0")

        # 年化（假设日频数据，365 天）
        annualized = std * Decimal(str(math.sqrt(365)))

        return annualized


class VolatilityStdFactor:
    """波动率标准差因子（向后兼容 VolatilityFactor）。"""

    def __init__(self, window: int = 20) -> None:
        if window <= 0:
            raise ValueError(f"窗口大小必须大于 0，当前: {window}")
        self.name = f"volatility_{window}"
        self.window = window
        self._prices: list[float] = []

    def update(self, price: float) -> FactorResult:
        """更新因子。"""
        self._prices.append(price)

        if len(self._prices) < self.window + 1:
            return FactorResult(
                name=self.name,
                value=None,
                timestamp_ns=_now_ns(),
                metadata={"samples": len(self._prices), "required": self.window + 1},
            )

        returns = []
        for i in range(len(self._prices) - self.window, len(self._prices)):
            if self._prices[i - 1] > 0:
                returns.append((self._prices[i] - self._prices[i - 1]) / self._prices[i - 1])

        if len(returns) < 2:
            return FactorResult(
                name=self.name,
                value=None,
                timestamp_ns=_now_ns(),
                metadata={"reason": "insufficient returns"},
            )

        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        std = math.sqrt(variance)

        return FactorResult(
            name=self.name,
            value=round(std, 6),
            timestamp_ns=_now_ns(),
            metadata={"window": self.window, "mean_return": mean, "samples": len(returns)},
        )


# 向后兼容别名
VolatilityFactor = VolatilityStdFactor

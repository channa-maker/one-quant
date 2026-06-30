"""
ONE量化 - 因子库

实现常用量化因子，用于策略信号和 ML 特征。
因子命名规范：{类别}_{名称}_{窗口}，如 momentum_return_20、rsi_14。

规范：
  - 因子值为 NaN / None 时必须返回 None，禁止静默传播
  - 所有因子实现 Factor 协议
  - 支持增量计算（传入新数据更新，不重新计算全量）
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)


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


class MomentumFactor:
    """动量因子：N 期收益率。

    命名：momentum_return_{window}
    计算：(close - close[n]) / close[n]

    Attributes:
        name: 因子名称。
        window: 回看窗口大小。
    """

    def __init__(self, window: int = 20) -> None:
        if window <= 0:
            raise ValueError(f"窗口大小必须大于 0，当前: {window}")
        self.name = f"momentum_return_{window}"
        self.window = window
        self._prices: list[float] = []

    def update(self, price: float) -> FactorResult:
        """更新因子（增量）。

        Args:
            price: 最新收盘价。

        Returns:
            因子计算结果。
        """
        import time

        self._prices.append(price)

        if len(self._prices) < self.window + 1:
            return FactorResult(
                name=self.name,
                value=None,
                timestamp_ns=time.time_ns(),
                metadata={"samples": len(self._prices), "required": self.window + 1},
            )

        old_price = self._prices[-(self.window + 1)]
        if old_price == 0:
            return FactorResult(
                name=self.name,
                value=None,
                timestamp_ns=time.time_ns(),
                metadata={"reason": "old_price is zero"},
            )

        ret = (price - old_price) / old_price
        return FactorResult(
            name=self.name,
            value=round(ret, 6),
            timestamp_ns=time.time_ns(),
            metadata={"window": self.window, "old_price": old_price, "new_price": price},
        )


class RSIFactor:
    """RSI 因子：相对强弱指数。

    命名：rsi_{window}
    计算：经典 Wilder RSI

    Attributes:
        name: 因子名称。
        window: 回看窗口大小。
    """

    def __init__(self, window: int = 14) -> None:
        if window <= 0:
            raise ValueError(f"窗口大小必须大于 0，当前: {window}")
        self.name = f"rsi_{window}"
        self.window = window
        self._prices: list[float] = []

    def update(self, price: float) -> FactorResult:
        """更新因子。

        Args:
            price: 最新收盘价。

        Returns:
            因子计算结果。
        """
        import time

        self._prices.append(price)

        if len(self._prices) < self.window + 1:
            return FactorResult(
                name=self.name,
                value=None,
                timestamp_ns=time.time_ns(),
                metadata={"samples": len(self._prices), "required": self.window + 1},
            )

        # 计算涨跌幅
        changes = [
            self._prices[i] - self._prices[i - 1]
            for i in range(len(self._prices) - self.window, len(self._prices))
        ]

        gains = [c for c in changes if c > 0]
        losses = [-c for c in changes if c < 0]

        avg_gain = sum(gains) / self.window if gains else 0
        avg_loss = sum(losses) / self.window if losses else 0

        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

        return FactorResult(
            name=self.name,
            value=round(rsi, 2),
            timestamp_ns=time.time_ns(),
            metadata={"window": self.window, "avg_gain": avg_gain, "avg_loss": avg_loss},
        )


class VolatilityFactor:
    """波动率因子：N 期收益率标准差。

    命名：volatility_{window}
    计算：std(returns, window)

    Attributes:
        name: 因子名称。
        window: 回看窗口大小。
    """

    def __init__(self, window: int = 20) -> None:
        if window <= 0:
            raise ValueError(f"窗口大小必须大于 0，当前: {window}")
        self.name = f"volatility_{window}"
        self.window = window
        self._prices: list[float] = []

    def update(self, price: float) -> FactorResult:
        """更新因子。

        Args:
            price: 最新收盘价。

        Returns:
            因子计算结果。
        """
        import time

        self._prices.append(price)

        if len(self._prices) < self.window + 1:
            return FactorResult(
                name=self.name,
                value=None,
                timestamp_ns=time.time_ns(),
                metadata={"samples": len(self._prices), "required": self.window + 1},
            )

        # 计算收益率
        returns = []
        for i in range(len(self._prices) - self.window, len(self._prices)):
            if self._prices[i - 1] > 0:
                returns.append((self._prices[i] - self._prices[i - 1]) / self._prices[i - 1])

        if len(returns) < 2:
            return FactorResult(
                name=self.name,
                value=None,
                timestamp_ns=time.time_ns(),
                metadata={"reason": "insufficient returns"},
            )

        # 标准差
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        std = math.sqrt(variance)

        return FactorResult(
            name=self.name,
            value=round(std, 6),
            timestamp_ns=time.time_ns(),
            metadata={"window": self.window, "mean_return": mean, "samples": len(returns)},
        )


class VolumeFactor:
    """成交量因子：当前成交量 vs N 期均量。

    命名：volume_ratio_{window}
    计算：volume / mean(volume, window)

    Attributes:
        name: 因子名称。
        window: 回看窗口大小。
    """

    def __init__(self, window: int = 20) -> None:
        if window <= 0:
            raise ValueError(f"窗口大小必须大于 0，当前: {window}")
        self.name = f"volume_ratio_{window}"
        self.window = window
        self._volumes: list[float] = []

    def update(self, volume: float) -> FactorResult:
        """更新因子。

        Args:
            volume: 最新成交量。

        Returns:
            因子计算结果。
        """
        import time

        self._volumes.append(volume)

        if len(self._volumes) < self.window:
            return FactorResult(
                name=self.name,
                value=None,
                timestamp_ns=time.time_ns(),
                metadata={"samples": len(self._volumes), "required": self.window},
            )

        recent = self._volumes[-self.window:]
        mean_vol = sum(recent) / len(recent)

        if mean_vol == 0:
            return FactorResult(
                name=self.name,
                value=None,
                timestamp_ns=time.time_ns(),
                metadata={"reason": "mean volume is zero"},
            )

        ratio = volume / mean_vol
        return FactorResult(
            name=self.name,
            value=round(ratio, 4),
            timestamp_ns=time.time_ns(),
            metadata={"window": self.window, "current": volume, "mean": mean_vol},
        )

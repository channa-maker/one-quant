"""
因子库 — 动量因子
"""

from __future__ import annotations

from decimal import Decimal

from one_quant.ml.factors.protocols import FactorResult, _now_ns, _safe_float


class MomentumFactor:
    """动量因子：N 期收益率。

    命名：momentum_return_{window}
    计算：(close - close[n]) / close[n]
    """

    def __init__(self, window: int = 20) -> None:
        if window <= 0:
            raise ValueError(f"窗口大小必须大于 0，当前: {window}")
        self.name = f"momentum_return_{window}"
        self.window = window
        self._prices: list[float] = []

    def update(self, price: float) -> FactorResult:
        """更新因子（增量）。"""
        self._prices.append(price)

        if len(self._prices) < self.window + 1:
            return FactorResult(
                name=self.name,
                value=None,
                timestamp_ns=_now_ns(),
                metadata={"samples": len(self._prices), "required": self.window + 1},
            )

        old_price = self._prices[-(self.window + 1)]
        if old_price == 0:
            return FactorResult(
                name=self.name,
                value=None,
                timestamp_ns=_now_ns(),
                metadata={"reason": "old_price is zero"},
            )

        ret = (price - old_price) / old_price
        return FactorResult(
            name=self.name,
            value=round(ret, 6),
            timestamp_ns=_now_ns(),
            metadata={"window": self.window, "old_price": old_price, "new_price": price},
        )


class RSIFactor:
    """RSI 因子：相对强弱指数。

    命名：rsi_{window}（对应 momentum_rsi_{window}）
    计算：经典 Wilder RSI
    """

    def __init__(self, window: int = 14) -> None:
        if window <= 0:
            raise ValueError(f"窗口大小必须大于 0，当前: {window}")
        self.name = f"momentum_rsi_{window}"
        self.window = window
        self._prices: list[float] = []

    def update(self, price: float) -> FactorResult:
        """更新因子。"""
        price_float = float(price)
        self._prices.append(price_float)

        if len(self._prices) < self.window + 1:
            return FactorResult(
                name=self.name,
                value=None,
                timestamp_ns=_now_ns(),
                metadata={"samples": len(self._prices), "required": self.window + 1},
            )

        changes = [
            self._prices[i] - self._prices[i - 1]
            for i in range(len(self._prices) - self.window, len(self._prices))
        ]

        gains = [c for c in changes if c > 0]
        losses = [-c for c in changes if c < 0]

        avg_gain = sum(gains) / self.window if gains else 0.0
        avg_loss = sum(losses) / self.window if losses else 0.0

        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

        return FactorResult(
            name=self.name,
            value=round(float(rsi), 2),
            timestamp_ns=_now_ns(),
            metadata={
                "window": self.window,
                "avg_gain": float(avg_gain),
                "avg_loss": float(avg_loss),
            },
        )


class MomentumRSIFactor:
    """RSI 动量因子（批量接口）。

    命名：momentum_rsi_{period}
    """

    def __init__(self, period: int = 14) -> None:
        if period <= 0:
            raise ValueError(f"周期必须大于 0，当前: {period}")
        self.name = f"momentum_rsi_{period}"
        self.period = period

    def compute(self, prices: list[Decimal]) -> float | None:
        """批量计算 RSI。

        Args:
            prices: 收盘价序列（至少 period+1 个）。

        Returns:
            RSI 值（0-100），数据不足返回 None。
        """
        if len(prices) < self.period + 1:
            return None

        changes: list[float] = []
        for i in range(len(prices) - self.period, len(prices)):
            diff = float(prices[i]) - float(prices[i - 1])
            changes.append(diff)

        gains = [c for c in changes if c > 0]
        losses = [-c for c in changes if c < 0]

        avg_gain = sum(gains) / self.period if gains else 0.0
        avg_loss = sum(losses) / self.period if losses else 0.0

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return float(rsi)


class MomentumMACDFactor:
    """MACD 动量因子。

    命名：momentum_macd_{fast}_{slow}_{signal}
    返回：macd_line, signal_line, histogram
    """

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9) -> None:
        if fast <= 0 or slow <= 0 or signal <= 0:
            raise ValueError("fast/slow/signal 必须大于 0")
        if fast >= slow:
            raise ValueError("fast 必须小于 slow")
        self.name = f"momentum_macd_{fast}_{slow}_{signal}"
        self.fast = fast
        self.slow = slow
        self.signal = signal

    def compute(self, prices: list[Decimal]) -> dict[str, float | None]:
        """计算 MACD。

        Args:
            prices: 收盘价序列。

        Returns:
            {"macd": ..., "signal": ..., "histogram": ...}
        """
        min_len = self.slow + self.signal
        if len(prices) < min_len:
            return {"macd": None, "signal": None, "histogram": None}

        prices_f = [float(p) for p in prices]

        # EMA 计算
        fast_ema = self._ema(prices_f, self.fast)
        slow_ema = self._ema(prices_f, self.slow)

        # MACD 线 = fast_ema - slow_ema
        macd_line = [f - s for f, s in zip(fast_ema[-self.signal :], slow_ema[-self.signal :])]

        # 信号线 = EMA(MACD, signal)
        signal_ema = self._ema_from_list(macd_line, self.signal)

        macd_val = macd_line[-1] if macd_line else None
        signal_val = signal_ema[-1] if signal_ema else None
        histogram = (
            (macd_val - signal_val) if macd_val is not None and signal_val is not None else None
        )

        return {
            "macd": round(macd_val, 6) if macd_val is not None else None,
            "signal": round(signal_val, 6) if signal_val is not None else None,
            "histogram": round(histogram, 6) if histogram is not None else None,
        }

    @staticmethod
    def _ema(data: list[float], period: int) -> list[float]:
        """计算 EMA 序列。"""
        if len(data) < period:
            return []
        multiplier = 2.0 / (period + 1)
        ema = [sum(data[:period]) / period]
        for price in data[period:]:
            ema.append((price - ema[-1]) * multiplier + ema[-1])
        return ema

    @staticmethod
    def _ema_from_list(data: list[float], period: int) -> list[float]:
        """从已有列表计算 EMA。"""
        if len(data) < period:
            return []
        multiplier = 2.0 / (period + 1)
        ema = [sum(data[:period]) / period]
        for val in data[period:]:
            ema.append((val - ema[-1]) * multiplier + ema[-1])
        return ema


class MomentumBreakoutFactor:
    """突破强度因子。

    命名：momentum_breakout_{window}
    计算：(close - max(high, window)) / max(high, window)  归一化突破幅度
    """

    def __init__(self, window: int = 20) -> None:
        if window <= 0:
            raise ValueError(f"窗口大小必须大于 0，当前: {window}")
        self.name = f"momentum_breakout_{window}"
        self.window = window

    def compute(self, prices: list[Decimal]) -> float | None:
        """计算突破强度。

        Args:
            prices: 收盘价序列（至少 window 个）。

        Returns:
            突破强度（正数=向上突破，负数=向下突破），数据不足返回 None。
        """
        if len(prices) < self.window:
            return None

        recent = prices[-self.window :]
        current = prices[-1]
        high = max(recent)
        low = min(recent)

        if high == low:
            return None  # 无波动，避免除零

        # 归一化到 [-1, 1]：(current - mid) / (high - low) * 2
        mid = (high + low) / 2
        strength = (
            (current - mid) / (high - mid) if current >= mid else (current - mid) / (mid - low)
        )
        return _safe_float(strength)


class MomentumReturnFactor:
    """N 期收益率因子（向后兼容 MomentumFactor）。"""

    def __init__(self, window: int = 20) -> None:
        self._inner = MomentumFactor(window)
        self.name = self._inner.name
        self.window = self._inner.window

    def update(self, price: float) -> FactorResult:
        return self._inner.update(price)

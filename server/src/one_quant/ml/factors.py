"""
ONE量化 - 因子库

实现常用量化因子，用于策略信号和 ML 特征。
因子命名规范：{类别}_{名称}_{窗口}，如 momentum_rsi_14、volatility_atr_14。

规范：
  - 因子值为 NaN / None 时必须返回 None，禁止静默传播
  - 所有因子实现 Factor 协议
  - 支持增量计算（传入新数据更新，不重新计算全量）
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, DivisionByZero
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 协议与结果
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# 动量因子
# ---------------------------------------------------------------------------

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
        self._prices.append(price)

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

        avg_gain = sum(gains) / self.window if gains else Decimal("0")
        avg_loss = sum(losses) / self.window if losses else Decimal("0")

        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

        return FactorResult(
            name=self.name,
            value=round(float(rsi), 2),
            timestamp_ns=_now_ns(),
            metadata={"window": self.window, "avg_gain": float(avg_gain), "avg_loss": float(avg_loss)},
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

        changes: list[Decimal] = []
        for i in range(len(prices) - self.period, len(prices)):
            diff = prices[i] - prices[i - 1]
            changes.append(diff)

        gains = [c for c in changes if c > 0]
        losses = [-c for c in changes if c < 0]

        avg_gain = sum(gains) / self.period if gains else Decimal("0")
        avg_loss = sum(losses) / self.period if losses else Decimal("0")

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return _safe_float(rsi)


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
        macd_line = [f - s for f, s in zip(fast_ema[-self.signal:], slow_ema[-self.signal:])]

        # 信号线 = EMA(MACD, signal)
        signal_ema = self._ema_from_list(macd_line, self.signal)

        macd_val = macd_line[-1] if macd_line else None
        signal_val = signal_ema[-1] if signal_ema else None
        histogram = (macd_val - signal_val) if macd_val is not None and signal_val is not None else None

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

        recent = prices[-self.window:]
        current = prices[-1]
        high = max(recent)
        low = min(recent)

        if high == low:
            return None  # 无波动，避免除零

        # 归一化到 [-1, 1]：(current - mid) / (high - low) * 2
        mid = (high + low) / 2
        strength = (current - mid) / (high - mid) if current >= mid else (current - mid) / (mid - low)
        return _safe_float(strength)


# ---------------------------------------------------------------------------
# 资金流因子
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# 波动因子
# ---------------------------------------------------------------------------

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

        recent = returns[-self.window:]
        n = len(recent)

        # 计算均值
        mean = sum(recent) / n

        # 计算样本标准差
        variance = sum((r - mean) ** 2 for r in recent) / (n - 1)
        std = variance.sqrt() if variance > 0 else Decimal("0")

        # 年化（假设日频数据，365 天）
        annualized = std * Decimal(str(math.sqrt(365)))

        return annualized


# ---------------------------------------------------------------------------
# 情绪因子
# ---------------------------------------------------------------------------

class SentimentScoreFactor:
    """新闻情绪因子。

    命名：sentiment_score
    计算：基于关键词的简易情绪打分（-1 到 1）
    注意：生产环境应替换为 NLP 模型推理
    """

    # 简易情绪词典
    _POSITIVE_WORDS = {
        "利好", "上涨", "突破", "新高", "暴涨", "牛市", "盈利", "增长",
        "bullish", "surge", "rally", "breakout", "gain", "profit", "rise",
    }
    _NEGATIVE_WORDS = {
        "利空", "下跌", "暴跌", "新低", "崩盘", "熊市", "亏损", "衰退",
        "bearish", "crash", "dump", "loss", "decline", "fall", "panic",
    }

    def __init__(self) -> None:
        self.name = "sentiment_score"

    def compute(self, news_texts: list[str]) -> float | None:
        """计算情绪分数。

        Args:
            news_texts: 新闻文本列表。

        Returns:
            情绪分数 [-1, 1]，无数据返回 None。
        """
        if not news_texts:
            return None

        total_score = 0.0
        scored_count = 0

        for text in news_texts:
            text_lower = text.lower()
            pos = sum(1 for w in self._POSITIVE_WORDS if w in text_lower)
            neg = sum(1 for w in self._NEGATIVE_WORDS if w in text_lower)
            total = pos + neg
            if total > 0:
                total_score += (pos - neg) / total
                scored_count += 1

        if scored_count == 0:
            return 0.0  # 无情绪词，视为中性

        return round(total_score / scored_count, 4)


# ---------------------------------------------------------------------------
# 事件因子
# ---------------------------------------------------------------------------

class EventCalendarProximityFactor:
    """事件日历临近度因子。

    命名：event_calendar_proximity
    计算：距离事件的天数越近，因子值越大（指数衰减）
    """

    def __init__(self) -> None:
        self.name = "event_calendar_proximity"

    def compute(self, event_date: int, current_date: int) -> float | None:
        """计算事件临近度。

        Args:
            event_date: 事件日期（YYYYMMDD 或 Unix timestamp 天）。
            current_date: 当前日期（同格式）。

        Returns:
            临近度 [0, 1]，1=当天，指数衰减。已过期返回 None。
        """
        diff = event_date - current_date
        if diff < 0:
            return None  # 事件已过

        # 指数衰减：e^(-diff/7)，7 天半衰期
        proximity = math.exp(-diff / 7.0)
        return round(proximity, 4)


# ---------------------------------------------------------------------------
# 原有因子（保持向后兼容）
# ---------------------------------------------------------------------------

class MomentumReturnFactor:
    """N 期收益率因子（向后兼容 MomentumFactor）。"""

    def __init__(self, window: int = 20) -> None:
        self._inner = MomentumFactor(window)
        self.name = self._inner.name
        self.window = self._inner.window

    def update(self, price: float) -> FactorResult:
        return self._inner.update(price)


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


class VolumeRatioFactor:
    """成交量比率因子（向后兼容 VolumeFactor）。"""

    def __init__(self, window: int = 20) -> None:
        if window <= 0:
            raise ValueError(f"窗口大小必须大于 0，当前: {window}")
        self.name = f"volume_ratio_{window}"
        self.window = window
        self._volumes: list[float] = []

    def update(self, volume: float) -> FactorResult:
        """更新因子。"""
        self._volumes.append(volume)

        if len(self._volumes) < self.window:
            return FactorResult(
                name=self.name,
                value=None,
                timestamp_ns=_now_ns(),
                metadata={"samples": len(self._volumes), "required": self.window},
            )

        recent = self._volumes[-self.window:]
        mean_vol = sum(recent) / len(recent)

        if mean_vol == 0:
            return FactorResult(
                name=self.name,
                value=None,
                timestamp_ns=_now_ns(),
                metadata={"reason": "mean volume is zero"},
            )

        ratio = volume / mean_vol
        return FactorResult(
            name=self.name,
            value=round(ratio, 4),
            timestamp_ns=_now_ns(),
            metadata={"window": self.window, "current": volume, "mean": mean_vol},
        )


# 向后兼容别名
VolatilityFactor = VolatilityStdFactor
VolumeFactor = VolumeRatioFactor


# ---------------------------------------------------------------------------
# 批量计算接口（面向 ML 管线）
# ---------------------------------------------------------------------------

class FactorCalculator:
    """因子计算器 — 统一入口，供 ML 管线调用。

    组合所有因子类，提供批量计算接口。
    """

    def __init__(self) -> None:
        self._momentum_rsi = MomentumRSIFactor()
        self._momentum_macd = MomentumMACDFactor()
        self._momentum_breakout = MomentumBreakoutFactor()
        self._flow_cvd = FlowCVDFactor()
        self._flow_funding = FlowFundingRateFactor()
        self._flow_large_order = FlowLargeOrderNetFactor()
        self._volatility_atr = VolatilityATRFactor()
        self._volatility_realized = VolatilityRealizedFactor()
        self._sentiment = SentimentScoreFactor()
        self._event_proximity = EventCalendarProximityFactor()

    def momentum_rsi(self, prices: list[Decimal], period: int = 14) -> float | None:
        """RSI 动量因子。"""
        return MomentumRSIFactor(period).compute(prices)

    def momentum_macd(
        self, prices: list[Decimal], fast: int = 12, slow: int = 26, signal: int = 9
    ) -> dict[str, float | None]:
        """MACD 因子。"""
        return MomentumMACDFactor(fast, slow, signal).compute(prices)

    def momentum_breakout(self, prices: list[Decimal], window: int = 20) -> float | None:
        """突破强度因子。"""
        return MomentumBreakoutFactor(window).compute(prices)

    def flow_cvd(self, trades: list[dict[str, Any]]) -> Decimal | None:
        """累计成交量差 CVD。"""
        return self._flow_cvd.compute(trades)

    def flow_funding_rate(self, rate: Decimal) -> float | None:
        """资金费率因子。"""
        return self._flow_funding.compute(rate)

    def flow_large_order_net(
        self, trades: list[dict[str, Any]], threshold: Decimal
    ) -> Decimal | None:
        """大单净流入。"""
        return self._flow_large_order.compute(trades, threshold)

    def volatility_atr(
        self,
        highs: list[Decimal],
        lows: list[Decimal],
        closes: list[Decimal],
        period: int = 14,
    ) -> Decimal | None:
        """ATR 波动因子。"""
        return VolatilityATRFactor(period).compute(highs, lows, closes)

    def volatility_realized(
        self, returns: list[Decimal], window: int = 20
    ) -> Decimal | None:
        """已实现波动率。"""
        return VolatilityRealizedFactor(window).compute(returns)

    def sentiment_score(self, news_texts: list[str]) -> float | None:
        """新闻情绪因子（-1 到 1）。"""
        return self._sentiment.compute(news_texts)

    def event_calendar_proximity(
        self, event_date: int, current_date: int
    ) -> float | None:
        """事件日历临近度。"""
        return self._event_proximity.compute(event_date, current_date)

    def compute_all(self, market_data: dict[str, Any]) -> dict[str, float | None]:
        """从市场数据字典批量计算所有因子。

        Args:
            market_data: 市场数据，键包括：
                - prices: list[Decimal] — 收盘价
                - highs: list[Decimal] — 最高价
                - lows: list[Decimal] — 最低价
                - closes: list[Decimal] — 收盘价（别名）
                - returns: list[Decimal] — 收益率
                - trades: list[dict] — 交易数据
                - funding_rate: Decimal — 资金费率
                - news_texts: list[str] — 新闻文本
                - event_date: int — 事件日期
                - current_date: int — 当前日期

        Returns:
            因子名到因子值的映射，None 表示数据不足。
        """
        result: dict[str, float | None] = {}
        prices = market_data.get("prices") or market_data.get("closes", [])
        highs = market_data.get("highs", [])
        lows = market_data.get("lows", [])
        closes = market_data.get("closes") or prices
        returns = market_data.get("returns", [])
        trades = market_data.get("trades", [])
        funding_rate = market_data.get("funding_rate")
        news_texts = market_data.get("news_texts", [])
        event_date = market_data.get("event_date")
        current_date = market_data.get("current_date")
        large_order_threshold = market_data.get("large_order_threshold")

        # 动量因子
        if prices:
            result["momentum_rsi_14"] = self.momentum_rsi(prices, 14)
            result["momentum_rsi_7"] = self.momentum_rsi(prices, 7)
            macd = self.momentum_macd(prices)
            result["momentum_macd_12_26_9"] = macd.get("histogram")
            result["momentum_breakout_20"] = self.momentum_breakout(prices, 20)

        # 资金流因子
        if trades:
            cvd = self.flow_cvd(trades)
            result["flow_cvd"] = _safe_float(cvd)
            if large_order_threshold is not None:
                threshold = _safe_decimal(large_order_threshold) or Decimal("0")
                lon = self.flow_large_order_net(trades, threshold)
                result["flow_large_order_net"] = _safe_float(lon)

        if funding_rate is not None:
            result["flow_funding_rate"] = self.flow_funding_rate(
                _safe_decimal(funding_rate) or Decimal("0")
            )

        # 波动因子
        if highs and lows and closes:
            atr = self.volatility_atr(highs, lows, closes, 14)
            result["volatility_atr_14"] = _safe_float(atr)

        if returns:
            rv = self.volatility_realized(returns, 20)
            result["volatility_realized_20"] = _safe_float(rv)

        # 情绪因子
        if news_texts:
            result["sentiment_score"] = self.sentiment_score(news_texts)

        # 事件因子
        if event_date is not None and current_date is not None:
            result["event_calendar_proximity"] = self.event_calendar_proximity(
                event_date, current_date
            )

        return result


# ---------------------------------------------------------------------------
# 因子库管理器
# ---------------------------------------------------------------------------

class FactorLibrary:
    """因子库管理器 — 注册、查询、批量计算。

    职责：
      - 管理因子元数据注册表
      - 统一调度因子计算
      - 支持因子的启用/禁用
    """

    def __init__(self) -> None:
        self._calculator = FactorCalculator()
        self._registry: dict[str, dict[str, Any]] = {}

    @property
    def calculator(self) -> FactorCalculator:
        """获取底层计算器。"""
        return self._calculator

    def register(self, name: str, category: str, description: str) -> None:
        """注册因子元数据。

        Args:
            name: 因子名称（遵循 {类别}_{名称}_{窗口} 规范）。
            category: 因子类别（momentum/flow/volatility/sentiment/event）。
            description: 因子描述。
        """
        self._registry[name] = {
            "name": name,
            "category": category,
            "description": description,
            "enabled": True,
        }

    def enable(self, name: str) -> None:
        """启用因子。"""
        if name in self._registry:
            self._registry[name]["enabled"] = True

    def disable(self, name: str) -> None:
        """禁用因子。"""
        if name in self._registry:
            self._registry[name]["enabled"] = False

    def compute_all(self, market_data: dict[str, Any]) -> dict[str, float | None]:
        """计算所有已注册且启用的因子。

        Args:
            market_data: 市场数据字典（参见 FactorCalculator.compute_all）。

        Returns:
            因子名到因子值的映射。
        """
        all_factors = self._calculator.compute_all(market_data)

        # 如果有注册表，过滤出已注册且启用的因子
        if self._registry:
            return {
                k: v
                for k, v in all_factors.items()
                if k in self._registry and self._registry[k].get("enabled", True)
            }

        # 未注册时返回全部
        return all_factors

    def get_factor_info(self, name: str) -> dict[str, Any] | None:
        """获取因子元数据。

        Args:
            name: 因子名称。

        Returns:
            因子元数据字典，不存在返回 None。
        """
        return self._registry.get(name)

    def list_factors(self, category: str | None = None) -> list[dict[str, Any]]:
        """列出所有已注册因子。

        Args:
            category: 可选，按类别过滤。

        Returns:
            因子元数据列表。
        """
        factors = list(self._registry.values())
        if category:
            factors = [f for f in factors if f["category"] == category]
        return factors

    def register_defaults(self) -> None:
        """注册默认因子集。"""
        defaults = [
            ("momentum_rsi_14", "momentum", "RSI 动量因子（14 周期）"),
            ("momentum_rsi_7", "momentum", "RSI 动量因子（7 周期）"),
            ("momentum_macd_12_26_9", "momentum", "MACD 动量因子"),
            ("momentum_breakout_20", "momentum", "突破强度因子（20 周期）"),
            ("flow_cvd", "flow", "累计成交量差 CVD"),
            ("flow_funding_rate", "flow", "资金费率因子"),
            ("flow_large_order_net", "flow", "大单净流入"),
            ("volatility_atr_14", "volatility", "ATR 波动因子（14 周期）"),
            ("volatility_realized_20", "volatility", "已实现波动率（20 周期）"),
            ("sentiment_score", "sentiment", "新闻情绪因子"),
            ("event_calendar_proximity", "event", "事件日历临近度"),
        ]
        for name, category, description in defaults:
            self.register(name, category, description)

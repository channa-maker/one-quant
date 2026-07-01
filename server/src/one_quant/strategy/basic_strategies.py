"""基础策略 ×3 — EMA 交叉 / RSI 反转 / 网格"""

from __future__ import annotations

from collections import deque
from decimal import Decimal

from one_quant.core.types import Kline, Market, Signal, Ticker
from one_quant.infra.registry import register_strategy
from one_quant.strategy.contracts import Strategy

# ──────────────────── EMA 交叉策略 ────────────────────


@register_strategy("ema_cross")
class EMACrossStrategy(Strategy):
    """EMA 交叉策略。

    EMA12 上穿 EMA26 → 买入信号
    EMA12 下穿 EMA26 → 卖出信号
    """

    name = "ema_cross"
    enabled = False

    def __init__(
        self, fast_period: int = 12, slow_period: int = 26, symbol: str = "BTC/USDT"
    ) -> None:
        self._fast_period = fast_period
        self._slow_period = slow_period
        self._symbol = symbol
        self._closes: deque[Decimal] = deque(maxlen=max(fast_period, slow_period) * 3)
        self._fast_ema = Decimal("0")
        self._slow_ema = Decimal("0")
        self._prev_fast = Decimal("0")
        self._prev_slow = Decimal("0")
        self._initialized = False

    def _update_ema(self, close: Decimal) -> None:
        self._closes.append(close)
        if len(self._closes) < self._slow_period:
            return

        if not self._initialized:
            self._fast_ema = sum(list(self._closes)[-self._fast_period :], Decimal("0")) / Decimal(
                str(self._fast_period)
            )
            self._slow_ema = sum(list(self._closes)[-self._slow_period :], Decimal("0")) / Decimal(
                str(self._slow_period)
            )
            self._initialized = True
        else:
            k_fast = Decimal(2) / (self._fast_period + 1)
            k_slow = Decimal(2) / (self._slow_period + 1)
            self._prev_fast = self._fast_ema
            self._prev_slow = self._slow_ema
            self._fast_ema = close * k_fast + self._fast_ema * (1 - k_fast)
            self._slow_ema = close * k_slow + self._slow_ema * (1 - k_slow)

    def on_ticker(self, ticker: Ticker) -> list[Signal]:
        if ticker.symbol != self._symbol:
            return []
        self._update_ema(ticker.last_price)
        return self._check_cross(ticker.last_price, ticker.timestamp_ns)

    def on_kline(self, kline: Kline) -> list[Signal]:
        if kline.symbol != self._symbol:
            return []
        self._update_ema(kline.close)
        return self._check_cross(kline.close, kline.timestamp_ns)

    def _check_cross(self, price: Decimal, ts_ns: int) -> list[Signal]:
        if not self._initialized or self._prev_fast == 0:
            return []

        # 金叉：fast 上穿 slow
        if self._prev_fast <= self._prev_slow and self._fast_ema > self._slow_ema:
            return [
                Signal(
                    symbol=self._symbol,
                    market=Market.SPOT,
                    side="buy",
                    strength=0.7,
                    strategy_name=self.name,
                    reason=f"EMA{self._fast_period} 上穿 EMA{self._slow_period}，金叉信号",
                    timestamp_ns=ts_ns,
                )
            ]

        # 死叉：fast 下穿 slow
        if self._prev_fast >= self._prev_slow and self._fast_ema < self._slow_ema:
            return [
                Signal(
                    symbol=self._symbol,
                    market=Market.SPOT,
                    side="sell",
                    strength=0.7,
                    strategy_name=self.name,
                    reason=f"EMA{self._fast_period} 下穿 EMA{self._slow_period}，死叉信号",
                    timestamp_ns=ts_ns,
                )
            ]

        return []


# ──────────────────── RSI 反转策略 ────────────────────


@register_strategy("rsi_reversal")
class RSIReversalStrategy(Strategy):
    """RSI 反转策略。

    RSI < 30 且开始回升 → 买入（超卖反弹）
    RSI > 70 且开始回落 → 卖出（超买回调）
    """

    name = "rsi_reversal"
    enabled = False

    def __init__(
        self,
        period: int = 14,
        oversold: float = 30,
        overbought: float = 70,
        symbol: str = "BTC/USDT",
    ) -> None:
        self._period = period
        self._oversold = Decimal(str(oversold))
        self._overbought = Decimal(str(overbought))
        self._symbol = symbol
        self._closes: deque[Decimal] = deque(maxlen=period * 3)
        self._prev_rsi = Decimal("50")

    def _calc_rsi(self) -> Decimal:
        if len(self._closes) < self._period + 1:
            return Decimal("50")

        closes = list(self._closes)
        gains = []
        losses = []
        for i in range(-self._period, 0):
            delta = closes[i] - closes[i - 1]
            if delta > 0:
                gains.append(delta)
                losses.append(Decimal("0"))
            else:
                gains.append(Decimal("0"))
                losses.append(-delta)

        avg_gain = sum(gains) / self._period if gains else Decimal("0")
        avg_loss = sum(losses) / self._period if losses else Decimal("0")

        if avg_loss == 0:
            return Decimal("100")
        rs = avg_gain / avg_loss
        return Decimal("100") - Decimal("100") / (Decimal("1") + rs)

    def on_ticker(self, ticker: Ticker) -> list[Signal]:
        if ticker.symbol != self._symbol:
            return []
        self._closes.append(ticker.last_price)
        return self._check_rsi(ticker.last_price, ticker.timestamp_ns)

    def on_kline(self, kline: Kline) -> list[Signal]:
        if kline.symbol != self._symbol:
            return []
        self._closes.append(kline.close)
        return self._check_rsi(kline.close, kline.timestamp_ns)

    def _check_rsi(self, price: Decimal, ts_ns: int) -> list[Signal]:
        rsi = self._calc_rsi()
        signals: list[Signal] = []

        # RSI 从超卖区回升
        if self._prev_rsi < self._oversold and rsi >= self._oversold:
            signals.append(
                Signal(
                    symbol=self._symbol,
                    market=Market.SPOT,
                    side="buy",
                    strength=0.65,
                    strategy_name=self.name,
                    reason=f"RSI 从 {self._prev_rsi:.1f} 回升至 {rsi:.1f}，超卖反弹信号",
                    timestamp_ns=ts_ns,
                )
            )

        # RSI 从超买区回落
        if self._prev_rsi > self._overbought and rsi <= self._overbought:
            signals.append(
                Signal(
                    symbol=self._symbol,
                    market=Market.SPOT,
                    side="sell",
                    strength=0.65,
                    strategy_name=self.name,
                    reason=f"RSI 从 {self._prev_rsi:.1f} 回落至 {rsi:.1f}，超买回调信号",
                    timestamp_ns=ts_ns,
                )
            )

        self._prev_rsi = rsi
        return signals


# ──────────────────── 网格策略 ────────────────────


@register_strategy("grid")
class GridStrategy(Strategy):
    """网格策略。

    在指定价格区间内均匀布置买卖网格。
    价格触网即交易，适合震荡行情。
    """

    name = "grid"
    enabled = False

    def __init__(
        self,
        symbol: str = "BTC/USDT",
        grid_lower: Decimal = Decimal("40000"),
        grid_upper: Decimal = Decimal("50000"),
        grid_count: int = 10,
    ) -> None:
        self._symbol = symbol
        self._grid_lower = grid_lower
        self._grid_upper = grid_upper
        self._grid_count = grid_count
        self._grid_step = (grid_upper - grid_lower) / grid_count
        self._last_price = Decimal("0")
        self._filled_grids: set[int] = set()

    def on_ticker(self, ticker: Ticker) -> list[Signal]:
        if ticker.symbol != self._symbol:
            return []
        return self._check_grid(ticker.last_price, ticker.timestamp_ns)

    def on_kline(self, kline: Kline) -> list[Signal]:
        if kline.symbol != self._symbol:
            return []
        return self._check_grid(kline.close, kline.timestamp_ns)

    def _check_grid(self, price: Decimal, ts_ns: int) -> list[Signal]:
        if price < self._grid_lower or price > self._grid_upper:
            return []

        # 计算当前价格所在的网格索引
        grid_idx = int((price - self._grid_lower) / self._grid_step)
        grid_idx = max(0, min(grid_idx, self._grid_count - 1))

        signals: list[Signal] = []

        if self._last_price > 0:
            last_idx = int((self._last_price - self._grid_lower) / self._grid_step)
            last_idx = max(0, min(last_idx, self._grid_count - 1))

            # 价格下穿网格线 → 买入
            if grid_idx < last_idx and grid_idx not in self._filled_grids:
                self._filled_grids.add(grid_idx)
                signals.append(
                    Signal(
                        symbol=self._symbol,
                        market=Market.SPOT,
                        side="buy",
                        strength=0.5,
                        strategy_name=self.name,
                        reason=f"网格买入：价格 {price} 触及第 {grid_idx} 格",
                        timestamp_ns=ts_ns,
                    )
                )

            # 价格上穿网格线 → 卖出
            if grid_idx > last_idx and last_idx in self._filled_grids:
                self._filled_grids.discard(last_idx)
                signals.append(
                    Signal(
                        symbol=self._symbol,
                        market=Market.SPOT,
                        side="sell",
                        strength=0.5,
                        strategy_name=self.name,
                        reason=f"网格卖出：价格 {price} 上穿第 {last_idx} 格",
                        timestamp_ns=ts_ns,
                    )
                )

        self._last_price = price
        return signals

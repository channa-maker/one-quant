"""
ONE量化 - EMA 交叉策略

核心思想：
  快速 EMA 上穿慢速 EMA（金叉）做多，快速 EMA 下穿慢速 EMA（死叉）做空。
  属于经典趋势跟踪策略，在单边趋势行情中表现较好，震荡行情中容易出现频繁止损。

适用市场环境：
  - 趋势行情（上升/下降趋势明确）：信号准确率较高，能捕捉主要趋势段
  - 震荡行情（价格区间波动）：信号频繁且假突破多，表现较差
  - 建议配合波动率过滤器或 ADX 等趋势强度指标使用

参数说明：
  - fast_period: 快线 EMA 周期，越小越灵敏（默认 12）
  - slow_period: 慢线 EMA 周期，越大越平滑（默认 26）
  - signal_threshold: 信号强度阈值，低于此值不产生信号（默认 0.6）
  - factor_name 示例: ema_cross_fast_12_slow_26
"""

from __future__ import annotations

from decimal import Decimal

from one_quant.core.types import Kline, Market, Signal, Ticker
from one_quant.strategy.contracts import Strategy


def _ema(prev_ema: Decimal, price: Decimal, period: int) -> Decimal:
    """计算单步 EMA。

    公式：EMA_today = price * k + EMA_yesterday * (1 - k)
    其中 k = 2 / (period + 1)

    Args:
        prev_ema: 前一周期 EMA 值
        price: 当前价格
        period: EMA 周期

    Returns:
        当前 EMA 值
    """
    k = Decimal(2) / Decimal(period + 1)
    return price * k + prev_ema * (Decimal(1) - k)


class EMACrossStrategy(Strategy):
    """EMA 交叉策略。

    原理：快线上穿慢线做多，快线下穿慢线做空。
    适用：趋势行情。

    参数：
    - fast_period: 快线周期（默认 12）
    - slow_period: 慢线周期（默认 26）
    - signal_threshold: 信号强度阈值（默认 0.6）

    因子命名：ema_cross_fast_{fast_period}_slow_{slow_period}
    """

    name = "ema_cross"
    enabled = False

    def __init__(
        self,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_threshold: float = 0.6,
    ) -> None:
        if fast_period <= 0 or slow_period <= 0:
            raise ValueError("EMA 周期必须为正整数")
        if fast_period >= slow_period:
            raise ValueError("快线周期必须小于慢线周期")
        if not 0.0 <= signal_threshold <= 1.0:
            raise ValueError("信号强度阈值必须在 [0, 1] 范围内")

        self.fast_period: int = fast_period
        self.slow_period: int = slow_period
        self.signal_threshold: float = signal_threshold

        # 每个 symbol 独立维护状态
        self._prices: dict[str, list[Decimal]] = {}  # 价格缓冲（用于初始化 EMA）
        self._ema_fast: dict[str, Decimal] = {}  # 快线当前值
        self._ema_slow: dict[str, Decimal] = {}  # 慢线当前值
        self._prev_diff: dict[str, Decimal] = {}  # 前一次快慢线差值（用于检测交叉）

    @property
    def factor_name(self) -> str:
        """因子命名：ema_cross_fast_{fast_period}_slow_{slow_period}"""
        return f"ema_cross_fast_{self.fast_period}_slow_{self.slow_period}"

    def _warmup_complete(self, symbol: str) -> bool:
        """检查是否已完成预热（收集了足够的价格数据）。

        Args:
            symbol: 标的符号

        Returns:
            预热是否完成
        """
        return symbol in self._ema_fast and symbol in self._ema_slow

    def _init_ema(self, symbol: str, prices: list[Decimal]) -> None:
        """用 SMA 初始化 EMA。

        当收集到 slow_period 个价格后，用前 fast_period 个价格的 SMA 初始化快线，
        用前 slow_period 个价格的 SMA 初始化慢线。

        Args:
            symbol: 标的符号
            prices: 已收集的价格列表（长度 >= slow_period）
        """
        fast_buf = prices[-self.fast_period :]
        slow_buf = prices[-self.slow_period :]
        self._ema_fast[symbol] = sum(fast_buf) / Decimal(len(fast_buf))
        self._ema_slow[symbol] = sum(slow_buf) / Decimal(len(slow_buf))
        self._prev_diff[symbol] = self._ema_fast[symbol] - self._ema_slow[symbol]

    def _process_price(
        self, symbol: str, price: Decimal, market: Market, timestamp_ns: int
    ) -> list[Signal]:
        """处理单个价格更新，返回信号列表。

        流程：
        1. 数据不足 → 收集到缓冲区，返回空
        2. 刚好够初始化 → 用 SMA 初始化 EMA，返回空
        3. EMA 已初始化 → 更新 EMA，检测交叉，生成信号

        Args:
            symbol: 标的符号
            price: 当前价格
            market: 市场类型
            timestamp_ns: 时间戳

        Returns:
            信号列表
        """
        # 阶段 1：数据不足，收集价格
        if symbol not in self._prices:
            self._prices[symbol] = []

        buf = self._prices[symbol]
        buf.append(price)

        # 阶段 2：数据刚好够初始化 EMA
        if len(buf) == self.slow_period and symbol not in self._ema_fast:
            self._init_ema(symbol, buf)
            return []

        # 数据还不够
        if symbol not in self._ema_fast:
            return []

        # 阶段 3：EMA 已初始化，正常更新
        old_fast = self._ema_fast[symbol]
        old_slow = self._ema_slow[symbol]
        new_fast = _ema(old_fast, price, self.fast_period)
        new_slow = _ema(old_slow, price, self.slow_period)

        self._ema_fast[symbol] = new_fast
        self._ema_slow[symbol] = new_slow

        # 检测交叉
        new_diff = new_fast - new_slow
        prev_diff = self._prev_diff[symbol]
        self._prev_diff[symbol] = new_diff

        signals: list[Signal] = []

        # 信号强度 = |快慢线差值| / 价格，归一化到 [0, 1]
        if price > 0:
            strength_raw = abs(new_diff) / price
        else:
            return []

        # 将比值映射到 [0, 1]：使用 0~2% 的差值范围映射到 0~1
        # 超过 2% 按 1 处理
        strength = float(min(strength_raw / Decimal("0.02"), Decimal(1)))

        if strength < self.signal_threshold:
            return signals

        # 金叉：快线从下方穿越慢线（prev_diff <= 0 且 new_diff > 0）
        if prev_diff <= 0 and new_diff > 0:
            signals.append(
                Signal(
                    symbol=symbol,
                    market=market,
                    side="buy",
                    strength=strength,
                    strategy_name=self.name,
                    reason=(
                        f"EMA金叉：快线({new_fast:.4f})上穿慢线({new_slow:.4f})，"
                        f"差值{new_diff:.4f}，信号强度{strength:.2f}"
                    ),
                    metadata={
                        "factor": self.factor_name,
                        "ema_fast": str(new_fast),
                        "ema_slow": str(new_slow),
                        "diff": str(new_diff),
                    },
                    timestamp_ns=timestamp_ns,
                )
            )

        # 死叉：快线从上方穿越慢线（prev_diff >= 0 且 new_diff < 0）
        elif prev_diff >= 0 and new_diff < 0:
            signals.append(
                Signal(
                    symbol=symbol,
                    market=market,
                    side="sell",
                    strength=strength,
                    strategy_name=self.name,
                    reason=(
                        f"EMA死叉：快线({new_fast:.4f})下穿慢线({new_slow:.4f})，"
                        f"差值{new_diff:.4f}，信号强度{strength:.2f}"
                    ),
                    metadata={
                        "factor": self.factor_name,
                        "ema_fast": str(new_fast),
                        "ema_slow": str(new_slow),
                        "diff": str(new_diff),
                    },
                    timestamp_ns=timestamp_ns,
                )
            )

        return signals

    def on_ticker(self, ticker: Ticker) -> list[Signal]:
        """处理实时行情更新。

        使用 last_price 更新 EMA 并检测交叉。

        Args:
            ticker: 最新行情快照

        Returns:
            信号列表。无信号时返回空列表。
        """
        return self._process_price(
            symbol=ticker.symbol,
            price=ticker.last_price,
            market=ticker.market,
            timestamp_ns=ticker.timestamp_ns,
        )

    def on_kline(self, kline: Kline) -> list[Signal]:
        """处理K线更新。

        使用 close 价格更新 EMA 并检测交叉。

        Args:
            kline: 最新K线数据

        Returns:
            信号列表。无信号时返回空列表。
        """
        return self._process_price(
            symbol=kline.symbol,
            price=kline.close,
            market=kline.market,
            timestamp_ns=kline.timestamp_ns,
        )

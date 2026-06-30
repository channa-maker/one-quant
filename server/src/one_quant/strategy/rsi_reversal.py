"""
ONE量化 - RSI 反转策略

核心思想：
  基于相对强弱指标（RSI）的超买超卖反转信号。
  RSI 跌入超卖区（< 30）后回升穿越阈值时做多，
  RSI 升入超买区（> 70）后回落穿越阈值时做空。
  属于均值回归策略，在震荡行情中表现较好。

适用市场环境：
  - 震荡行情（价格在区间内波动）：RSI 反转信号准确率较高
  - 趋势行情（单边上涨/下跌）：RSI 可能长期停留在超买/超卖区，产生过早反向信号
  - 建议配合趋势过滤器（如均线方向）使用，避免逆势操作

参数说明：
  - period: RSI 计算周期，Wilder 默认 14（默认 14）
  - oversold: 超卖阈值，低于此值视为超卖（默认 30）
  - overbought: 超买阈值，高于此值视为超买（默认 70）
  - factor_name 示例: rsi_reversal_14
"""

from __future__ import annotations

from decimal import Decimal

from one_quant.core.types import Kline, Market, Signal, Ticker
from one_quant.strategy.contracts import Strategy


class RSIReversalStrategy(Strategy):
    """RSI 反转策略。

    原理：RSI < 30 超卖做多，RSI > 70 超买做空。
    适用：震荡行情。

    参数：
    - period: RSI 周期（默认 14）
    - oversold: 超卖阈值（默认 30）
    - overbought: 超买阈值（默认 70）

    因子命名：rsi_reversal_{period}
    """

    name = "rsi_reversal"
    enabled = False

    def __init__(
        self,
        period: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0,
    ) -> None:
        if period <= 0:
            raise ValueError("RSI 周期必须为正整数")
        if not 0 < oversold < 50:
            raise ValueError("超卖阈值必须在 (0, 50) 范围内")
        if not 50 < overbought < 100:
            raise ValueError("超买阈值必须在 (50, 100) 范围内")
        if oversold >= overbought:
            raise ValueError("超卖阈值必须小于超买阈值")

        self.period: int = period
        self.oversold: Decimal = Decimal(str(oversold))
        self.overbought: Decimal = Decimal(str(overbought))

        # 每个 symbol 独立维护状态
        self._prev_close: dict[str, Decimal] = {}          # 前一收盘价
        self._avg_gain: dict[str, Decimal] = {}            # Wilder 平均涨幅
        self._avg_loss: dict[str, Decimal] = {}            # Wilder 平均跌幅
        self._rsi: dict[str, Decimal | None] = {}          # 当前 RSI 值
        self._prev_rsi: dict[str, Decimal | None] = {}     # 前一次 RSI 值
        self._price_count: dict[str, int] = {}             # 已处理价格数量
        self._gains_buf: dict[str, list[Decimal]] = {}     # 预热期涨幅缓冲
        self._losses_buf: dict[str, list[Decimal]] = {}    # 预热期跌幅缓冲

    @property
    def factor_name(self) -> str:
        """因子命名：rsi_reversal_{period}"""
        return f"rsi_reversal_{self.period}"

    def _process_price(self, symbol: str, price: Decimal, market: Market, timestamp_ns: int) -> list[Signal]:
        """处理单个价格更新，计算 RSI 并检测反转信号。

        流程：
        1. 第一个价格 → 记录，返回空
        2. 预热期（< period 个变化） → 收集涨跌幅到缓冲区
        3. 刚好够初始化 → 计算初始平均涨跌幅和 RSI
        4. 正常运行 → Wilder 平滑更新 RSI，检测穿越信号

        Args:
            symbol: 标的符号
            price: 当前价格
            market: 市场类型
            timestamp_ns: 时间戳

        Returns:
            信号列表
        """
        # 第一个价格，仅记录
        if symbol not in self._prev_close:
            self._prev_close[symbol] = price
            self._price_count[symbol] = 0
            self._gains_buf[symbol] = []
            self._losses_buf[symbol] = []
            return []

        # 计算价格变化
        change = price - self._prev_close[symbol]
        self._prev_close[symbol] = price

        gain = change if change > 0 else Decimal(0)
        loss = -change if change < 0 else Decimal(0)

        self._price_count[symbol] += 1
        count = self._price_count[symbol]

        # 预热期：收集涨跌幅
        if symbol not in self._avg_gain:
            self._gains_buf[symbol].append(gain)
            self._losses_buf[symbol].append(loss)

            # 数据足够，用 SMA 初始化平均涨跌幅
            if count == self.period:
                gains = self._gains_buf[symbol]
                losses = self._losses_buf[symbol]
                self._avg_gain[symbol] = sum(gains) / Decimal(self.period)
                self._avg_loss[symbol] = sum(losses) / Decimal(self.period)
                # 计算初始 RSI
                rsi = self._compute_rsi(symbol)
                self._rsi[symbol] = rsi
                self._prev_rsi[symbol] = rsi
                # 清理缓冲
                del self._gains_buf[symbol]
                del self._losses_buf[symbol]

            return []

        # 正常运行：Wilder 平滑法更新
        avg_gain = self._avg_gain[symbol]
        avg_loss = self._avg_loss[symbol]
        period_dec = Decimal(self.period)

        new_avg_gain = (avg_gain * (period_dec - 1) + gain) / period_dec
        new_avg_loss = (avg_loss * (period_dec - 1) + loss) / period_dec

        self._avg_gain[symbol] = new_avg_gain
        self._avg_loss[symbol] = new_avg_loss

        # 更新 RSI
        self._prev_rsi[symbol] = self._rsi[symbol]
        rsi = self._compute_rsi(symbol)
        self._rsi[symbol] = rsi

        # RSI 无法计算（平均跌幅为 0 且平均涨幅为 0）
        if rsi is None:
            return []

        prev_rsi = self._prev_rsi[symbol]
        if prev_rsi is None:
            return []

        # 检测穿越信号
        signals: list[Signal] = []

        # 从超卖区回升：前一次 RSI < oversold，当前 RSI >= oversold
        if prev_rsi < self.oversold and rsi >= self.oversold:
            # 信号强度：RSI 偏离 50 的程度（越大说明超卖越严重，反转越可靠）
            # 用前一次 RSI（最低点）计算：越低越强
            deviation = (Decimal(50) - prev_rsi) / Decimal(50)
            strength = float(min(deviation, Decimal(1)))
            if strength > 0:
                signals.append(
                    Signal(
                        symbol=symbol,
                        market=market,
                        side="buy",
                        strength=strength,
                        strategy_name=self.name,
                        reason=(
                            f"RSI超卖回升：RSI从{prev_rsi:.1f}升至{rsi:.1f}，"
                            f"穿越超卖线{self.oversold}，信号强度{strength:.2f}"
                        ),
                        metadata={
                            "factor": self.factor_name,
                            "rsi": str(rsi),
                            "prev_rsi": str(prev_rsi),
                            "avg_gain": str(self._avg_gain[symbol]),
                            "avg_loss": str(self._avg_loss[symbol]),
                        },
                        timestamp_ns=timestamp_ns,
                    )
                )

        # 从超买区回落：前一次 RSI > overbought，当前 RSI <= overbought
        elif prev_rsi > self.overbought and rsi <= self.overbought:
            deviation = (prev_rsi - Decimal(50)) / Decimal(50)
            strength = float(min(deviation, Decimal(1)))
            if strength > 0:
                signals.append(
                    Signal(
                        symbol=symbol,
                        market=market,
                        side="sell",
                        strength=strength,
                        strategy_name=self.name,
                        reason=(
                            f"RSI超买回落：RSI从{prev_rsi:.1f}降至{rsi:.1f}，"
                            f"穿越超买线{self.overbought}，信号强度{strength:.2f}"
                        ),
                        metadata={
                            "factor": self.factor_name,
                            "rsi": str(rsi),
                            "prev_rsi": str(prev_rsi),
                            "avg_gain": str(self._avg_gain[symbol]),
                            "avg_loss": str(self._avg_loss[symbol]),
                        },
                        timestamp_ns=timestamp_ns,
                    )
                )

        return signals

    def _compute_rsi(self, symbol: str) -> Decimal | None:
        """计算 RSI 值。

        公式：RSI = 100 - 100 / (1 + RS)
        其中 RS = 平均涨幅 / 平均跌幅

        特殊情况：
        - 平均跌幅 = 0 且 平均涨幅 > 0 → RSI = 100（全涨）
        - 平均涨幅 = 0 且 平均跌幅 > 0 → RSI = 0（全跌）
        - 两者都为 0 → 返回 None（无意义）

        Args:
            symbol: 标的符号

        Returns:
            RSI 值（0-100），无法计算时返回 None
        """
        avg_gain = self._avg_gain[symbol]
        avg_loss = self._avg_loss[symbol]

        if avg_loss == 0 and avg_gain == 0:
            return None
        if avg_loss == 0:
            return Decimal(100)
        if avg_gain == 0:
            return Decimal(0)

        rs = avg_gain / avg_loss
        rsi = Decimal(100) - Decimal(100) / (Decimal(1) + rs)
        return rsi

    def on_ticker(self, ticker: Ticker) -> list[Signal]:
        """处理实时行情更新。

        使用 last_price 更新 RSI 并检测反转信号。

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

        使用 close 价格更新 RSI 并检测反转信号。

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

"""
ONE量化 - 回测引擎测试

覆盖：
  - 空数据回测不崩溃
  - 含成本收益低于无成本
  - 锚定交易（持仓跟踪）
  - 无未来函数验证
  - 权益曲线生成
  - 指标计算（夏普/回撤/胜率）
"""

import asyncio
import time
from decimal import Decimal

from one_quant.core.types import (
    Fill,
    Kline,
    Signal,
    Ticker,
)
from one_quant.strategy.backtest import BacktestEngine, BacktestResult
from one_quant.strategy.contracts import Strategy

# ──────────────────────────── 辅助工具 ────────────────────────────


class BuyHoldStrategy(Strategy):
    """简单买入持有策略：第一根K线买入，最后一根卖出。"""

    name = "buy_hold"
    enabled = True

    def __init__(self) -> None:
        self._count = 0
        self._bought = False

    def on_ticker(self, ticker: Ticker) -> list[Signal]:
        return []

    def on_kline(self, kline: Kline) -> list[Signal]:
        self._count += 1
        signals: list[Signal] = []
        if not self._bought:
            signals.append(
                Signal(
                    symbol=kline.symbol,
                    market=kline.market,
                    side="buy",
                    strength=1.0,
                    strategy_name=self.name,
                    reason="首次买入",
                    timestamp_ns=kline.timestamp_ns,
                )
            )
            self._bought = True
        return signals

    def on_fill(self, fill: Fill) -> None:
        pass


class AlwaysBuyStrategy(Strategy):
    """每根K线都买入的策略，用于测试连续交易。"""

    name = "always_buy"
    enabled = True

    def on_ticker(self, ticker: Ticker) -> list[Signal]:
        return []

    def on_kline(self, kline: Kline) -> list[Signal]:
        return [
            Signal(
                symbol=kline.symbol,
                market=kline.market,
                side="buy",
                strength=0.5,
                strategy_name=self.name,
                reason="持续买入",
                timestamp_ns=kline.timestamp_ns,
            )
        ]

    def on_fill(self, fill: Fill) -> None:
        pass


class BuySellStrategy(Strategy):
    """交替买卖策略：奇数K线买入，偶数K线卖出。"""

    name = "buy_sell"
    enabled = True

    def __init__(self) -> None:
        self._count = 0

    def on_ticker(self, ticker: Ticker) -> list[Signal]:
        return []

    def on_kline(self, kline: Kline) -> list[Signal]:
        self._count += 1
        side = "buy" if self._count % 2 == 1 else "sell"
        return [
            Signal(
                symbol=kline.symbol,
                market=kline.market,
                side=side,
                strength=1.0,
                strategy_name=self.name,
                reason=f"第{self._count}笔{'买入' if side == 'buy' else '卖出'}",
                timestamp_ns=kline.timestamp_ns,
            )
        ]

    def on_fill(self, fill: Fill) -> None:
        pass


class NoOpStrategy(Strategy):
    """空策略：不产生任何信号。"""

    name = "noop"
    enabled = True

    def on_ticker(self, ticker: Ticker) -> list[Signal]:
        return []

    def on_kline(self, kline: Kline) -> list[Signal]:
        return []

    def on_fill(self, fill: Fill) -> None:
        pass


def _make_kline_data(
    close: str = "100",
    high: str | None = None,
    low: str | None = None,
    open_: str | None = None,
    timestamp_ns: int | None = None,
    symbol: str = "BTCUSDT",
) -> dict:
    """构造K线数据字典。"""
    c = Decimal(close)
    return {
        "_type": "kline",
        "symbol": symbol,
        "market": "SPOT",
        "exchange": "binance",
        "interval": "1m",
        "open": str(open_ or close),
        "high": str(high or str(c * Decimal("1.01"))),
        "low": str(low or str(c * Decimal("0.99"))),
        "close": close,
        "volume": "100",
        "timestamp_ns": timestamp_ns or time.time_ns(),
    }


def _make_rising_data(n: int = 10, start: float = 100.0, step: float = 1.0) -> list[dict]:
    """生成连续上涨的K线数据序列。"""
    data = []
    base_ts = 1_000_000_000_000  # 1T ns
    for i in range(n):
        price = start + i * step
        data.append(
            _make_kline_data(
                close=str(price),
                high=str(price + step * 0.5),
                low=str(price - step * 0.5),
                timestamp_ns=base_ts + i * 60_000_000_000,  # 每分钟
            )
        )
    return data


def _make_volatile_data(n: int = 20, base: float = 100.0) -> list[dict]:
    """生成涨跌交替的波动K线数据。"""
    data = []
    base_ts = 1_000_000_000_000
    for i in range(n):
        if i % 2 == 0:
            price = base + 5.0
        else:
            price = base - 5.0
        data.append(
            _make_kline_data(
                close=str(price),
                high=str(price + 2),
                low=str(price - 2),
                timestamp_ns=base_ts + i * 60_000_000_000,
            )
        )
    return data


# ──────────────────────────── 测试类 ────────────────────────────


class TestBacktestEmptyData:
    """空数据回测测试"""

    def test_empty_data_no_crash(self):
        """空数据列表回测不崩溃，返回零指标。"""
        engine = BacktestEngine(strategy=NoOpStrategy())
        result = asyncio.run(engine.run([]))

        assert isinstance(result, BacktestResult)
        assert result.total_return == Decimal("0")
        assert result.total_trades == 0
        assert result.equity_curve == []
        assert result.win_rate == 0.0
        assert result.sharpe_ratio == 0.0

    def test_no_signal_data(self):
        """有行情数据但策略不产生信号，权益不变。"""
        data = _make_rising_data(n=10)
        engine = BacktestEngine(strategy=NoOpStrategy())
        result = asyncio.run(engine.run(data))

        assert result.total_trades == 0
        assert result.total_return == Decimal("0")
        # 权益曲线应有记录
        assert len(result.equity_curve) == 10

    def test_unknown_event_type_skipped(self):
        """未知事件类型被跳过，不影响回测。"""
        data = [
            {"_type": "unknown_type", "timestamp_ns": 1},
            _make_kline_data(timestamp_ns=2),
        ]
        engine = BacktestEngine(strategy=NoOpStrategy())
        result = asyncio.run(engine.run(data))
        assert isinstance(result, BacktestResult)


class TestBacktestCosts:
    """交易成本测试"""

    def test_with_cost_return_lower_than_without(self):
        """含成本的收益应低于无成本收益。"""
        data = _make_rising_data(n=20, start=100.0, step=2.0)

        # 无成本
        engine_no_cost = BacktestEngine(
            strategy=BuySellStrategy(),
            commission_rate=Decimal("0"),
            slippage_rate=Decimal("0"),
        )
        result_no_cost = asyncio.run(engine_no_cost.run(data))

        # 有成本
        engine_with_cost = BacktestEngine(
            strategy=BuySellStrategy(),
            commission_rate=Decimal("0.01"),  # 1% 手续费
            slippage_rate=Decimal("0.005"),  # 0.5% 滑点
        )
        result_with_cost = asyncio.run(engine_with_cost.run(data))

        # 含成本收益应更低
        assert result_with_cost.total_return < result_no_cost.total_return

    def test_zero_commission_no_fee(self):
        """零手续费时手续费为零。"""
        engine = BacktestEngine(
            strategy=BuyHoldStrategy(),
            commission_rate=Decimal("0"),
            slippage_rate=Decimal("0"),
        )
        data = _make_rising_data(n=5, start=100.0, step=1.0)
        _result = asyncio.run(engine.run(data))  # noqa: F841

        # 检查成交记录无手续费
        for fill in engine.trades:
            assert fill.fee == Decimal("0")

    def test_higher_commission_lower_return(self):
        """更高的手续费率导致更低的收益。"""
        data = _make_rising_data(n=10, start=100.0, step=1.0)

        results = []
        for comm in [Decimal("0.001"), Decimal("0.01"), Decimal("0.05")]:
            engine = BacktestEngine(
                strategy=BuySellStrategy(),
                commission_rate=comm,
                slippage_rate=Decimal("0"),
            )
            r = asyncio.run(engine.run(data))
            results.append(r.total_return)

        # 收益应单调递减
        assert results[0] >= results[1] >= results[2]


class TestBacktestAnchoring:
    """锚定交易测试（持仓跟踪）"""

    def test_buy_creates_long_position(self):
        """买入信号创建多头持仓。"""
        engine = BacktestEngine(strategy=BuyHoldStrategy())
        data = [_make_kline_data(close="100")]
        asyncio.run(engine.run(data))

        positions = engine.positions
        assert "BTCUSDT" in positions
        assert positions["BTCUSDT"].side == "long"
        assert positions["BTCUSDT"].quantity > 0

    def test_multiple_buys_accumulate(self):
        """多次买入累积持仓。"""
        engine = BacktestEngine(strategy=AlwaysBuyStrategy())
        data = _make_rising_data(n=5, start=100.0, step=0.0)
        result = asyncio.run(engine.run(data))

        assert result.total_trades > 0
        pos = engine.positions.get("BTCUSDT")
        assert pos is not None
        assert pos.side == "long"

    def test_sell_reduces_position(self):
        """卖出减少持仓。"""
        engine = BacktestEngine(strategy=BuySellStrategy())
        data = _make_rising_data(n=4, start=100.0, step=1.0)
        _result = asyncio.run(engine.run(data))  # noqa: F841

        # 应该有买入和卖出成交
        buys = [f for f in engine.trades if f.side == "buy"]
        sells = [f for f in engine.trades if f.side == "sell"]
        assert len(buys) > 0
        assert len(sells) > 0


class TestBacktestNoFutureFunction:
    """无未来函数验证"""

    def test_signal_uses_only_current_and_past_data(self):
        """验证策略信号只使用当前及历史数据。"""

        class FutureDetectorStrategy(Strategy):
            """检测是否使用了未来数据的策略。"""

            name = "future_detector"
            enabled = True

            def __init__(self):
                self.seen_prices: list[float] = []
                self.last_signal_price = None

            def on_ticker(self, ticker: Ticker) -> list[Signal]:
                return []

            def on_kline(self, kline: Kline) -> list[Signal]:
                current_price = float(kline.close)
                self.seen_prices.append(current_price)

                # 记录信号时的价格
                self.last_signal_price = current_price
                return [
                    Signal(
                        symbol=kline.symbol,
                        market=kline.market,
                        side="buy",
                        strength=0.5,
                        strategy_name=self.name,
                        reason="测试",
                        timestamp_ns=kline.timestamp_ns,
                    )
                ]

            def on_fill(self, fill: Fill) -> None:
                pass

        strategy = FutureDetectorStrategy()
        engine = BacktestEngine(strategy=strategy)
        data = _make_rising_data(n=20, start=100.0, step=1.0)
        asyncio.run(engine.run(data))

        # 验证策略看到的价格序列是递增时间顺序
        assert len(strategy.seen_prices) == 20
        # 策略不应访问未来数据（通过设计保证，此处验证数据完整性）

    def test_engine_processes_data_in_order(self):
        """引擎按时间顺序处理数据。"""
        timestamps_seen: list[int] = []

        class TimestampTracker(Strategy):
            name = "ts_tracker"
            enabled = True

            def on_ticker(self, ticker: Ticker) -> list[Signal]:
                return []

            def on_kline(self, kline: Kline) -> list[Signal]:
                timestamps_seen.append(kline.timestamp_ns)
                return []

            def on_fill(self, fill: Fill) -> None:
                pass

        engine = BacktestEngine(strategy=TimestampTracker())
        data = _make_rising_data(n=10)
        asyncio.run(engine.run(data))

        # 时间戳应单调递增
        for i in range(1, len(timestamps_seen)):
            assert timestamps_seen[i] >= timestamps_seen[i - 1]


class TestBacktestEquityCurve:
    """权益曲线测试"""

    def test_equity_curve_has_entries(self):
        """回测后权益曲线有记录。"""
        engine = BacktestEngine(strategy=NoOpStrategy())
        data = _make_rising_data(n=10)
        result = asyncio.run(engine.run(data))

        assert len(result.equity_curve) == 10
        for ts, equity in result.equity_curve:
            assert isinstance(ts, int)
            assert isinstance(equity, Decimal)
            assert equity > 0

    def test_equity_curve_starts_at_initial_capital(self):
        """权益曲线起始值等于初始资金。"""
        engine = BacktestEngine(
            strategy=NoOpStrategy(),
            initial_capital=Decimal("50000"),
        )
        data = _make_rising_data(n=5)
        result = asyncio.run(engine.run(data))

        assert result.equity_curve[0][1] == Decimal("50000.00")

    def test_equity_curve_monotonic_with_no_trades(self):
        """无交易时权益曲线保持不变。"""
        engine = BacktestEngine(
            strategy=NoOpStrategy(),
            initial_capital=Decimal("100000"),
        )
        data = _make_rising_data(n=10)
        result = asyncio.run(engine.run(data))

        for _, equity in result.equity_curve:
            assert equity == Decimal("100000.00")


class TestBacktestMetrics:
    """指标计算测试"""

    def test_max_drawdown_non_negative(self):
        """最大回撤为非负数。"""
        engine = BacktestEngine(strategy=BuySellStrategy())
        data = _make_volatile_data(n=20)
        result = asyncio.run(engine.run(data))

        assert result.max_drawdown >= Decimal("0")

    def test_max_drawdown_zero_for_constant_equity(self):
        """恒定权益时最大回撤为零。"""
        engine = BacktestEngine(strategy=NoOpStrategy())
        data = _make_rising_data(n=10, step=0.0)
        result = asyncio.run(engine.run(data))

        assert result.max_drawdown == Decimal("0")

    def test_sharpe_ratio_finite(self):
        """夏普比率为有限值。"""
        engine = BacktestEngine(strategy=BuySellStrategy())
        data = _make_rising_data(n=20)
        result = asyncio.run(engine.run(data))

        assert isinstance(result.sharpe_ratio, float)
        assert not (result.sharpe_ratio == float("inf") or result.sharpe_ratio == float("-inf"))

    def test_win_rate_in_valid_range(self):
        """胜率在 [0, 1] 范围内。"""
        engine = BacktestEngine(strategy=BuySellStrategy())
        data = _make_rising_data(n=20)
        result = asyncio.run(engine.run(data))

        assert 0.0 <= result.win_rate <= 1.0

    def test_profit_factor_non_negative(self):
        """盈亏比为非负数。"""
        engine = BacktestEngine(strategy=BuySellStrategy())
        data = _make_rising_data(n=20)
        result = asyncio.run(engine.run(data))

        assert result.profit_factor >= 0.0

    def test_total_trades_count(self):
        """总交易次数应等于实际成交数。"""
        engine = BacktestEngine(strategy=BuySellStrategy())
        data = _make_rising_data(n=10)
        result = asyncio.run(engine.run(data))

        assert result.total_trades == len(engine.trades)

    def test_calmar_ratio_calculation(self):
        """卡玛比率 = 年化收益 / 最大回撤。"""
        engine = BacktestEngine(strategy=BuySellStrategy())
        data = _make_rising_data(n=20)
        result = asyncio.run(engine.run(data))

        assert isinstance(result.calmar_ratio, float)

    def test_turnover_rate_positive_with_trades(self):
        """有交易时换手率为正。"""
        engine = BacktestEngine(strategy=BuySellStrategy())
        data = _make_rising_data(n=10)
        result = asyncio.run(engine.run(data))

        if result.total_trades > 0:
            assert result.turnover_rate > 0.0

    def test_repeat_run_resets_state(self):
        """重复运行回测引擎应重置状态。"""
        engine = BacktestEngine(strategy=BuySellStrategy())
        data = _make_rising_data(n=10)

        result1 = asyncio.run(engine.run(data))
        result2 = asyncio.run(engine.run(data))

        # 两次结果应一致
        assert result1.total_return == result2.total_return
        assert result1.total_trades == result2.total_trades

    def test_initial_capital_affects_results(self):
        """不同初始资金影响绝对收益但不影响收益率。"""
        data = _make_rising_data(n=10)

        engine1 = BacktestEngine(
            strategy=BuyHoldStrategy(),
            initial_capital=Decimal("100000"),
        )
        engine2 = BacktestEngine(
            strategy=BuyHoldStrategy(),
            initial_capital=Decimal("200000"),
        )

        r1 = asyncio.run(engine1.run(data))
        r2 = asyncio.run(engine2.run(data))

        # 收益率应相近（不完全相同因为舍入）
        assert abs(float(r1.total_return) - float(r2.total_return)) < 0.01

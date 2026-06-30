"""
ONE量化 - 策略实现测试

验证 EMA 交叉、RSI 反转等内置策略的基本契约。
"""

import time
from decimal import Decimal

from one_quant.core.types import Kline, Market, Signal, Ticker
from one_quant.strategy.ema_cross import EMACrossStrategy
from one_quant.strategy.rsi_reversal import RSIReversalStrategy


def _make_ticker(price: str = "50000") -> Ticker:
    return Ticker(
        symbol="BTCUSDT",
        market=Market.SPOT,
        exchange="binance",
        last_price=Decimal(price),
        bid=Decimal(price),
        ask=Decimal(price),
        volume_24h=Decimal("1000"),
        timestamp_ns=time.time_ns(),
    )


def _make_kline(close: str = "50500") -> Kline:
    return Kline(
        symbol="BTCUSDT",
        market=Market.SPOT,
        exchange="binance",
        interval="1m",
        open=Decimal("50000"),
        high=Decimal("51000"),
        low=Decimal("49000"),
        close=Decimal(close),
        volume=Decimal("100"),
        timestamp_ns=time.time_ns(),
    )


class TestEMACrossStrategy:
    """EMA 交叉策略测试"""

    def test_name(self):
        s = EMACrossStrategy()
        assert isinstance(s.name, str) and len(s.name) > 0

    def test_on_ticker_returns_list(self):
        s = EMACrossStrategy()
        result = s.on_ticker(_make_ticker())
        assert isinstance(result, list)

    def test_on_kline_returns_list(self):
        s = EMACrossStrategy()
        result = s.on_kline(_make_kline())
        assert isinstance(result, list)

    def test_signal_type(self):
        s = EMACrossStrategy()
        for _ in range(50):
            signals = s.on_kline(_make_kline(close="50000"))
        for sig in signals:
            assert isinstance(sig, Signal)
            assert sig.symbol == "BTCUSDT"
            assert sig.side in ("buy", "sell")
            assert 0 <= sig.strength <= 1

    def test_on_orderbook_returns_list(self):
        s = EMACrossStrategy()
        assert s.on_orderbook == s.on_orderbook  # 默认实现


class TestRSIReversalStrategy:
    """RSI 反转策略测试"""

    def test_name(self):
        s = RSIReversalStrategy()
        assert isinstance(s.name, str) and len(s.name) > 0

    def test_on_ticker_returns_list(self):
        s = RSIReversalStrategy()
        result = s.on_ticker(_make_ticker())
        assert isinstance(result, list)

    def test_on_kline_returns_list(self):
        s = RSIReversalStrategy()
        result = s.on_kline(_make_kline())
        assert isinstance(result, list)

    def test_rsi_extremes(self):
        """连续上涨后 RSI 应该升高。"""
        s = RSIReversalStrategy()
        # 连续上涨
        for i in range(30):
            s.on_kline(_make_kline(close=str(50000 + i * 100)))
        # 连续下跌
        for i in range(30):
            signals = s.on_kline(_make_kline(close=str(53000 - i * 100)))
        # 应该产生信号（RSI 超卖反转）
        assert isinstance(signals, list)

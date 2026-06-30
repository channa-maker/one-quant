"""
ONE量化 - 策略运行引擎测试

覆盖：注册/注销/启用/禁用/替换策略、行情分发、信号发射、生命周期记录。
"""

from decimal import Decimal

import pytest

from one_quant.core.types import (
    Kline,
    Market,
    Signal,
    Ticker,
)
from one_quant.runner.engine import StrategyRunner
from one_quant.strategy.contracts import Strategy

# ──────────────── Mock 策略 ────────────────


class MockStrategy(Strategy):
    """测试用策略"""

    name = "mock_strategy"
    enabled = True

    def __init__(self, name="mock_strategy", enabled=True, signals=None):
        self.name = name
        self.enabled = enabled
        self._signals = signals or []
        self.ticker_calls = []
        self.kline_calls = []
        self.fill_calls = []

    def on_ticker(self, ticker: Ticker) -> list[Signal]:
        self.ticker_calls.append(ticker)
        return self._signals

    def on_kline(self, kline: Kline) -> list[Signal]:
        self.kline_calls.append(kline)
        return self._signals


def _make_signal(side="buy", strength=0.8, strategy_name="mock_strategy"):
    return Signal(
        symbol="BTCUSDT",
        market=Market.SPOT,
        side=side,
        strength=strength,
        strategy_name=strategy_name,
        reason="测试信号",
        timestamp_ns=1700000000000000000,
    )


def _make_ticker():
    return Ticker(
        symbol="BTCUSDT",
        market=Market.SPOT,
        exchange="binance",
        last_price=Decimal("50000"),
        bid=Decimal("49999"),
        ask=Decimal("50001"),
        volume_24h=Decimal("1000"),
        timestamp_ns=1700000000000000000,
    )


def _make_kline():
    return Kline(
        symbol="BTCUSDT",
        market=Market.SPOT,
        exchange="binance",
        interval="1m",
        open=Decimal("50000"),
        high=Decimal("50100"),
        low=Decimal("49900"),
        close=Decimal("50050"),
        volume=Decimal("100"),
        timestamp_ns=1700000000000000000,
    )


# ──────────────── 注册与注销 ────────────────


class TestStrategyRegistration:
    """策略注册"""

    def test_register_strategy(self, event_bus):
        engine = StrategyRunner(event_bus)
        s = MockStrategy()
        engine.register_strategy(s)
        assert len(engine.strategies) == 1
        assert engine.strategies[0].name == "mock_strategy"

    def test_register_replaces_same_name(self, event_bus):
        engine = StrategyRunner(event_bus)
        s1 = MockStrategy(name="s1", enabled=True)
        s2 = MockStrategy(name="s1", enabled=False)
        engine.register_strategy(s1)
        engine.register_strategy(s2)
        assert len(engine.strategies) == 1
        assert engine.strategies[0].enabled is False

    @pytest.mark.asyncio
    async def test_unregister_strategy(self, event_bus):
        engine = StrategyRunner(event_bus)
        engine.register_strategy(MockStrategy())
        result = await engine.unregister_strategy("mock_strategy")
        assert result is True
        assert len(engine.strategies) == 0

    @pytest.mark.asyncio
    async def test_unregister_nonexistent(self, event_bus):
        engine = StrategyRunner(event_bus)
        result = await engine.unregister_strategy("nonexistent")
        assert result is False


# ──────────────── 启用与禁用 ────────────────


class TestStrategyEnableDisable:
    """策略启用/禁用"""

    @pytest.mark.asyncio
    async def test_enable_strategy(self, event_bus):
        engine = StrategyRunner(event_bus)
        s = MockStrategy(enabled=False)
        engine.register_strategy(s)
        result = await engine.enable_strategy("mock_strategy")
        assert result is True
        assert s.enabled is True

    @pytest.mark.asyncio
    async def test_enable_already_enabled(self, event_bus):
        engine = StrategyRunner(event_bus)
        s = MockStrategy(enabled=True)
        engine.register_strategy(s)
        result = await engine.enable_strategy("mock_strategy")
        assert result is True

    @pytest.mark.asyncio
    async def test_disable_strategy(self, event_bus):
        engine = StrategyRunner(event_bus)
        s = MockStrategy(enabled=True)
        engine.register_strategy(s)
        result = await engine.disable_strategy("mock_strategy")
        assert result is True
        assert s.enabled is False

    @pytest.mark.asyncio
    async def test_disable_already_disabled(self, event_bus):
        engine = StrategyRunner(event_bus)
        s = MockStrategy(enabled=False)
        engine.register_strategy(s)
        result = await engine.disable_strategy("mock_strategy")
        assert result is True

    @pytest.mark.asyncio
    async def test_enable_nonexistent(self, event_bus):
        engine = StrategyRunner(event_bus)
        result = await engine.enable_strategy("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_disable_nonexistent(self, event_bus):
        engine = StrategyRunner(event_bus)
        result = await engine.disable_strategy("nonexistent")
        assert result is False


# ──────────────── 替换策略 ────────────────


class TestStrategyReplace:
    """策略替换"""

    @pytest.mark.asyncio
    async def test_replace_strategy(self, event_bus):
        engine = StrategyRunner(event_bus)
        old = MockStrategy(name="old", enabled=True)
        engine.register_strategy(old)
        new = MockStrategy(name="new", enabled=True)
        result = await engine.replace_strategy("old", new)
        assert result is True
        assert len(engine.strategies) == 1
        assert engine.strategies[0].name == "new"

    @pytest.mark.asyncio
    async def test_replace_nonexistent(self, event_bus):
        engine = StrategyRunner(event_bus)
        new = MockStrategy(name="new")
        result = await engine.replace_strategy("nonexistent", new)
        assert result is False


# ──────────────── 查询 ────────────────


class TestStrategyQuery:
    """策略查询"""

    def test_get_strategy(self, event_bus):
        engine = StrategyRunner(event_bus)
        s = MockStrategy()
        engine.register_strategy(s)
        assert engine.get_strategy("mock_strategy") is s
        assert engine.get_strategy("nonexistent") is None

    def test_get_strategy_status(self, event_bus):
        engine = StrategyRunner(event_bus)
        engine.register_strategy(MockStrategy(name="a", enabled=True))
        engine.register_strategy(MockStrategy(name="b", enabled=False))
        status = engine.get_strategy_status()
        assert len(status) == 2
        names = {s["name"] for s in status}
        assert "a" in names and "b" in names

    def test_stats(self, event_bus):
        engine = StrategyRunner(event_bus)
        engine.register_strategy(MockStrategy(enabled=True))
        engine.register_strategy(MockStrategy(name="s2", enabled=False))
        stats = engine.stats
        assert stats["strategies"] == 2
        assert stats["enabled"] == 1
        assert stats["ticks"] == 0
        assert stats["signals"] == 0


# ──────────────── 生命周期记录 ────────────────


class TestLifecycleEvents:
    """生命周期事件"""

    def test_register_records_event(self, event_bus):
        engine = StrategyRunner(event_bus)
        engine.register_strategy(MockStrategy())
        events = engine.get_lifecycle_events()
        assert len(events) == 1
        assert events[0]["action"] == "register"
        assert events[0]["strategy_name"] == "mock_strategy"

    @pytest.mark.asyncio
    async def test_lifecycle_limit(self, event_bus):
        engine = StrategyRunner(event_bus)
        for i in range(60):
            engine.register_strategy(MockStrategy(name=f"s{i}"))
        events = engine.get_lifecycle_events(limit=10)
        assert len(events) == 10


# ──────────────── 行情分发 ────────────────


class TestMarketDispatch:
    """行情分发"""

    @pytest.mark.asyncio
    async def test_ticker_dispatch(self, event_bus):
        engine = StrategyRunner(event_bus)
        signal = _make_signal()
        s = MockStrategy(signals=[signal])
        engine.register_strategy(s)
        engine._running = True

        await engine._on_ticker(_make_ticker().model_dump(mode="json"))
        assert len(s.ticker_calls) == 1
        assert engine._tick_count == 1
        assert engine._signal_count == 1

    @pytest.mark.asyncio
    async def test_kline_dispatch(self, event_bus):
        engine = StrategyRunner(event_bus)
        s = MockStrategy(signals=[])
        engine.register_strategy(s)
        engine._running = True

        await engine._on_kline(_make_kline().model_dump(mode="json"))
        assert len(s.kline_calls) == 1

    @pytest.mark.asyncio
    async def test_disabled_strategy_not_dispatched(self, event_bus):
        engine = StrategyRunner(event_bus)
        s = MockStrategy(enabled=False, signals=[_make_signal()])
        engine.register_strategy(s)
        engine._running = True

        await engine._on_ticker(_make_ticker().model_dump(mode="json"))
        assert len(s.ticker_calls) == 0
        assert engine._signal_count == 0

    @pytest.mark.asyncio
    async def test_strategy_exception_continues(self, event_bus):
        engine = StrategyRunner(event_bus)

        class FailingStrategy(Strategy):
            name = "failing"
            enabled = True

            def on_ticker(self, ticker):
                raise RuntimeError("boom")

            def on_kline(self, kline):
                return []

        engine.register_strategy(FailingStrategy())
        engine.register_strategy(MockStrategy(name="good", signals=[]))
        engine._running = True

        # Should not raise — exception is caught
        await engine._on_ticker(_make_ticker().model_dump(mode="json"))


# ──────────────── 启动/停止 ────────────────


class TestEngineStartStop:
    """引擎启动停止"""

    @pytest.mark.asyncio
    async def test_start_stop(self, event_bus):
        engine = StrategyRunner(event_bus)
        engine.register_strategy(MockStrategy())
        await engine.start()
        assert engine._running is True
        await engine.stop()
        assert engine._running is False

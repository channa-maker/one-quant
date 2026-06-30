"""
ONE量化 - 策略运行引擎测试

验证策略注册、信号分发。
"""

import asyncio
import time

import pytest

from one_quant.core.types import Kline, Signal, Ticker
from one_quant.infra.event_bus import InMemoryEventBus
from one_quant.runner.engine import StrategyRunner
from one_quant.strategy.contracts import Strategy


class DummyStrategy(Strategy):
    """测试策略：每次收到 ticker 返回一个买入信号。"""

    name = "dummy_test"
    enabled = True

    def on_ticker(self, ticker: Ticker) -> list[Signal]:
        return [
            Signal(
                symbol=ticker.symbol,
                market=ticker.market,
                side="buy",
                strength=0.5,
                strategy_name=self.name,
                reason="测试信号",
                timestamp_ns=time.time_ns(),
            )
        ]

    def on_kline(self, kline: Kline) -> list[Signal]:
        return []


@pytest.mark.asyncio
async def test_register_and_start() -> None:
    """测试策略注册和启动。"""
    bus = InMemoryEventBus()
    runner = StrategyRunner(bus)

    strategy = DummyStrategy()
    runner.register_strategy(strategy)
    await bus.start()
    await runner.start()

    assert runner.stats["strategies"] == 1
    assert runner.stats["enabled"] == 1

    await runner.stop()
    await bus.stop()


@pytest.mark.asyncio
async def test_signal_emission() -> None:
    """测试信号产生和收集。"""
    bus = InMemoryEventBus()
    runner = StrategyRunner(bus)
    received_signals: list[dict] = []

    async def signal_handler(data: dict) -> None:
        received_signals.append(data)

    bus.subscribe("strategy.signal", signal_handler)

    strategy = DummyStrategy()
    runner.register_strategy(strategy)
    await bus.start()
    await runner.start()

    # 发布行情
    await bus.publish(
        "market.ticker",
        {
            "symbol": "BTCUSDT",
            "market": "SPOT",
            "exchange": "binance",
            "last_price": "50000",
            "bid": "49999",
            "ask": "50001",
            "volume_24h": "1000",
            "timestamp_ns": time.time_ns(),
        },
    )

    await asyncio.sleep(0.2)

    assert len(received_signals) == 1
    assert received_signals[0]["strategy_name"] == "dummy_test"
    assert received_signals[0]["side"] == "buy"

    await runner.stop()
    await bus.stop()

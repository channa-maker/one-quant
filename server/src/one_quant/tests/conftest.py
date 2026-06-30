"""pytest 公共 fixture"""

import pytest

from one_quant.infra.event_bus import InMemoryEventBus


@pytest.fixture
def event_bus():
    """提供内存事件总线实例。"""
    return InMemoryEventBus()


@pytest.fixture
def sample_ticker():
    """提供示例 Ticker 数据。"""
    from decimal import Decimal

    from one_quant.core.types import Market, Ticker

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


@pytest.fixture
def sample_kline():
    """提供示例 Kline 数据。"""
    from decimal import Decimal

    from one_quant.core.types import Kline, Market

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

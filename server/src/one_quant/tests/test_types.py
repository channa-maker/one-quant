"""核心领域类型单元测试"""

from __future__ import annotations

from decimal import Decimal

import pytest

from one_quant.core.types import (
    Kline,
    Market,
    Order,
    OrderBook,
    OrderBookLevel,
    Signal,
    Ticker,
    Trade,
)


class TestTicker:
    def test_create(self) -> None:
        ticker = Ticker(
            symbol="BTC/USDT",
            market=Market.SPOT,
            exchange="binance",
            last_price=Decimal("42000.50"),
            bid=Decimal("42000.00"),
            ask=Decimal("42001.00"),
            volume_24h=Decimal("1234.56"),
            timestamp_ns=1700000000000000000,
        )
        assert ticker.symbol == "BTC/USDT"
        assert ticker.last_price == Decimal("42000.50")

    def test_frozen(self) -> None:
        ticker = Ticker(
            symbol="ETH/USDT",
            market=Market.SPOT,
            exchange="okx",
            last_price=Decimal("3000"),
            bid=Decimal("2999"),
            ask=Decimal("3001"),
            volume_24h=Decimal("5000"),
            timestamp_ns=1700000000000000000,
        )
        with pytest.raises(Exception):
            ticker.symbol = "BTC/USDT"  # type: ignore

    def test_json_serialization(self) -> None:
        ticker = Ticker(
            symbol="BTC/USDT",
            market=Market.SPOT,
            exchange="binance",
            last_price=Decimal("42000.50"),
            bid=Decimal("42000.00"),
            ask=Decimal("42001.00"),
            volume_24h=Decimal("1234.56"),
            timestamp_ns=1700000000000000000,
        )
        data = ticker.model_dump(mode="json")
        assert isinstance(data["last_price"], str)
        assert data["last_price"] == "42000.50"


class TestKline:
    def test_create(self) -> None:
        kline = Kline(
            symbol="BTC/USDT",
            market=Market.SPOT,
            exchange="binance",
            interval="1m",
            open=Decimal("42000"),
            high=Decimal("42100"),
            low=Decimal("41900"),
            close=Decimal("42050"),
            volume=Decimal("100"),
            timestamp_ns=1700000000000000000,
        )
        assert kline.interval == "1m"
        assert kline.high > kline.low


class TestSignal:
    def test_create(self) -> None:
        signal = Signal(
            symbol="BTC/USDT",
            market=Market.SPOT,
            side="buy",
            strength=0.85,
            strategy_name="ema_cross",
            reason="EMA12 上穿 EMA26，金叉信号",
            timestamp_ns=1700000000000000000,
        )
        assert signal.strength == 0.85
        assert "金叉" in signal.reason


class TestOrderBook:
    def test_create(self) -> None:
        ob = OrderBook(
            symbol="BTC/USDT",
            exchange="binance",
            bids=[
                OrderBookLevel(price=Decimal("42000"), quantity=Decimal("1.5")),
                OrderBookLevel(price=Decimal("41999"), quantity=Decimal("2.0")),
            ],
            asks=[
                OrderBookLevel(price=Decimal("42001"), quantity=Decimal("1.0")),
                OrderBookLevel(price=Decimal("42002"), quantity=Decimal("3.0")),
            ],
            timestamp_ns=1700000000000000000,
        )
        assert len(ob.bids) == 2
        assert len(ob.asks) == 2


class TestOrder:
    def test_create(self) -> None:
        order = Order(
            client_order_id="uuid-1234",
            symbol="BTC/USDT",
            market=Market.SPOT,
            side="buy",
            order_type="limit",
            quantity=Decimal("0.1"),
            price=Decimal("42000"),
            stop_price=None,
            status="pending",
            exchange="binance",
            timestamp_ns=1700000000000000000,
        )
        assert order.status == "pending"
        assert order.order_type == "limit"

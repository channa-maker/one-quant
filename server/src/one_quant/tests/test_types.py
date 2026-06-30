"""
ONE量化 - 核心类型测试

验证所有领域类型的创建、不可变性、序列化。
"""

import time
from datetime import date
from decimal import Decimal

import pytest

from one_quant.core.types import (
    Instrument,
    InstrumentType,
    Kline,
    Market,
    OptionQuote,
    Order,
    PositionState,
    Signal,
    Ticker,
)


class TestTicker:
    """Ticker 测试"""

    def test_create(self) -> None:
        """测试创建 Ticker。"""
        t = Ticker(
            symbol="BTC/USDT",
            market=Market.SPOT,
            exchange="binance",
            last_price=Decimal("50000"),
            bid=Decimal("49999"),
            ask=Decimal("50001"),
            volume_24h=Decimal("1000"),
            timestamp_ns=time.time_ns(),
        )
        assert t.symbol == "BTC/USDT"
        assert t.market == Market.SPOT
        assert t.last_price == Decimal("50000")

    def test_frozen(self) -> None:
        """测试不可变性。"""
        t = Ticker(
            symbol="BTC/USDT",
            market=Market.SPOT,
            exchange="binance",
            last_price=Decimal("50000"),
            bid=Decimal("49999"),
            ask=Decimal("50001"),
            volume_24h=Decimal("1000"),
            timestamp_ns=time.time_ns(),
        )
        with pytest.raises(Exception):
            t.symbol = "ETH/USDT"  # type: ignore

    def test_model_dump(self) -> None:
        """测试序列化。"""
        t = Ticker(
            symbol="BTC/USDT",
            market=Market.SPOT,
            exchange="binance",
            last_price=Decimal("50000"),
            bid=Decimal("49999"),
            ask=Decimal("50001"),
            volume_24h=Decimal("1000"),
            timestamp_ns=time.time_ns(),
        )
        data = t.model_dump(mode="json")
        assert data["symbol"] == "BTC/USDT"
        assert isinstance(data["last_price"], str)  # Decimal → str


class TestKline:
    """Kline 测试"""

    def test_create(self) -> None:
        k = Kline(
            symbol="BTC/USDT",
            market=Market.SPOT,
            exchange="binance",
            interval="1m",
            open=Decimal("1"),
            high=Decimal("2"),
            low=Decimal("0.5"),
            close=Decimal("1.5"),
            volume=Decimal("100"),
            timestamp_ns=time.time_ns(),
        )
        assert k.interval == "1m"
        assert k.high == Decimal("2")


class TestSignal:
    """Signal 测试"""

    def test_create(self) -> None:
        s = Signal(
            symbol="BTC/USDT",
            market=Market.SPOT,
            side="buy",
            strength=0.8,
            strategy_name="test",
            reason="测试信号",
            timestamp_ns=time.time_ns(),
        )
        assert s.strength == 0.8
        assert s.reason == "测试信号"

    def test_metadata_default(self) -> None:
        s = Signal(
            symbol="BTC/USDT",
            market=Market.SPOT,
            side="buy",
            strength=0.8,
            strategy_name="test",
            reason="测试",
            timestamp_ns=time.time_ns(),
        )
        assert s.metadata == {}


class TestOrder:
    """Order 测试"""

    def test_create(self) -> None:
        o = Order(
            client_order_id="uuid-123",
            symbol="BTC/USDT",
            market=Market.SPOT,
            side="buy",
            order_type="limit",
            quantity=Decimal("0.1"),
            price=Decimal("50000"),
            stop_price=None,
            status="pending",
            exchange="binance",
            timestamp_ns=time.time_ns(),
        )
        assert o.client_order_id == "uuid-123"
        assert o.price == Decimal("50000")
        assert o.stop_price is None


class TestPositionState:
    """PositionState 测试"""

    def test_create(self) -> None:
        p = PositionState(
            symbol="BTC/USDT",
            market=Market.SPOT,
            side="long",
            quantity=Decimal("1"),
            entry_price=Decimal("50000"),
            unrealized_pnl=Decimal("0"),
            realized_pnl=Decimal("0"),
            timestamp_ns=time.time_ns(),
        )
        assert p.side == "long"


class TestInstrument:
    """Instrument 测试"""

    def test_create(self) -> None:
        inst = Instrument(
            internal_id="binance-btc-usdt",
            symbol="BTCUSDT",
            market=Market.SPOT,
            instrument_type=InstrumentType.PERPETUAL,
            exchange="binance",
            base_currency="BTC",
            quote_currency="USDT",
            tick_size=Decimal("0.01"),
            lot_size=Decimal("0.001"),
        )
        assert inst.is_active is True
        assert inst.contract_multiplier == Decimal("1")


class TestOptionQuote:
    """OptionQuote 测试"""

    def test_create(self) -> None:
        q = OptionQuote(
            symbol="BTC-30JUN-C50000",
            underlying="BTC",
            strike=Decimal("50000"),
            expiry=date(2026, 6, 30),
            option_type="call",
            bid=Decimal("100"),
            ask=Decimal("110"),
            iv=Decimal("0.5"),
            delta=Decimal("0.6"),
            gamma=Decimal("0.01"),
            theta=Decimal("-50"),
            vega=Decimal("200"),
            open_interest=Decimal("1000"),
            timestamp_ns=time.time_ns(),
        )
        assert q.option_type == "call"
        assert q.strike == Decimal("50000")


class TestMarketEnum:
    """Market 枚举测试"""

    def test_values(self) -> None:
        assert Market.SPOT == "SPOT"
        assert Market.FUTURES == "FUTURES"
        assert Market.OPTION == "OPTION"
        assert Market.STOCK == "STOCK"

    def test_str(self) -> None:
        assert str(Market.SPOT) == "SPOT"

"""测试：领域类型"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from one_quant.core.types import (
    Fill,
    Instrument,
    InstrumentType,
    Kline,
    Market,
    OptionQuote,
    Order,
    OrderBook,
    OrderBookLevel,
    PositionState,
    Signal,
    Ticker,
    Trade,
)


class TestMarket:
    def test_market_values(self) -> None:
        assert Market.SPOT == "spot"
        assert Market.FUTURES == "futures"
        assert Market.OPTION == "option"
        assert Market.STOCK == "stock"


class TestTicker:
    def test_create_ticker(self) -> None:
        ticker = Ticker(
            symbol="BTCUSDT",
            market=Market.SPOT,
            exchange="binance",
            last_price=Decimal("50000.00"),
            bid=Decimal("49999.00"),
            ask=Decimal("50001.00"),
            volume_24h=Decimal("1234.56"),
            timestamp_ns=1700000000000000000,
        )
        assert ticker.symbol == "BTCUSDT"
        assert ticker.market == Market.SPOT
        assert ticker.last_price == Decimal("50000.00")

    def test_ticker_frozen(self) -> None:
        ticker = Ticker(
            symbol="BTCUSDT",
            market=Market.SPOT,
            exchange="binance",
            last_price=Decimal("50000"),
            bid=Decimal("49999"),
            ask=Decimal("50001"),
            volume_24h=Decimal("1000"),
            timestamp_ns=1700000000000000000,
        )
        with pytest.raises(ValidationError):
            ticker.symbol = "ETHUSDT"  # type: ignore[misc]


class TestKline:
    def test_create_kline(self) -> None:
        kline = Kline(
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
        assert kline.interval == "1m"
        assert kline.high > kline.low


class TestTrade:
    def test_create_trade(self) -> None:
        trade = Trade(
            symbol="BTCUSDT",
            exchange="binance",
            price=Decimal("50000"),
            quantity=Decimal("0.5"),
            side="buy",
            trade_id="12345",
            timestamp_ns=1700000000000000000,
        )
        assert trade.side == "buy"


class TestOrderBook:
    def test_create_orderbook(self) -> None:
        ob = OrderBook(
            symbol="BTCUSDT",
            exchange="binance",
            bids=[OrderBookLevel(price=Decimal("49999"), quantity=Decimal("1.0"))],
            asks=[OrderBookLevel(price=Decimal("50001"), quantity=Decimal("2.0"))],
            timestamp_ns=1700000000000000000,
        )
        assert len(ob.bids) == 1
        assert len(ob.asks) == 1


class TestSignal:
    def test_create_signal(self) -> None:
        signal = Signal(
            symbol="BTCUSDT",
            market=Market.SPOT,
            side="buy",
            strength=0.85,
            strategy_name="ema_cross",
            reason="EMA12 上穿 EMA26",
            timestamp_ns=1700000000000000000,
        )
        assert signal.strength == 0.85
        assert signal.reason == "EMA12 上穿 EMA26"


class TestOrder:
    def test_create_order(self) -> None:
        order = Order(
            client_order_id="uuid-1234",
            symbol="BTCUSDT",
            market=Market.SPOT,
            side="buy",
            order_type="limit",
            quantity=Decimal("1.0"),
            price=Decimal("50000"),
            stop_price=None,
            status="pending",
            exchange="binance",
            timestamp_ns=1700000000000000000,
        )
        assert order.status == "pending"
        assert order.order_type == "limit"


class TestPositionState:
    def test_create_position(self) -> None:
        pos = PositionState(
            symbol="BTCUSDT",
            market=Market.SPOT,
            side="long",
            quantity=Decimal("1.0"),
            entry_price=Decimal("50000"),
            unrealized_pnl=Decimal("500"),
            realized_pnl=Decimal("0"),
            timestamp_ns=1700000000000000000,
        )
        assert pos.side == "long"
        assert pos.unrealized_pnl == Decimal("500")


class TestInstrument:
    def test_create_instrument(self) -> None:
        inst = Instrument(
            internal_id="binance_btcusdt",
            symbol="BTCUSDT",
            market=Market.SPOT,
            instrument_type=InstrumentType.SPOT,
            exchange="binance",
            base_currency="BTC",
            quote_currency="USDT",
            tick_size=Decimal("0.01"),
            lot_size=Decimal("0.001"),
        )
        assert inst.is_active is True
        assert inst.contract_multiplier == Decimal("1")


class TestFill:
    def test_create_fill(self) -> None:
        fill = Fill(
            order_id="order-123",
            symbol="BTCUSDT",
            side="buy",
            price=Decimal("50000"),
            quantity=Decimal("1.0"),
            fee=Decimal("50"),
            fee_currency="USDT",
            exchange="binance",
            timestamp_ns=1700000000000000000,
        )
        assert fill.fee == Decimal("50")

"""期权策略补充测试 — CalendarSpread, Collar, DeltaNeutral"""

from __future__ import annotations

import time
from datetime import date, timedelta
from decimal import Decimal

from one_quant.core.types import Kline, Market, OptionQuote, Ticker
from one_quant.strategy.options.strategies import (
    CalendarSpreadStrategy,
    CollarStrategy,
    DeltaNeutralStrategy,
)


def _q(
    option_type: str = "call",
    strike: str = "100",
    delta: str = "0.5",
    iv: str = "0.3",
    bid: str = "5",
    ask: str = "6",
    expiry: date | None = None,
) -> OptionQuote:
    return OptionQuote(
        symbol=f"BTC-{strike}-{option_type.upper()}",
        underlying="BTC",
        strike=Decimal(strike),
        expiry=expiry or (date.today() + timedelta(days=30)),
        option_type=option_type,
        bid=Decimal(bid),
        ask=Decimal(ask),
        iv=Decimal(iv),
        delta=Decimal(delta),
        gamma=Decimal("0.01"),
        theta=Decimal("-0.05"),
        vega=Decimal("0.15"),
        open_interest=Decimal("1000"),
        timestamp_ns=time.time_ns(),
    )


# ──────────────────────────── CalendarSpreadStrategy 测试 ────────────────────────────


class TestCalendarSpreadStrategy:
    def test_name(self):
        s = CalendarSpreadStrategy()
        assert s.name == "calendar_spread"

    def test_on_ticker_returns_empty(self):
        s = CalendarSpreadStrategy()
        t = Ticker(
            symbol="BTC",
            market=Market.SPOT,
            exchange="binance",
            last_price=Decimal("100"),
            bid=Decimal("100"),
            ask=Decimal("100"),
            volume_24h=Decimal("1000"),
            timestamp_ns=time.time_ns(),
        )
        assert s.on_ticker(t) == []

    def test_on_kline_returns_empty(self):
        s = CalendarSpreadStrategy()
        k = Kline(
            symbol="BTC",
            market=Market.SPOT,
            exchange="binance",
            interval="1m",
            open=Decimal("100"),
            high=Decimal("105"),
            low=Decimal("95"),
            close=Decimal("102"),
            volume=Decimal("100"),
            timestamp_ns=time.time_ns(),
        )
        assert s.on_kline(k) == []

    def test_near_term_sell_signal(self):
        s = CalendarSpreadStrategy(min_dte_near=7, max_dte_near=30)
        exp = date.today() + timedelta(days=15)
        q = _q(delta="0.5", expiry=exp)
        signals = s.on_option_quote(q)
        sells = [s for s in signals if s.side == "sell"]
        assert len(sells) > 0
        assert sells[0].metadata["leg"] == "short_near_term"

    def test_far_term_buy_signal(self):
        s = CalendarSpreadStrategy(min_dte_far=60)
        exp = date.today() + timedelta(days=90)
        q = _q(delta="0.5", expiry=exp)
        signals = s.on_option_quote(q)
        buys = [s for s in signals if s.side == "buy"]
        assert len(buys) > 0
        assert buys[0].metadata["leg"] == "long_far_term"

    def test_otm_no_signal(self):
        s = CalendarSpreadStrategy()
        exp = date.today() + timedelta(days=15)
        q = _q(delta="0.1", expiry=exp)
        signals = s.on_option_quote(q)
        assert len(signals) == 0

    def test_short_dte_no_far_signal(self):
        s = CalendarSpreadStrategy(min_dte_far=60)
        exp = date.today() + timedelta(days=10)
        q = _q(delta="0.5", expiry=exp)
        signals = s.on_option_quote(q)
        buys = [s for s in signals if s.metadata.get("leg") == "long_far_term"]
        assert len(buys) == 0


# ──────────────────────────── CollarStrategy 测试 ────────────────────────────


class TestCollarStrategy:
    def test_name(self):
        s = CollarStrategy()
        assert s.name == "collar"

    def test_protective_put_signal(self):
        s = CollarStrategy(put_delta=Decimal("0.2"))
        q = _q(option_type="put", delta="-0.2")
        signals = s.on_option_quote(q)
        buys = [s for s in signals if s.side == "buy"]
        assert len(buys) > 0
        assert buys[0].metadata["leg"] == "protective_put"

    def test_covered_call_signal(self):
        s = CollarStrategy(call_delta=Decimal("0.3"))
        q = _q(option_type="call", delta="0.3")
        signals = s.on_option_quote(q)
        sells = [s for s in signals if s.side == "sell"]
        assert len(sells) > 0
        assert sells[0].metadata["leg"] == "covered_call"

    def test_put_outside_delta_range(self):
        s = CollarStrategy(put_delta=Decimal("0.2"))
        q = _q(option_type="put", delta="-0.5")
        signals = s.on_option_quote(q)
        buys = [s for s in signals if s.metadata.get("leg") == "protective_put"]
        assert len(buys) == 0

    def test_call_outside_delta_range(self):
        s = CollarStrategy(call_delta=Decimal("0.3"))
        q = _q(option_type="call", delta="0.7")
        signals = s.on_option_quote(q)
        sells = [s for s in signals if s.metadata.get("leg") == "covered_call"]
        assert len(sells) == 0

    def test_on_ticker_returns_empty(self):
        s = CollarStrategy()
        t = Ticker(
            symbol="BTC",
            market=Market.SPOT,
            exchange="binance",
            last_price=Decimal("100"),
            bid=Decimal("100"),
            ask=Decimal("100"),
            volume_24h=Decimal("1000"),
            timestamp_ns=time.time_ns(),
        )
        assert s.on_ticker(t) == []


# ──────────────────────────── DeltaNeutralStrategy 测试 ────────────────────────────


class TestDeltaNeutralStrategy:
    def test_name(self):
        s = DeltaNeutralStrategy()
        assert s.name == "delta_neutral"

    def test_call_hedge_signal(self):
        s = DeltaNeutralStrategy(delta_tolerance=Decimal("0.3"))
        q = _q(option_type="call", delta="0.8")
        q = q.model_copy(update={"underlying": "BTC"})
        signals = s.on_option_quote(q)
        sells = [s for s in signals if s.side == "sell"]
        assert len(sells) > 0
        assert sells[0].metadata["hedge_type"] == "delta_neutral"

    def test_put_hedge_signal(self):
        s = DeltaNeutralStrategy(delta_tolerance=Decimal("0.3"))
        q = _q(option_type="put", delta="-0.8")
        q = q.model_copy(update={"underlying": "BTC"})
        signals = s.on_option_quote(q)
        buys = [s for s in signals if s.side == "buy"]
        assert len(buys) > 0

    def test_low_delta_no_signal(self):
        s = DeltaNeutralStrategy(delta_tolerance=Decimal("0.5"))
        q = _q(option_type="call", delta="0.1")
        signals = s.on_option_quote(q)
        assert len(signals) == 0

    def test_on_ticker_returns_empty(self):
        s = DeltaNeutralStrategy()
        t = Ticker(
            symbol="BTC",
            market=Market.SPOT,
            exchange="binance",
            last_price=Decimal("100"),
            bid=Decimal("100"),
            ask=Decimal("100"),
            volume_24h=Decimal("1000"),
            timestamp_ns=time.time_ns(),
        )
        assert s.on_ticker(t) == []

    def test_on_kline_returns_empty(self):
        s = DeltaNeutralStrategy()
        k = Kline(
            symbol="BTC",
            market=Market.SPOT,
            exchange="binance",
            interval="1m",
            open=Decimal("100"),
            high=Decimal("105"),
            low=Decimal("95"),
            close=Decimal("102"),
            volume=Decimal("100"),
            timestamp_ns=time.time_ns(),
        )
        assert s.on_kline(k) == []

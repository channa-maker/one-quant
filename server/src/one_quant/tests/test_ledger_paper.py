"""
Tests for execution.ledger and execution.paper_trading
"""

import time
import uuid
from decimal import Decimal

import pytest

from one_quant.core.types import Market, Order
from one_quant.execution.ledger import Ledger, LedgerEntry
from one_quant.execution.paper_trading import PaperExchangeSimulator


def _make_order(
    qty: str = "1.0",
    price: str = "50000",
    side: str = "buy",
    order_type: str = "market",
) -> Order:
    return Order(
        client_order_id=str(uuid.uuid4()),
        symbol="BTCUSDT",
        market=Market.SPOT,
        side=side,
        order_type=order_type,
        quantity=Decimal(qty),
        price=Decimal(price),
        stop_price=None,
        status="pending",
        exchange="binance",
        timestamp_ns=time.time_ns(),
    )


# ═══════════════════════ Ledger ═══════════════════════


class TestLedger:
    def test_create_ledger(self):
        ledger = Ledger()
        assert ledger.entry_count == 0
        assert ledger._base_currency == "USDT"

    def test_custom_base_currency(self):
        ledger = Ledger(base_currency="USD")
        assert ledger._base_currency == "USD"

    def test_record_buy_trade(self):
        ledger = Ledger()
        asset, cash, fee = ledger.record_trade(
            account="main",
            symbol="BTC/USDT",
            side="buy",
            quantity=Decimal("1"),
            price=Decimal("50000"),
            commission=Decimal("50"),
            commission_currency="USDT",
        )

        # Asset entry: debit BTC, credit 0
        assert asset.currency == "BTC"
        assert asset.debit == Decimal("1")
        assert asset.credit == Decimal("0")
        assert "买入" in asset.description

        # Cash entry: debit 0, credit USDT
        assert cash.currency == "USDT"
        assert cash.debit == Decimal("0")
        assert cash.credit == Decimal("50000")

        # Fee entry: debit fee, credit 0
        assert fee.currency == "USDT"
        assert fee.debit == Decimal("50")
        assert fee.credit == Decimal("0")

    def test_record_sell_trade(self):
        ledger = Ledger()
        asset, cash, fee = ledger.record_trade(
            account="main",
            symbol="BTC/USDT",
            side="sell",
            quantity=Decimal("1"),
            price=Decimal("50000"),
            commission=Decimal("50"),
            commission_currency="USDT",
        )

        # Asset entry: debit 0, credit BTC
        assert asset.currency == "BTC"
        assert asset.debit == Decimal("0")
        assert asset.credit == Decimal("1")

        # Cash entry: debit USDT, credit 0
        assert cash.currency == "USDT"
        assert cash.debit == Decimal("50000")
        assert cash.credit == Decimal("0")

    def test_record_trade_updates_balances(self):
        ledger = Ledger()
        ledger.record_trade(
            account="main",
            symbol="BTC/USDT",
            side="buy",
            quantity=Decimal("1"),
            price=Decimal("50000"),
            commission=Decimal("50"),
            commission_currency="USDT",
        )

        assert ledger.get_balance("main", "BTC") == Decimal("1")
        # USDT: cash credit -50000, fee debit +50 => -49950
        assert ledger.get_balance("main", "USDT") == Decimal("-49950")

    def test_get_balance_unknown_account(self):
        ledger = Ledger()
        assert ledger.get_balance("nonexistent", "BTC") == Decimal("0")

    def test_get_balance_unknown_currency(self):
        ledger = Ledger()
        assert ledger.get_balance("main", "ETH") == Decimal("0")

    def test_get_all_balances(self):
        ledger = Ledger()
        ledger.record_trade(
            account="main",
            symbol="BTC/USDT",
            side="buy",
            quantity=Decimal("1"),
            price=Decimal("50000"),
            commission=Decimal("50"),
            commission_currency="USDT",
        )

        balances = ledger.get_all_balances("main")
        assert "BTC" in balances
        assert "USDT" in balances
        assert balances["BTC"] == Decimal("1")

    def test_get_all_balances_unknown(self):
        ledger = Ledger()
        assert ledger.get_all_balances("nonexistent") == {}

    def test_compute_nav(self):
        ledger = Ledger()
        ledger.record_trade(
            account="main",
            symbol="BTC/USDT",
            side="buy",
            quantity=Decimal("2"),
            price=Decimal("50000"),
            commission=Decimal("100"),
            commission_currency="USDT",
        )

        nav = ledger.compute_nav("main", {"BTC": Decimal("60000")})
        # BTC balance = 2, USDT balance = -100000 + 100 = -99900
        # NAV = 2 * 60000 + (-99900) = 20100
        assert nav == Decimal("20100")

    def test_compute_nav_no_prices(self):
        ledger = Ledger()
        ledger.record_trade(
            account="main",
            symbol="BTC/USDT",
            side="buy",
            quantity=Decimal("1"),
            price=Decimal("50000"),
            commission=Decimal("0"),
            commission_currency="USDT",
        )

        # No price for BTC, only USDT counted
        nav = ledger.compute_nav("main", {})
        assert nav == Decimal("-50000")

    def test_compute_nav_unknown_account(self):
        ledger = Ledger()
        nav = ledger.compute_nav("nonexistent", {"BTC": Decimal("50000")})
        assert nav == Decimal("0")

    def test_verify_balance(self):
        ledger = Ledger()
        ledger.record_trade(
            account="main",
            symbol="BTC/USDT",
            side="buy",
            quantity=Decimal("1"),
            price=Decimal("50000"),
            commission=Decimal("50"),
            commission_currency="USDT",
        )

        assert ledger.verify_balance() is True

    def test_entry_count(self):
        ledger = Ledger()
        assert ledger.entry_count == 0

        ledger.record_trade(
            account="main",
            symbol="BTC/USDT",
            side="buy",
            quantity=Decimal("1"),
            price=Decimal("50000"),
            commission=Decimal("50"),
            commission_currency="USDT",
        )
        # 3 entries: asset, cash, fee
        assert ledger.entry_count == 3

    def test_entries_property(self):
        ledger = Ledger()
        ledger.record_trade(
            account="main",
            symbol="BTC/USDT",
            side="buy",
            quantity=Decimal("1"),
            price=Decimal("50000"),
            commission=Decimal("50"),
            commission_currency="USDT",
        )

        entries = ledger.entries
        assert len(entries) == 3
        assert all(isinstance(e, LedgerEntry) for e in entries)

    def test_multiple_trades_same_account(self):
        ledger = Ledger()
        ledger.record_trade(
            account="main",
            symbol="BTC/USDT",
            side="buy",
            quantity=Decimal("1"),
            price=Decimal("50000"),
            commission=Decimal("50"),
            commission_currency="USDT",
        )
        ledger.record_trade(
            account="main",
            symbol="BTC/USDT",
            side="sell",
            quantity=Decimal("0.5"),
            price=Decimal("55000"),
            commission=Decimal("27.5"),
            commission_currency="USDT",
        )

        # BTC: 1 - 0.5 = 0.5
        assert ledger.get_balance("main", "BTC") == Decimal("0.5")
        # Buy: USDT = -50000 + 50 = -49950
        # Sell: USDT = +27500 + 27.5 = +27527.5
        # Total: -49950 + 27527.5 = -22422.5
        assert ledger.get_balance("main", "USDT") == Decimal("-22422.5")

    def test_symbol_without_slash(self):
        ledger = Ledger()
        ledger.record_trade(
            account="main",
            symbol="BTCUSDT",
            side="buy",
            quantity=Decimal("1"),
            price=Decimal("50000"),
            commission=Decimal("50"),
            commission_currency="USDT",
        )
        # When no slash, base = symbol, quote = base_currency
        assert ledger.get_balance("main", "BTCUSDT") == Decimal("1")

    def test_entry_ids_increment(self):
        ledger = Ledger()
        ledger.record_trade(
            account="main",
            symbol="BTC/USDT",
            side="buy",
            quantity=Decimal("1"),
            price=Decimal("50000"),
            commission=Decimal("10"),
            commission_currency="USDT",
        )
        ledger.record_trade(
            account="main",
            symbol="ETH/USDT",
            side="buy",
            quantity=Decimal("10"),
            price=Decimal("3000"),
            commission=Decimal("10"),
            commission_currency="USDT",
        )

        entries = ledger.entries
        assert entries[0].entry_id == "JE-00000001"
        assert (
            entries[3].entry_id == "JE-00000004"
        )  # 4th entry (3 from first trade + 1 from second)


# ═══════════════════════ PaperExchangeSimulator ═══════════════════════


class TestPaperExchangeSimulator:
    def test_default_init(self):
        sim = PaperExchangeSimulator()
        assert sim.get_balance() == Decimal("100000")
        assert sim.stats["total_fills"] == 0
        assert sim.stats["open_orders"] == 0

    def test_custom_init(self):
        sim = PaperExchangeSimulator(
            initial_balance=Decimal("500000"),
            commission_rate=Decimal("0.002"),
            slippage_bps=10,
        )
        assert sim.get_balance() == Decimal("500000")

    @pytest.mark.asyncio
    async def test_submit_market_buy_order(self):
        sim = PaperExchangeSimulator(
            initial_balance=Decimal("100000"),
            commission_rate=Decimal("0.001"),
            slippage_bps=0,
        )
        order = _make_order(qty="1.0", price="50000", side="buy", order_type="market")

        ex_id = await sim.submit_order(order)

        assert ex_id.startswith("SIM-")
        assert sim.stats["total_orders"] == 1
        assert sim.stats["total_fills"] == 1
        # Balance should decrease
        assert sim.get_balance() < Decimal("100000")

    @pytest.mark.asyncio
    async def test_submit_market_sell_order(self):
        sim = PaperExchangeSimulator(
            initial_balance=Decimal("100000"),
            slippage_bps=0,
        )
        # First buy
        buy_order = _make_order(qty="1.0", price="50000", side="buy", order_type="market")
        await sim.submit_order(buy_order)

        balance_after_buy = sim.get_balance()

        # Then sell
        sell_order = _make_order(qty="1.0", price="50000", side="sell", order_type="market")
        await sim.submit_order(sell_order)

        # Balance should increase after sell
        assert sim.get_balance() > balance_after_buy

    @pytest.mark.asyncio
    async def test_submit_limit_order(self):
        sim = PaperExchangeSimulator()
        order = _make_order(qty="1.0", price="50000", side="buy", order_type="limit")

        ex_id = await sim.submit_order(order)

        assert ex_id.startswith("SIM-")
        assert sim.stats["open_orders"] == 1
        assert sim.stats["total_fills"] == 0  # Not filled yet

    @pytest.mark.asyncio
    async def test_cancel_order(self):
        sim = PaperExchangeSimulator()
        order = _make_order(qty="1.0", price="50000", side="buy", order_type="limit")

        ex_id = await sim.submit_order(order)
        assert sim.stats["open_orders"] == 1

        result = await sim.cancel_order(ex_id)
        assert result is True
        assert sim.stats["open_orders"] == 0

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_order(self):
        sim = PaperExchangeSimulator()
        result = await sim.cancel_order("nonexistent-id")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_position_after_buy(self):
        sim = PaperExchangeSimulator(slippage_bps=0)
        order = _make_order(qty="1.0", price="50000", side="buy", order_type="market")
        await sim.submit_order(order)

        pos = sim.get_position("BTCUSDT")
        assert pos["quantity"] == Decimal("1")
        assert pos["avg_price"] > 0

    @pytest.mark.asyncio
    async def test_get_position_unknown_symbol(self):
        sim = PaperExchangeSimulator()
        pos = sim.get_position("UNKNOWN")
        assert pos["quantity"] == Decimal("0")
        assert pos["avg_price"] == Decimal("0")

    @pytest.mark.asyncio
    async def test_slippage_applied_buy(self):
        sim = PaperExchangeSimulator(
            slippage_bps=100,  # 1%
            commission_rate=Decimal("0"),
        )
        order = _make_order(qty="1.0", price="50000", side="buy", order_type="market")
        await sim.submit_order(order)

        pos = sim.get_position("BTCUSDT")
        # With 100bps slippage on buy, fill price = 50000 * 1.01 = 50500
        assert pos["avg_price"] == Decimal("50500")

    @pytest.mark.asyncio
    async def test_slippage_applied_sell(self):
        sim = PaperExchangeSimulator(
            initial_balance=Decimal("200000"),
            slippage_bps=100,
            commission_rate=Decimal("0"),
        )
        # Buy first
        buy = _make_order(qty="1.0", price="50000", side="buy", order_type="market")
        await sim.submit_order(buy)

        balance_before = sim.get_balance()
        sell = _make_order(qty="1.0", price="50000", side="sell", order_type="market")
        await sim.submit_order(sell)

        # Sell slippage: fill_price = 50000 * 0.99 = 49500
        # Balance change: +49500 (no commission)
        balance_after = sim.get_balance()
        assert balance_after - balance_before == Decimal("49500")

    @pytest.mark.asyncio
    async def test_commission_deducted(self):
        sim = PaperExchangeSimulator(
            commission_rate=Decimal("0.01"),  # 1%
            slippage_bps=0,
        )
        order = _make_order(qty="1.0", price="50000", side="buy", order_type="market")
        await sim.submit_order(order)

        # Notional = 50000, commission = 50000 * 0.01 = 500
        # Balance = 100000 - 50000 - 500 = 49500
        assert sim.get_balance() == Decimal("49500")

    @pytest.mark.asyncio
    async def test_multiple_positions(self):
        sim = PaperExchangeSimulator(
            initial_balance=Decimal("500000"),
            slippage_bps=0,
        )
        buy_btc = _make_order(qty="1.0", price="50000", side="buy", order_type="market")
        await sim.submit_order(buy_btc)

        buy_eth = _make_order(
            qty="10",
            price="3000",
            side="buy",
            order_type="market",
        )
        # Need to change symbol
        buy_eth = Order(
            client_order_id=str(uuid.uuid4()),
            symbol="ETHUSDT",
            market=Market.SPOT,
            side="buy",
            order_type="market",
            quantity=Decimal("10"),
            price=Decimal("3000"),
            stop_price=None,
            status="pending",
            exchange="binance",
            timestamp_ns=time.time_ns(),
        )
        await sim.submit_order(buy_eth)

        assert sim.stats["positions"] == 2
        assert sim.get_position("BTCUSDT")["quantity"] == Decimal("1")
        assert sim.get_position("ETHUSDT")["quantity"] == Decimal("10")

    @pytest.mark.asyncio
    async def test_average_price_multiple_buys(self):
        sim = PaperExchangeSimulator(
            initial_balance=Decimal("500000"),
            slippage_bps=0,
            commission_rate=Decimal("0"),
        )
        buy1 = _make_order(qty="1.0", price="50000", side="buy", order_type="market")
        await sim.submit_order(buy1)

        buy2 = _make_order(qty="1.0", price="60000", side="buy", order_type="market")
        await sim.submit_order(buy2)

        pos = sim.get_position("BTCUSDT")
        assert pos["quantity"] == Decimal("2")
        # Avg price = (50000*1 + 60000*1) / 2 = 55000
        assert pos["avg_price"] == Decimal("55000")

    @pytest.mark.asyncio
    async def test_sell_reduces_position(self):
        sim = PaperExchangeSimulator(
            initial_balance=Decimal("200000"),
            slippage_bps=0,
            commission_rate=Decimal("0"),
        )
        buy = _make_order(qty="2.0", price="50000", side="buy", order_type="market")
        await sim.submit_order(buy)

        sell = _make_order(qty="1.0", price="50000", side="sell", order_type="market")
        await sim.submit_order(sell)

        pos = sim.get_position("BTCUSDT")
        assert pos["quantity"] == Decimal("1")

    @pytest.mark.asyncio
    async def test_sell_all_clears_position(self):
        sim = PaperExchangeSimulator(
            slippage_bps=0,
            commission_rate=Decimal("0"),
        )
        buy = _make_order(qty="1.0", price="50000", side="buy", order_type="market")
        await sim.submit_order(buy)

        sell = _make_order(qty="1.0", price="50000", side="sell", order_type="market")
        await sim.submit_order(sell)

        pos = sim.get_position("BTCUSDT")
        assert pos["quantity"] == Decimal("0")
        assert pos["avg_price"] == Decimal("0")

    def test_stats(self):
        sim = PaperExchangeSimulator()
        stats = sim.stats

        assert "balance" in stats
        assert "positions" in stats
        assert "open_orders" in stats
        assert "total_fills" in stats
        assert "total_orders" in stats
        assert stats["balance"] == "100000"

    @pytest.mark.asyncio
    async def test_fill_recorded(self):
        sim = PaperExchangeSimulator(slippage_bps=0, commission_rate=Decimal("0"))
        order = _make_order(qty="1.0", price="50000", side="buy", order_type="market")
        await sim.submit_order(order)

        assert sim.stats["total_fills"] == 1

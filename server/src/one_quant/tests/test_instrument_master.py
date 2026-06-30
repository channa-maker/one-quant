"""Instrument Master 单元测试"""

from __future__ import annotations

from decimal import Decimal

import pytest

from one_quant.core.types import Instrument, InstrumentType, Market
from one_quant.data.instrument_master import InstrumentMaster


@pytest.fixture
def master() -> InstrumentMaster:
    return InstrumentMaster()


class TestInstrumentMaster:
    def test_register_and_get(self, master: InstrumentMaster) -> None:
        inst = Instrument(
            internal_id="binance:BTC/USDT",
            symbol="BTCUSDT",
            market=Market.SPOT,
            instrument_type=InstrumentType.SPOT,
            exchange="binance",
            base_currency="BTC",
            quote_currency="USDT",
            tick_size=Decimal("0.01"),
            lot_size=Decimal("0.00001"),
        )
        master.register(inst)

        result = master.get("binance:BTC/USDT")
        assert result is not None
        assert result.symbol == "BTCUSDT"

    def test_get_by_exchange_symbol(self, master: InstrumentMaster) -> None:
        inst = Instrument(
            internal_id="okx:ETH/USDT",
            symbol="ETH-USDT",
            market=Market.SPOT,
            instrument_type=InstrumentType.SPOT,
            exchange="okx",
            base_currency="ETH",
            quote_currency="USDT",
            tick_size=Decimal("0.01"),
            lot_size=Decimal("0.001"),
        )
        master.register(inst)

        result = master.get_by_exchange_symbol("okx", "ETH-USDT")
        assert result is not None
        assert result.internal_id == "okx:ETH/USDT"

    def test_deactivate(self, master: InstrumentMaster) -> None:
        inst = Instrument(
            internal_id="binance:DOGE/USDT",
            symbol="DOGEUSDT",
            market=Market.SPOT,
            instrument_type=InstrumentType.SPOT,
            exchange="binance",
            base_currency="DOGE",
            quote_currency="USDT",
            tick_size=Decimal("0.0001"),
            lot_size=Decimal("1"),
        )
        master.register(inst)
        assert master.deactivate("binance:DOGE/USDT", reason="下架") is True

        result = master.get("binance:DOGE/USDT")
        assert result is not None
        assert result.is_active is False

    def test_list_active(self, master: InstrumentMaster) -> None:
        for sym in ["BTC/USDT", "ETH/USDT", "SOL/USDT"]:
            inst = Instrument(
                internal_id=f"binance:{sym}",
                symbol=sym.replace("/", ""),
                market=Market.SPOT,
                instrument_type=InstrumentType.SPOT,
                exchange="binance",
                base_currency=sym.split("/")[0],
                quote_currency="USDT",
                tick_size=Decimal("0.01"),
                lot_size=Decimal("0.00001"),
            )
            master.register(inst)

        master.deactivate("binance:SOL/USDT")

        active = master.list_active(exchange="binance")
        assert len(active) == 2

    def test_resolve_internal_id_auto_register(self, master: InstrumentMaster) -> None:
        iid = master.resolve_internal_id("binance", "NEW/USDT")
        assert iid == "binance:NEW/USDT"
        assert master.get(iid) is not None

    def test_point_in_time_query(self, master: InstrumentMaster) -> None:
        import time
        t1 = time.time_ns()
        inst = Instrument(
            internal_id="binance:T1/USDT",
            symbol="T1USDT",
            market=Market.SPOT,
            instrument_type=InstrumentType.SPOT,
            exchange="binance",
            base_currency="T1",
            quote_currency="USDT",
            tick_size=Decimal("0.01"),
            lot_size=Decimal("0.00001"),
        )
        master.register(inst)

        t2 = time.time_ns()
        master.deactivate("binance:T1/USDT")

        # t1 时刻应该活跃
        active_at_t1 = master.get_active_at(t1 + 1)
        ids_at_t1 = [i.internal_id for i in active_at_t1]
        assert "binance:T1/USDT" in ids_at_t1

    def test_stats(self, master: InstrumentMaster) -> None:
        inst = Instrument(
            internal_id="binance:X/USDT",
            symbol="XUSDT",
            market=Market.SPOT,
            instrument_type=InstrumentType.SPOT,
            exchange="binance",
            base_currency="X",
            quote_currency="USDT",
            tick_size=Decimal("0.01"),
            lot_size=Decimal("0.00001"),
        )
        master.register(inst)
        stats = master.stats
        assert stats["total"] == 1
        assert stats["active"] == 1

"""
Tests for accounting.tax (WashSaleDetector, TaxLotAccounting, TaxReportGenerator)
"""

from datetime import date
from decimal import Decimal

from one_quant.accounting.tax import (
    DisposalRecord,
    TaxLot,
    TaxLotAccounting,
    TaxReportGenerator,
    WashSaleDetector,
)

# ═══════════════════════ WashSaleDetector ═══════════════════════


class TestWashSaleDetector:
    def test_create(self):
        detector = WashSaleDetector()
        assert detector.total_disallowed_loss == Decimal("0")

    def test_check_wash_sale_no_loss_no_trigger(self):
        detector = WashSaleDetector()
        # sell_price >= buy_price → no loss, no wash sale
        is_wash, loss = detector.check_wash_sale(
            symbol="AAPL",
            sell_date=date(2024, 1, 15),
            sell_price=Decimal("160"),
            buy_date=date(2024, 2, 1),  # 17 days later, within window
            buy_price=Decimal("150"),
        )
        # sell_price (160) >= buy_price (150) → no loss
        assert is_wash is False
        assert loss == Decimal("0")

    def test_check_wash_sale_with_loss(self):
        detector = WashSaleDetector()
        is_wash, loss = detector.check_wash_sale(
            symbol="AAPL",
            sell_date=date(2024, 1, 15),
            sell_price=Decimal("140"),
            buy_date=date(2024, 2, 1),  # 17 days later, within 30-day window
            buy_price=Decimal("150"),
        )
        # sell_price (140) < buy_price (150) → loss detected
        assert is_wash is True
        assert loss == Decimal("10")

    def test_check_wash_sale_outside_window(self):
        detector = WashSaleDetector()
        is_wash, loss = detector.check_wash_sale(
            symbol="AAPL",
            sell_date=date(2024, 1, 1),
            sell_price=Decimal("140"),
            buy_date=date(2024, 3, 15),  # 74 days later, outside window
            buy_price=Decimal("150"),
        )
        assert is_wash is False
        assert loss == Decimal("0")

    def test_check_wash_sale_before_sell(self):
        detector = WashSaleDetector()
        # Buy before sell (within 30 days before)
        is_wash, loss = detector.check_wash_sale(
            symbol="AAPL",
            sell_date=date(2024, 2, 15),
            sell_price=Decimal("140"),
            buy_date=date(2024, 1, 25),  # 21 days before
            buy_price=Decimal("150"),
        )
        assert is_wash is True
        assert loss == Decimal("10")

    def test_check_wash_sale_no_profit_scenario(self):
        detector = WashSaleDetector()
        # sell_price >= buy_price → no loss, no wash sale
        is_wash, loss = detector.check_wash_sale(
            symbol="AAPL",
            sell_date=date(2024, 1, 15),
            sell_price=Decimal("160"),
            buy_date=date(2024, 2, 1),
            buy_price=Decimal("150"),
        )
        assert is_wash is False

    def test_record_sale(self):
        detector = WashSaleDetector()
        detector.record_sale(
            symbol="AAPL",
            sell_date=date(2024, 1, 15),
            sell_price=Decimal("150"),
            quantity=Decimal("100"),
            cost_basis=Decimal("160"),
        )
        # No direct accessor, but no crash
        assert detector.total_disallowed_loss == Decimal("0")

    def test_check_wash_sale_with_lots_triggered(self):
        detector = WashSaleDetector()
        recent_buys = [
            {"buy_date": date(2024, 2, 1), "buy_price": Decimal("155"), "quantity": Decimal("50")},
        ]
        is_wash, loss = detector.check_wash_sale_with_lots(
            symbol="AAPL",
            sell_date=date(2024, 1, 15),
            sell_price=Decimal("150"),
            cost_basis=Decimal("160"),
            quantity=Decimal("100"),
            recent_buys=recent_buys,
        )
        # cost_basis > sell_price → loss = (160-150)*100 = 1000
        assert is_wash is True
        assert loss == Decimal("1000")

    def test_check_wash_sale_with_lots_no_loss(self):
        detector = WashSaleDetector()
        is_wash, loss = detector.check_wash_sale_with_lots(
            symbol="AAPL",
            sell_date=date(2024, 1, 15),
            sell_price=Decimal("170"),
            cost_basis=Decimal("160"),
            quantity=Decimal("100"),
            recent_buys=[],
        )
        # No loss (profit) → no wash sale
        assert is_wash is False
        assert loss == Decimal("0")

    def test_check_wash_sale_with_lots_outside_window(self):
        detector = WashSaleDetector()
        recent_buys = [
            {"buy_date": date(2024, 5, 1), "buy_price": Decimal("155"), "quantity": Decimal("50")},
        ]
        is_wash, loss = detector.check_wash_sale_with_lots(
            symbol="AAPL",
            sell_date=date(2024, 1, 15),
            sell_price=Decimal("150"),
            cost_basis=Decimal("160"),
            quantity=Decimal("100"),
            recent_buys=recent_buys,
        )
        assert is_wash is False

    def test_total_disallowed_loss_accumulates(self):
        detector = WashSaleDetector()
        detector.check_wash_sale(
            symbol="AAPL",
            sell_date=date(2024, 1, 15),
            sell_price=Decimal("140"),
            buy_date=date(2024, 2, 1),
            buy_price=Decimal("150"),
        )
        detector.check_wash_sale(
            symbol="GOOG",
            sell_date=date(2024, 3, 1),
            sell_price=Decimal("100"),
            buy_date=date(2024, 3, 15),
            buy_price=Decimal("120"),
        )

        assert detector.total_disallowed_loss == Decimal("30")  # 10 + 20

    def test_wash_sale_window_days(self):
        assert WashSaleDetector.WASH_SALE_WINDOW_DAYS == 30


# ═══════════════════════ TaxLotAccounting ═══════════════════════


class TestTaxLotAccounting:
    def test_create(self):
        accounting = TaxLotAccounting()
        assert accounting.get_total_quantity("AAPL") == Decimal("0")

    def test_add_lot(self):
        accounting = TaxLotAccounting()
        lot = accounting.add_lot("AAPL", date(2024, 1, 10), Decimal("150"), Decimal("100"))

        assert isinstance(lot, TaxLot)
        assert lot.symbol == "AAPL"
        assert lot.buy_date == date(2024, 1, 10)
        assert lot.buy_price == Decimal("150")
        assert lot.quantity == Decimal("100")
        assert lot.lot_id.startswith("LOT-")

    def test_add_multiple_lots(self):
        accounting = TaxLotAccounting()
        accounting.add_lot("AAPL", date(2024, 1, 10), Decimal("150"), Decimal("100"))
        accounting.add_lot("AAPL", date(2024, 2, 15), Decimal("160"), Decimal("50"))

        assert accounting.get_total_quantity("AAPL") == Decimal("150")

    def test_get_lots_sorted_by_date(self):
        accounting = TaxLotAccounting()
        accounting.add_lot("AAPL", date(2024, 3, 10), Decimal("170"), Decimal("50"))
        accounting.add_lot("AAPL", date(2024, 1, 10), Decimal("150"), Decimal("100"))
        accounting.add_lot("AAPL", date(2024, 2, 15), Decimal("160"), Decimal("50"))

        lots = accounting.get_lots("AAPL")
        assert len(lots) == 3
        # Should be sorted by buy_date
        assert lots[0].buy_date < lots[1].buy_date < lots[2].buy_date

    def test_get_lots_unknown_symbol(self):
        accounting = TaxLotAccounting()
        assert accounting.get_lots("UNKNOWN") == []

    def test_calculate_cost_basis_fifo(self):
        accounting = TaxLotAccounting()
        accounting.add_lot("AAPL", date(2024, 1, 10), Decimal("150"), Decimal("100"))
        accounting.add_lot("AAPL", date(2024, 2, 15), Decimal("160"), Decimal("100"))

        cost_basis, consumed = accounting.calculate_cost_basis("AAPL", Decimal("80"), method="fifo")

        # FIFO: take 80 from first lot (price 150)
        assert cost_basis == Decimal("12000.00")  # 80 * 150
        assert len(consumed) == 1
        assert consumed[0].buy_price == Decimal("150")
        assert consumed[0].quantity == Decimal("80")

    def test_calculate_cost_basis_fifo_spanning_lots(self):
        accounting = TaxLotAccounting()
        accounting.add_lot("AAPL", date(2024, 1, 10), Decimal("150"), Decimal("100"))
        accounting.add_lot("AAPL", date(2024, 2, 15), Decimal("160"), Decimal("100"))

        cost_basis, consumed = accounting.calculate_cost_basis(
            "AAPL", Decimal("150"), method="fifo"
        )

        # 100 * 150 + 50 * 160 = 15000 + 8000 = 23000
        assert cost_basis == Decimal("23000.00")
        assert len(consumed) == 2

    def test_calculate_cost_basis_insufficient(self):
        accounting = TaxLotAccounting()
        accounting.add_lot("AAPL", date(2024, 1, 10), Decimal("150"), Decimal("50"))

        try:
            accounting.calculate_cost_basis("AAPL", Decimal("100"), method="fifo")
            assert False, "Should raise ValueError"
        except ValueError as e:
            assert "数量不足" in str(e)

    def test_calculate_cost_basis_no_lots(self):
        accounting = TaxLotAccounting()
        try:
            accounting.calculate_cost_basis("AAPL", Decimal("100"), method="fifo")
            assert False, "Should raise ValueError"
        except ValueError as e:
            assert "无可用批次" in str(e)

    def test_calculate_cost_basis_specific(self):
        accounting = TaxLotAccounting()
        accounting.add_lot("AAPL", date(2024, 1, 10), Decimal("150"), Decimal("100"))
        lot2 = accounting.add_lot("AAPL", date(2024, 2, 15), Decimal("160"), Decimal("100"))

        cost_basis, consumed = accounting.calculate_cost_basis(
            "AAPL", Decimal("50"), method="specific", specific_lot_ids=[lot2.lot_id]
        )

        assert cost_basis == Decimal("8000.00")  # 50 * 160
        assert len(consumed) == 1
        assert consumed[0].lot_id == lot2.lot_id

    def test_calculate_cost_basis_specific_missing_lot(self):
        accounting = TaxLotAccounting()
        accounting.add_lot("AAPL", date(2024, 1, 10), Decimal("150"), Decimal("100"))

        try:
            accounting.calculate_cost_basis(
                "AAPL", Decimal("50"), method="specific", specific_lot_ids=["LOT-99999999"]
            )
            assert False, "Should raise ValueError"
        except ValueError as e:
            assert "批次不存在" in str(e)

    def test_calculate_cost_basis_specific_no_ids(self):
        accounting = TaxLotAccounting()
        accounting.add_lot("AAPL", date(2024, 1, 10), Decimal("150"), Decimal("100"))

        try:
            accounting.calculate_cost_basis("AAPL", Decimal("50"), method="specific")
            assert False, "Should raise ValueError"
        except ValueError as e:
            assert "必须指定" in str(e)

    def test_calculate_cost_basis_specific_insufficient(self):
        accounting = TaxLotAccounting()
        lot1 = accounting.add_lot("AAPL", date(2024, 1, 10), Decimal("150"), Decimal("30"))

        try:
            accounting.calculate_cost_basis(
                "AAPL", Decimal("100"), method="specific", specific_lot_ids=[lot1.lot_id]
            )
            assert False, "Should raise ValueError"
        except ValueError as e:
            assert "数量不足" in str(e)

    def test_calculate_cost_basis_invalid_method(self):
        accounting = TaxLotAccounting()
        accounting.add_lot("AAPL", date(2024, 1, 10), Decimal("150"), Decimal("100"))

        try:
            accounting.calculate_cost_basis("AAPL", Decimal("50"), method="lifo")  # type: ignore
            assert False, "Should raise ValueError"
        except ValueError as e:
            assert "不支持" in str(e)

    def test_lot_ids_increment(self):
        accounting = TaxLotAccounting()
        lot1 = accounting.add_lot("AAPL", date(2024, 1, 10), Decimal("150"), Decimal("100"))
        lot2 = accounting.add_lot("AAPL", date(2024, 2, 15), Decimal("160"), Decimal("50"))

        assert lot1.lot_id == "LOT-00000001"
        assert lot2.lot_id == "LOT-00000002"

    def test_multiple_symbols(self):
        accounting = TaxLotAccounting()
        accounting.add_lot("AAPL", date(2024, 1, 10), Decimal("150"), Decimal("100"))
        accounting.add_lot("GOOG", date(2024, 1, 10), Decimal("140"), Decimal("50"))

        assert accounting.get_total_quantity("AAPL") == Decimal("100")
        assert accounting.get_total_quantity("GOOG") == Decimal("50")


# ═══════════════════════ TaxReportGenerator ═══════════════════════


class TestTaxReportGenerator:
    def test_create(self):
        gen = TaxReportGenerator()
        assert gen is not None

    def test_add_disposal(self):
        gen = TaxReportGenerator()
        disposal = gen.add_disposal(
            symbol="AAPL",
            sell_date=date(2024, 6, 15),
            sell_price=Decimal("170"),
            quantity=Decimal("100"),
            cost_basis=Decimal("15000"),
            buy_date=date(2024, 1, 10),
        )

        assert isinstance(disposal, DisposalRecord)
        assert disposal.symbol == "AAPL"
        assert disposal.realized_pnl == Decimal("2000")  # 170*100 - 15000
        assert disposal.is_long_term is False  # ~157 days < 365

    def test_add_disposal_long_term(self):
        gen = TaxReportGenerator()
        disposal = gen.add_disposal(
            symbol="AAPL",
            sell_date=date(2025, 6, 15),
            sell_price=Decimal("170"),
            quantity=Decimal("100"),
            cost_basis=Decimal("15000"),
            buy_date=date(2024, 1, 10),
        )

        assert disposal.is_long_term is True  # > 365 days

    def test_generate_annual_report_empty(self):
        gen = TaxReportGenerator()
        report = gen.generate_annual_report(2024)

        assert report["year"] == 2024
        assert report["summary"]["total_disposals"] == 0
        assert report["summary"]["net_total"] == "0.00"

    def test_generate_annual_report_with_disposals(self):
        gen = TaxReportGenerator()
        # Short-term gain
        gen.add_disposal(
            symbol="AAPL",
            sell_date=date(2024, 6, 15),
            sell_price=Decimal("170"),
            quantity=Decimal("100"),
            cost_basis=Decimal("15000"),
            buy_date=date(2024, 1, 10),
        )
        # Short-term loss
        gen.add_disposal(
            symbol="GOOG",
            sell_date=date(2024, 8, 15),
            sell_price=Decimal("120"),
            quantity=Decimal("50"),
            cost_basis=Decimal("7000"),
            buy_date=date(2024, 3, 10),
        )

        report = gen.generate_annual_report(2024)

        assert report["summary"]["total_disposals"] == 2
        assert report["summary"]["short_term_transactions"] == 2
        assert report["summary"]["long_term_transactions"] == 0
        # Gain: 170*100 - 15000 = 2000
        # Loss: 120*50 - 7000 = -1000
        # Net: 2000 + (-1000) = 1000
        assert report["summary"]["net_total"] == "1000.00"

    def test_generate_annual_report_schedule_d(self):
        gen = TaxReportGenerator()
        gen.add_disposal(
            symbol="AAPL",
            sell_date=date(2024, 6, 15),
            sell_price=Decimal("170"),
            quantity=Decimal("100"),
            cost_basis=Decimal("15000"),
            buy_date=date(2024, 1, 10),
        )

        report = gen.generate_annual_report(2024)

        assert "schedule_d" in report
        assert "part_i_short_term" in report["schedule_d"]
        assert "part_ii_long_term" in report["schedule_d"]

    def test_generate_annual_report_form_8949(self):
        gen = TaxReportGenerator()
        gen.add_disposal(
            symbol="AAPL",
            sell_date=date(2024, 6, 15),
            sell_price=Decimal("170"),
            quantity=Decimal("100"),
            cost_basis=Decimal("15000"),
            buy_date=date(2024, 1, 10),
        )

        report = gen.generate_annual_report(2024)

        assert "form_8949" in report
        entries = report["form_8949"]
        assert len(entries) == 1
        assert entries[0]["symbol"] == "AAPL"
        assert "proceeds" in entries[0]
        assert "cost_basis" in entries[0]

    def test_generate_annual_report_filters_year(self):
        gen = TaxReportGenerator()
        gen.add_disposal(
            symbol="AAPL",
            sell_date=date(2024, 6, 15),
            sell_price=Decimal("170"),
            quantity=Decimal("100"),
            cost_basis=Decimal("15000"),
            buy_date=date(2024, 1, 10),
        )
        gen.add_disposal(
            symbol="GOOG",
            sell_date=date(2025, 6, 15),
            sell_price=Decimal("170"),
            quantity=Decimal("100"),
            cost_basis=Decimal("15000"),
            buy_date=date(2024, 1, 10),
        )

        report = gen.generate_annual_report(2024)
        assert report["summary"]["total_disposals"] == 1

    def test_generate_annual_report_wash_sale_summary(self):
        gen = TaxReportGenerator()
        gen.add_disposal(
            symbol="AAPL",
            sell_date=date(2024, 6, 15),
            sell_price=Decimal("170"),
            quantity=Decimal("100"),
            cost_basis=Decimal("15000"),
            buy_date=date(2024, 1, 10),
        )

        report = gen.generate_annual_report(2024)
        assert "wash_sale_summary" in report
        assert "affected_transactions" in report["wash_sale_summary"]

    def test_long_term_vs_short_term_classification(self):
        gen = TaxReportGenerator()
        # Short-term
        gen.add_disposal(
            symbol="A",
            sell_date=date(2024, 6, 1),
            sell_price=Decimal("110"),
            quantity=Decimal("10"),
            cost_basis=Decimal("1000"),
            buy_date=date(2024, 3, 1),
        )
        # Long-term
        gen.add_disposal(
            symbol="B",
            sell_date=date(2025, 3, 1),
            sell_price=Decimal("110"),
            quantity=Decimal("10"),
            cost_basis=Decimal("1000"),
            buy_date=date(2024, 1, 1),
        )

        report = gen.generate_annual_report(2025)
        assert report["summary"]["long_term_transactions"] == 1

    def test_disposal_record_frozen(self):
        gen = TaxReportGenerator()
        disposal = gen.add_disposal(
            symbol="AAPL",
            sell_date=date(2024, 6, 15),
            sell_price=Decimal("170"),
            quantity=Decimal("100"),
            cost_basis=Decimal("15000"),
            buy_date=date(2024, 1, 10),
        )

        try:
            disposal.symbol = "GOOG"  # type: ignore
            assert False, "Should be frozen"
        except Exception:
            pass

    def test_tax_lot_frozen(self):
        accounting = TaxLotAccounting()
        lot = accounting.add_lot("AAPL", date(2024, 1, 10), Decimal("150"), Decimal("100"))

        try:
            lot.symbol = "GOOG"  # type: ignore
            assert False, "Should be frozen"
        except Exception:
            pass

    def test_long_term_threshold(self):
        assert TaxReportGenerator.LONG_TERM_THRESHOLD_DAYS == 365

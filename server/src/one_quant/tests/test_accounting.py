"""
ONE量化 - 账户会计系统测试

测试 AccountLedger、Balance、SettlementEngine。
"""

from __future__ import annotations

import pytest
from decimal import Decimal
from unittest.mock import AsyncMock

from one_quant.accounting.account import (
    AccountLedger,
    Balance,
    PositionLot,
)
from one_quant.accounting.settlement import (
    InsufficientBalanceError,
    InvalidFillError,
    SettlementEngine,
    SettlementMonitor,
)
from one_quant.core.types import Fill, Market


# ──────────────────── 辅助函数 ────────────────────


def make_fill(
    side: str = "buy",
    quantity: str = "1.0",
    price: str = "50000",
    fee: str = "5.0",
    symbol: str = "BTC/USDT",
) -> Fill:
    """创建测试成交。"""
    return Fill(
        order_id="order-001",
        symbol=symbol,
        side=side,
        price=Decimal(price),
        quantity=Decimal(quantity),
        fee=Decimal(fee),
        fee_currency="USDT",
        exchange="binance",
        timestamp_ns=1700000000000000000,
    )


# ──────────────────── Balance 测试 ────────────────────


class TestBalance:
    """余额测试。"""

    def test_initial_balance(self):
        """初始余额为 0。"""
        b = Balance(currency="USDT")
        assert b.available == Decimal("0")
        assert b.frozen == Decimal("0")
        assert b.total == Decimal("0")

    def test_credit(self):
        """入账。"""
        b = Balance(currency="USDT")
        b.credit(Decimal("1000"))
        assert b.available == Decimal("1000")
        assert b.total == Decimal("1000")

    def test_debit(self):
        """扣款。"""
        b = Balance(currency="USDT")
        b.credit(Decimal("1000"))
        b.debit(Decimal("300"))
        assert b.available == Decimal("700")

    def test_debit_insufficient(self):
        """余额不足扣款。"""
        b = Balance(currency="USDT")
        b.credit(Decimal("100"))
        with pytest.raises(ValueError, match="可用余额不足"):
            b.debit(Decimal("200"))

    def test_freeze(self):
        """冻结。"""
        b = Balance(currency="USDT")
        b.credit(Decimal("1000"))
        b.freeze(Decimal("500"))
        assert b.available == Decimal("500")
        assert b.frozen == Decimal("500")
        assert b.total == Decimal("1000")

    def test_freeze_insufficient(self):
        """冻结超出可用。"""
        b = Balance(currency="USDT")
        b.credit(Decimal("100"))
        with pytest.raises(ValueError, match="可用余额不足"):
            b.freeze(Decimal("200"))

    def test_unfreeze(self):
        """解冻。"""
        b = Balance(currency="USDT")
        b.credit(Decimal("1000"))
        b.freeze(Decimal("500"))
        b.unfreeze(Decimal("300"))
        assert b.available == Decimal("800")
        assert b.frozen == Decimal("200")

    def test_unfreeze_insufficient(self):
        """解冻超出冻结。"""
        b = Balance(currency="USDT")
        b.credit(Decimal("1000"))
        b.freeze(Decimal("500"))
        with pytest.raises(ValueError, match="冻结余额不足"):
            b.unfreeze(Decimal("600"))

    def test_negative_amount_rejected(self):
        """负金额被拒绝。"""
        b = Balance(currency="USDT")
        with pytest.raises(ValueError):
            b.credit(Decimal("-100"))
        with pytest.raises(ValueError):
            b.debit(Decimal("-100"))
        with pytest.raises(ValueError):
            b.freeze(Decimal("-100"))


# ──────────────────── AccountLedger 测试 ────────────────────


class TestAccountLedger:
    """账户总账测试。"""

    def test_deposit(self):
        """入金。"""
        ledger = AccountLedger("test")
        ledger.deposit("USDT", Decimal("100000"))

        balance = ledger.get_balance("USDT")
        assert balance.available == Decimal("100000")

    def test_withdraw(self):
        """出金。"""
        ledger = AccountLedger("test")
        ledger.deposit("USDT", Decimal("100000"))
        ledger.withdraw("USDT", Decimal("30000"))

        balance = ledger.get_balance("USDT")
        assert balance.available == Decimal("70000")

    def test_withdraw_insufficient(self):
        """余额不足出金。"""
        ledger = AccountLedger("test")
        ledger.deposit("USDT", Decimal("100"))

        with pytest.raises(ValueError, match="可用余额不足"):
            ledger.withdraw("USDT", Decimal("200"))

    def test_deposit_negative_rejected(self):
        """负金额入金被拒绝。"""
        ledger = AccountLedger("test")
        with pytest.raises(ValueError, match="入金金额必须大于 0"):
            ledger.deposit("USDT", Decimal("-100"))

    def test_process_buy_fill(self):
        """处理买入成交。"""
        ledger = AccountLedger("test")
        ledger.deposit("USDT", Decimal("100000"))

        fill = make_fill(side="buy", quantity="1.0", price="50000", fee="5")
        ledger.process_fill(fill)

        # 余额减少 50000 + 5 = 50005
        balance = ledger.get_balance("USDT")
        assert balance.available == Decimal("49995")

        # 持仓增加
        qty = ledger.get_position_quantity("BTC/USDT")
        assert qty == Decimal("1.0")

    def test_process_sell_fill(self):
        """处理卖出成交（FIFO）。"""
        ledger = AccountLedger("test")
        ledger.deposit("USDT", Decimal("100000"))

        # 买入
        buy_fill = make_fill(side="buy", quantity="1.0", price="50000", fee="5")
        ledger.process_fill(buy_fill)

        # 卖出
        sell_fill = make_fill(side="sell", quantity="1.0", price="55000", fee="5.5")
        ledger.process_fill(sell_fill)

        # 持仓清空
        qty = ledger.get_position_quantity("BTC/USDT")
        assert qty == Decimal("0")

        # 余额 = 100000 - 50005 + 55000 - 5.5 = 104989.5
        balance = ledger.get_balance("USDT")
        assert balance.available == Decimal("104989.5")

    def test_fifo_cost_basis(self):
        """FIFO 成本法。"""
        ledger = AccountLedger("test")
        ledger.deposit("USDT", Decimal("200000"))

        # 第一批买入 @ 40000
        fill1 = make_fill(side="buy", quantity="1.0", price="40000", fee="4")
        ledger.process_fill(fill1)

        # 第二批买入 @ 50000
        fill2 = make_fill(side="buy", quantity="1.0", price="50000", fee="5")
        ledger.process_fill(fill2)

        # 平均价 = (40000 + 50000) / 2 = 45000
        avg = ledger.get_avg_entry_price("BTC/USDT")
        assert avg == Decimal("45000")

        # 卖出 1 个（消耗第一批 @ 40000）
        sell_fill = make_fill(side="sell", quantity="1.0", price="60000", fee="6")
        ledger.process_fill(sell_fill)

        # 剩余持仓均价 = 50000
        remaining_qty = ledger.get_position_quantity("BTC/USDT")
        assert remaining_qty == Decimal("1.0")

        avg_after = ledger.get_avg_entry_price("BTC/USDT")
        assert avg_after == Decimal("50000")

    def test_get_all_balances(self):
        """获取所有余额。"""
        ledger = AccountLedger("test")
        ledger.deposit("USDT", Decimal("10000"))
        ledger.deposit("BTC", Decimal("1"))

        balances = ledger.get_all_balances()
        assert len(balances) == 2

    def test_get_all_positions(self):
        """获取所有持仓。"""
        ledger = AccountLedger("test")
        ledger.deposit("USDT", Decimal("100000"))

        fill = make_fill(side="buy", quantity="1.0", price="50000")
        ledger.process_fill(fill)

        positions = ledger.get_all_positions()
        assert "BTC/USDT" in positions
        assert positions["BTC/USDT"] == Decimal("1.0")

    def test_get_equity(self):
        """计算账户权益。"""
        ledger = AccountLedger("test")
        ledger.deposit("USDT", Decimal("100000"))

        # 买入（默认手续费 5 USDT）
        fill = make_fill(side="buy", quantity="1.0", price="50000", fee="5")
        ledger.process_fill(fill)

        # 权益 = 余额 + 未实现盈亏
        # 余额 = 100000 - 50000 - 5 = 49995
        # 当前价格 60000，未实现盈亏 = (60000 - 50000) * 1 = 10000
        equity = ledger.get_equity({"BTC/USDT": Decimal("60000")})
        assert equity == Decimal("59995")  # 49995 + 10000

    def test_position_symbols(self):
        """有持仓的标的列表。"""
        ledger = AccountLedger("test")
        ledger.deposit("USDT", Decimal("100000"))

        fill = make_fill(side="buy", quantity="1.0", price="50000")
        ledger.process_fill(fill)

        assert "BTC/USDT" in ledger.position_symbols

    def test_entry_count(self):
        """账本记录计数。"""
        ledger = AccountLedger("test")
        ledger.deposit("USDT", Decimal("100000"))

        initial_count = ledger.entry_count

        fill = make_fill(side="buy", quantity="1.0", price="50000", fee="5")
        ledger.process_fill(fill)

        # 至少增加 2 条记录（扣款 + 手续费）
        assert ledger.entry_count >= initial_count + 2


# ──────────────────── SettlementEngine 测试 ────────────────────


class TestSettlementEngine:
    """结算引擎测试。"""

    @pytest.mark.asyncio
    async def test_settle_buy(self):
        """结算买入成交。"""
        ledger = AccountLedger("test")
        ledger.deposit("USDT", Decimal("100000"))

        engine = SettlementEngine(ledger)
        fill = make_fill(side="buy", quantity="1.0", price="50000", fee="5")

        fee_entry = await engine.settle(fill)

        assert ledger.get_position_quantity("BTC/USDT") == Decimal("1.0")
        assert fee_entry is not None

    @pytest.mark.asyncio
    async def test_settle_sell(self):
        """结算卖出成交。"""
        ledger = AccountLedger("test")
        ledger.deposit("USDT", Decimal("100000"))

        engine = SettlementEngine(ledger)

        # 先买入
        buy_fill = make_fill(side="buy", quantity="1.0", price="50000")
        await engine.settle(buy_fill)

        # 再卖出
        sell_fill = make_fill(side="sell", quantity="1.0", price="55000")
        await engine.settle(sell_fill)

        assert ledger.get_position_quantity("BTC/USDT") == Decimal("0")

    @pytest.mark.asyncio
    async def test_settle_invalid_fill(self):
        """无效成交校验。"""
        ledger = AccountLedger("test")
        engine = SettlementEngine(ledger)

        # 数量为 0
        fill = make_fill(quantity="0")
        with pytest.raises(InvalidFillError, match="成交数量必须大于 0"):
            await engine.settle(fill)

    @pytest.mark.asyncio
    async def test_settle_negative_price(self):
        """负价格校验。"""
        ledger = AccountLedger("test")
        engine = SettlementEngine(ledger)

        fill = make_fill(price="-100")
        with pytest.raises(InvalidFillError, match="成交价格不能为负"):
            await engine.settle(fill)

    @pytest.mark.asyncio
    async def test_settle_batch(self):
        """批量结算。"""
        ledger = AccountLedger("test")
        ledger.deposit("USDT", Decimal("200000"))

        engine = SettlementEngine(ledger)

        fills = [
            make_fill(side="buy", quantity="0.5", price="50000"),
            make_fill(side="buy", quantity="0.5", price="51000"),
        ]

        results = await engine.settle_batch(fills)
        assert len(results) == 2
        assert ledger.get_position_quantity("BTC/USDT") == Decimal("1.0")

    @pytest.mark.asyncio
    async def test_settle_with_event_bus(self):
        """带事件总线的结算。"""
        ledger = AccountLedger("test")
        ledger.deposit("USDT", Decimal("100000"))

        event_bus = AsyncMock()
        engine = SettlementEngine(ledger, event_bus)

        fill = make_fill(side="buy", quantity="1.0", price="50000")
        await engine.settle(fill)

        # 验证事件发布
        event_bus.publish.assert_called_once()
        call_args = event_bus.publish.call_args
        assert call_args[0][0] == "settlement"

    @pytest.mark.asyncio
    async def test_settle_stats(self):
        """结算统计。"""
        ledger = AccountLedger("test")
        ledger.deposit("USDT", Decimal("100000"))

        engine = SettlementEngine(ledger)

        fill = make_fill(side="buy", quantity="1.0", price="50000", fee="5")
        await engine.settle(fill)

        stats = engine.stats
        assert stats["settle_count"] == 1
        assert Decimal(stats["total_volume"]) == Decimal("50000")
        assert Decimal(stats["total_fees"]) == Decimal("5")


# ──────────────────── SettlementMonitor 测试 ────────────────────


class TestSettlementMonitor:
    """结算监控测试。"""

    def test_record_settlement(self):
        """记录结算耗时。"""
        monitor = SettlementMonitor()
        monitor.record_settlement(1_000_000)  # 1ms
        monitor.record_settlement(2_000_000)  # 2ms

        assert monitor.avg_settlement_time_ms == 1.5
        assert len(monitor._settlement_times) == 2

    def test_record_error(self):
        """记录错误。"""
        monitor = SettlementMonitor()
        fill = make_fill()
        monitor.record_error(fill, Exception("测试错误"))

        assert monitor.error_count == 1
        assert len(monitor.recent_errors) == 1

    def test_max_history(self):
        """历史记录上限。"""
        monitor = SettlementMonitor(max_history=5)

        for i in range(10):
            monitor.record_settlement(i * 1_000_000)

        assert len(monitor._settlement_times) == 5

    def test_stats(self):
        """统计信息。"""
        monitor = SettlementMonitor()
        monitor.record_settlement(1_000_000)

        stats = monitor.stats
        assert stats["settlement_count"] == 1
        assert stats["avg_time_ms"] == 1.0
        assert stats["error_count"] == 0

    def test_p99_empty(self):
        """空数据 P99。"""
        monitor = SettlementMonitor()
        assert monitor.p99_settlement_time_ms == 0.0

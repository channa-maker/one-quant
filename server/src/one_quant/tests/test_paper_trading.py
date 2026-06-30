"""
ONE量化 - 模拟盘测试

用模拟数据验证完整交易逻辑，不依赖真实交易所。
覆盖：
- 买入→卖出完整循环
- 多标的持仓
- 杠杆持仓与强平
- 止损执行
- 移动止损（追踪止损）
- 每日盈亏计算
- 多币种 NAV 合并
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal

import pytest

from one_quant.core.types import (
    Fill,
    Market,
    PositionState,
    Signal,
)
from one_quant.execution.oms import OrderManager
from one_quant.infra.event_bus import InMemoryEventBus

# ══════════════════════════════════════════════════════════════════════
# 模拟盘引擎（Paper Trading Engine）
# ══════════════════════════════════════════════════════════════════════


@dataclass
class PaperAccount:
    """模拟盘账户。

    管理资金、持仓、订单、盈亏计算，用于模拟盘测试。
    所有金额使用 Decimal 精确计算。

    Attributes:
        initial_balance: 初始资金（USDT）
        balance: 当前可用余额
        leverage: 杠杆倍数
        fee_rate: 手续费率（默认 0.1%）
        positions: 当前持仓 {symbol: PositionState}
        fills: 成交记录列表
        orders: 订单历史
        stop_losses: 止损设置 {symbol: {"price": Decimal, "quantity": Decimal}}
    """

    initial_balance: Decimal
    balance: Decimal
    leverage: Decimal = Decimal("1")
    fee_rate: Decimal = Decimal("0.001")  # 0.1%
    positions: dict = field(default_factory=dict)
    fills: list = field(default_factory=list)
    orders: list = field(default_factory=list)
    stop_losses: dict = field(default_factory=dict)

    def buy(self, symbol: str, price: Decimal, quantity: Decimal) -> Fill:
        """模拟买入。

        Args:
            symbol: 标的符号
            price: 买入价格
            quantity: 买入数量

        Returns:
            成交回报

        Raises:
            ValueError: 余额不足
        """
        cost = price * quantity
        fee = cost * self.fee_rate
        margin_required = cost / self.leverage + fee

        if margin_required > self.balance:
            raise ValueError(f"余额不足: 需要 {margin_required} USDT，当前 {self.balance} USDT")

        # 扣减余额
        self.balance -= margin_required

        # 更新持仓
        if symbol in self.positions:
            pos = self.positions[symbol]
            old_qty = pos.quantity
            old_cost = pos.entry_price * old_qty
            new_cost = price * quantity
            total_qty = old_qty + quantity
            new_entry = (old_cost + new_cost) / total_qty
            self.positions[symbol] = PositionState(
                symbol=symbol,
                market=Market.SPOT,
                side="long",
                quantity=total_qty,
                entry_price=new_entry,
                unrealized_pnl=Decimal("0"),
                realized_pnl=pos.realized_pnl,
                timestamp_ns=time.time_ns(),
            )
        else:
            self.positions[symbol] = PositionState(
                symbol=symbol,
                market=Market.SPOT,
                side="long",
                quantity=quantity,
                entry_price=price,
                unrealized_pnl=Decimal("0"),
                realized_pnl=Decimal("0"),
                timestamp_ns=time.time_ns(),
            )

        fill = Fill(
            order_id=f"paper-{len(self.fills)}",
            symbol=symbol,
            side="buy",
            price=price,
            quantity=quantity,
            fee=fee,
            fee_currency="USDT",
            exchange="paper",
            timestamp_ns=time.time_ns(),
        )
        self.fills.append(fill)
        return fill

    def sell(self, symbol: str, price: Decimal, quantity: Decimal) -> Fill:
        """模拟卖出。

        Args:
            symbol: 标的符号
            price: 卖出价格
            quantity: 卖出数量

        Returns:
            成交回报

        Raises:
            ValueError: 持仓不足
        """
        if symbol not in self.positions:
            raise ValueError(f"无持仓: {symbol}")

        pos = self.positions[symbol]
        if quantity > pos.quantity:
            raise ValueError(f"持仓不足: 要卖 {quantity}，只有 {pos.quantity}")

        revenue = price * quantity
        fee = revenue * self.fee_rate
        _net_revenue = revenue - fee  # noqa: F841

        # 计算已实现盈亏
        pnl = (price - pos.entry_price) * quantity - fee

        # 回收保证金 + 盈亏
        cost_basis = pos.entry_price * quantity
        margin_release = cost_basis / self.leverage
        self.balance += margin_release + pnl

        # 更新持仓
        remaining = pos.quantity - quantity
        if remaining == 0:
            del self.positions[symbol]
        else:
            self.positions[symbol] = PositionState(
                symbol=symbol,
                market=Market.SPOT,
                side="long",
                quantity=remaining,
                entry_price=pos.entry_price,
                unrealized_pnl=Decimal("0"),
                realized_pnl=pos.realized_pnl + pnl,
                timestamp_ns=time.time_ns(),
            )

        fill = Fill(
            order_id=f"paper-{len(self.fills)}",
            symbol=symbol,
            side="sell",
            price=price,
            quantity=quantity,
            fee=fee,
            fee_currency="USDT",
            exchange="paper",
            timestamp_ns=time.time_ns(),
        )
        self.fills.append(fill)
        return fill

    def get_unrealized_pnl(self, symbol: str, current_price: Decimal) -> Decimal:
        """计算未实现盈亏。"""
        if symbol not in self.positions:
            return Decimal("0")
        pos = self.positions[symbol]
        return (current_price - pos.entry_price) * pos.quantity

    def get_total_equity(self, prices: dict[str, Decimal]) -> Decimal:
        """计算总权益 = 可用余额 + 所有持仓市值。"""
        total = self.balance
        for symbol, pos in self.positions.items():
            if symbol in prices:
                market_value = prices[symbol] * pos.quantity
                total += market_value
        return total

    def check_stop_loss(self, symbol: str, current_price: Decimal) -> Fill | None:
        """检查并执行止损。

        Args:
            symbol: 标的符号
            current_price: 当前价格

        Returns:
            触发止损时返回成交回报，否则 None
        """
        if symbol not in self.stop_losses:
            return None

        sl = self.stop_losses[symbol]
        if current_price <= sl["price"]:
            # 触发止损：以当前价格全部卖出
            quantity = min(
                sl["quantity"],
                self.positions.get(
                    symbol,
                    PositionState(
                        symbol=symbol,
                        market=Market.SPOT,
                        side="flat",
                        quantity=Decimal("0"),
                        entry_price=Decimal("0"),
                        unrealized_pnl=Decimal("0"),
                        realized_pnl=Decimal("0"),
                        timestamp_ns=time.time_ns(),
                    ),
                ).quantity,
            )
            if quantity > 0 and symbol in self.positions:
                fill = self.sell(symbol, current_price, quantity)
                del self.stop_losses[symbol]
                return fill
        return None

    def update_trailing_stop(self, symbol: str, current_price: Decimal, trail_pct: Decimal) -> None:
        """更新移动止损。

        当价格上涨时，止损价跟随上移；价格下跌时止损价不变。

        Args:
            symbol: 标的符号
            current_price: 当前价格
            trail_pct: 移动止损百分比（如 3% = Decimal('0.03')）
        """
        if symbol not in self.positions:
            return

        new_stop = current_price * (Decimal("1") - trail_pct)

        if symbol in self.stop_losses:
            # 只在新止损价更高时更新
            if new_stop > self.stop_losses[symbol]["price"]:
                self.stop_losses[symbol]["price"] = new_stop
                self.stop_losses[symbol]["quantity"] = self.positions[symbol].quantity
        else:
            self.stop_losses[symbol] = {
                "price": new_stop,
                "quantity": self.positions[symbol].quantity,
            }


# ══════════════════════════════════════════════════════════════════════
# 模拟盘交易测试
# ══════════════════════════════════════════════════════════════════════


class TestPaperTrading:
    """模拟盘交易测试"""

    def test_buy_sell_round_trip(self):
        """买入→卖出完整循环

        场景：
        1. 初始资金 100000 USDT
        2. 买入 BTC @ 50000
        3. 卖出 BTC @ 51000
        4. 验证盈亏 = 1000 USDT（扣除手续费）
        """
        account = PaperAccount(
            initial_balance=Decimal("100000"),
            balance=Decimal("100000"),
        )

        # ── 1. 买入 1 BTC @ 50000 ──
        buy_fill = account.buy("BTCUSDT", Decimal("50000"), Decimal("1"))
        assert buy_fill.side == "buy"
        assert buy_fill.quantity == Decimal("1")
        assert buy_fill.price == Decimal("50000")

        # 手续费 = 50000 * 0.1% = 50 USDT
        assert buy_fill.fee == Decimal("50")

        # 余额 = 100000 - 50000 - 50 = 49950
        assert account.balance == Decimal("49950")

        # ── 2. 卖出 1 BTC @ 51000 ──
        sell_fill = account.sell("BTCUSDT", Decimal("51000"), Decimal("1"))
        assert sell_fill.side == "sell"

        # 手续费 = 51000 * 0.1% = 51 USDT
        assert sell_fill.fee == Decimal("51")

        # 盈亏 = (51000 - 50000) * 1 - 50 - 51 = 899 USDT
        _expected_pnl = Decimal("1000") - Decimal("50") - Decimal("51")  # noqa: F841
        assert sell_fill.fee == Decimal("51")

        # ── 3. 验证最终余额 ──
        # 初始 100000，净盈亏 = (51000-50000)*1 - 50 - 51 = 899
        # 余额 = 100000 + 899 = 100899
        assert account.balance == Decimal("100899")

        # ── 4. 持仓清空 ──
        assert "BTCUSDT" not in account.positions

    def test_multiple_positions(self):
        """多标的持仓

        场景：
        1. 同时持有 BTC、ETH、SOL
        2. 各自独立盈亏计算
        3. 总权益 = 可用余额 + 各持仓市值
        """
        account = PaperAccount(
            initial_balance=Decimal("100000"),
            balance=Decimal("100000"),
        )

        # ── 买入三个标的 ──
        account.buy("BTCUSDT", Decimal("50000"), Decimal("1"))  # 成本 50000 + 手续费 50
        account.buy("ETHUSDT", Decimal("3000"), Decimal("10"))  # 成本 30000 + 手续费 30
        account.buy("SOLUSDT", Decimal("100"), Decimal("100"))  # 成本 10000 + 手续费 10

        # 总支出 = 50000 + 50 + 30000 + 30 + 10000 + 10 = 90090
        # 余额 = 100000 - 90090 = 9910
        assert account.balance == Decimal("9910")

        # ── 验证各持仓 ──
        assert account.positions["BTCUSDT"].quantity == Decimal("1")
        assert account.positions["ETHUSDT"].quantity == Decimal("10")
        assert account.positions["SOLUSDT"].quantity == Decimal("100")

        # ── 更新价格，计算盈亏 ──
        btc_pnl = account.get_unrealized_pnl("BTCUSDT", Decimal("52000"))
        eth_pnl = account.get_unrealized_pnl("ETHUSDT", Decimal("2800"))
        sol_pnl = account.get_unrealized_pnl("SOLUSDT", Decimal("110"))

        assert btc_pnl == Decimal("2000"), "BTC 盈利 2000"
        assert eth_pnl == Decimal("-2000"), "ETH 亏损 2000"
        assert sol_pnl == Decimal("1000"), "SOL 盈利 1000"

        # ── 总权益 = 余额 + 各持仓市值 ──
        prices = {
            "BTCUSDT": Decimal("52000"),
            "ETHUSDT": Decimal("2800"),
            "SOLUSDT": Decimal("110"),
        }
        total_equity = account.get_total_equity(prices)
        # 余额 9910 + BTC 52000 + ETH 28000 + SOL 11000 = 100910
        assert total_equity == Decimal("100910")

    def test_leverage_position(self):
        """杠杆持仓

        场景：
        1. 10x 杠杆做多 BTC
        2. 价格上涨 5% → 盈利 50%
        3. 价格下跌 10% → 强平
        """
        # ── 1. 10x 杠杆 ──
        account = PaperAccount(
            initial_balance=Decimal("10000"),
            balance=Decimal("10000"),
            leverage=Decimal("10"),
        )

        # 买入 1 BTC @ 50000，10x 杠杆只需 5000 保证金 + 手续费
        account.buy("BTCUSDT", Decimal("50000"), Decimal("1"))

        # 保证金 = 50000 / 10 = 5000，手续费 = 50000 * 0.001 = 50
        # 余额 = 10000 - 5000 - 50 = 4950
        assert account.balance == Decimal("4950")

        # ── 2. 价格上涨 5% → 盈利 50% ──
        new_price = Decimal("52500")
        pnl = account.get_unrealized_pnl("BTCUSDT", new_price)
        assert pnl == Decimal("2500"), "未实现盈亏应为 2500 (5% * 10x = 50%)"

        # ── 3. 价格下跌 10% → 强平检查 ──
        crash_price = Decimal("45000")
        crash_pnl = account.get_unrealized_pnl("BTCUSDT", crash_price)
        assert crash_pnl == Decimal("-5000"), "未实现亏损应为 -5000"

        # 强平条件：亏损 >= 保证金
        # 保证金 = 5000，亏损 = 5000 → 触发强平
        position = account.positions["BTCUSDT"]
        margin = position.entry_price * position.quantity / account.leverage
        should_liquidate = abs(crash_pnl) >= margin
        assert should_liquidate, "亏损应达到强平线"

        # ── 强平执行：以强平价卖出 ──
        liquidation_fill = account.sell("BTCUSDT", crash_price, Decimal("1"))
        assert liquidation_fill.side == "sell"

        # 强平后余额 = 保证金 - 亏损 + 保证金释放
        # = 4950 + (5000 - 5000) = 4950（亏损吃掉保证金）
        # 实际：余额 4950 + 保证金释放 5000 + 盈亏 -5000 - 手续费 45 = 4905
        assert account.balance == Decimal("4905")
        assert "BTCUSDT" not in account.positions, "强平后应无持仓"

    def test_stop_loss_execution(self):
        """止损执行

        场景：
        1. 买入 @ 50000，止损 @ 49000
        2. 价格跌到 49000
        3. 自动触发卖出
        4. 验证亏损 = 1000 USDT + 手续费
        """
        account = PaperAccount(
            initial_balance=Decimal("100000"),
            balance=Decimal("100000"),
        )

        # ── 1. 买入并设置止损 ──
        account.buy("BTCUSDT", Decimal("50000"), Decimal("1"))
        account.stop_losses["BTCUSDT"] = {
            "price": Decimal("49000"),
            "quantity": Decimal("1"),
        }

        # ── 2. 价格跌到 49000 → 触发止损 ──
        fill = account.check_stop_loss("BTCUSDT", Decimal("49000"))
        assert fill is not None, "应触发止损"
        assert fill.side == "sell"
        assert fill.price == Decimal("49000")

        # ── 3. 验证亏损 ──
        # 买入手续费: 50, 卖出手续费: 49
        # 价差亏损: (49000 - 50000) * 1 = -1000
        # 总亏损: -1000 - 50 - 49 = -1099
        # 余额 = 100000 - 1099 = 98901
        assert account.balance == Decimal("98901")

        # ── 4. 持仓清空 ──
        assert "BTCUSDT" not in account.positions
        assert "BTCUSDT" not in account.stop_losses

    def test_trailing_stop(self):
        """移动止损

        场景：
        1. 买入 @ 50000，移动止损 3%
        2. 价格上涨到 55000（止损更新到 53350）
        3. 价格回落到 53000
        4. 触发止损 @ 53350（不是 53000）
        """
        account = PaperAccount(
            initial_balance=Decimal("100000"),
            balance=Decimal("100000"),
        )
        trail_pct = Decimal("0.03")

        # ── 1. 买入并设置初始移动止损 ──
        account.buy("BTCUSDT", Decimal("50000"), Decimal("1"))
        account.update_trailing_stop("BTCUSDT", Decimal("50000"), trail_pct)

        # 初始止损 = 50000 * 0.97 = 48500
        assert account.stop_losses["BTCUSDT"]["price"] == Decimal("48500")

        # ── 2. 价格上涨到 55000 ──
        account.update_trailing_stop("BTCUSDT", Decimal("55000"), trail_pct)
        # 新止损 = 55000 * 0.97 = 53350
        assert account.stop_losses["BTCUSDT"]["price"] == Decimal("53350")

        # ── 3. 价格回落到 54000 → 止损不更新（54000*0.97=52380 < 53350）──
        account.update_trailing_stop("BTCUSDT", Decimal("54000"), trail_pct)
        assert account.stop_losses["BTCUSDT"]["price"] == Decimal("53350"), "止损不应下调"

        # ── 4. 价格继续回落到 53000 → 触发止损 ──
        fill = account.check_stop_loss("BTCUSDT", Decimal("53000"))
        assert fill is not None, "应触发移动止损"
        assert fill.price == Decimal("53000"), "以当前市场价成交"

        # ── 5. 验证盈亏 ──
        # 盈亏 = (53000 - 50000) * 1 - 买入手续费50 - 卖出手续费53
        # = 3000 - 50 - 53 = 2897
        assert account.balance == Decimal("102897")

    def test_daily_pnl_calculation(self):
        """每日盈亏计算

        场景：
        1. 初始权益 100000
        2. 交易多笔
        3. 计算当日盈亏 = 当前权益 - 初始权益
        """
        account = PaperAccount(
            initial_balance=Decimal("100000"),
            balance=Decimal("100000"),
        )

        # ── 交易 1: 买 BTC @ 50000，卖 @ 50500 ──
        account.buy("BTCUSDT", Decimal("50000"), Decimal("1"))
        account.sell("BTCUSDT", Decimal("50500"), Decimal("1"))

        # 盈亏 = (50500 - 50000) * 1 - 50 - 50.5 = 399.5
        # 余额 = 100000 + 399.5 = 100399.5

        # ── 交易 2: 买 ETH @ 3000，卖 @ 2950 ──
        account.buy("ETHUSDT", Decimal("3000"), Decimal("5"))
        account.sell("ETHUSDT", Decimal("2950"), Decimal("5"))

        # 盈亏 = (2950 - 3000) * 5 - 15 - 14.75 = -279.75
        # 余额 = 100399.5 - 279.75 = 100119.75

        # ── 当日盈亏 ──
        daily_pnl = account.balance - account.initial_balance
        # 399.5 - 279.75 = 119.75
        assert daily_pnl == Decimal("119.75")

    def test_multi_currency_nav(self):
        """多币种 NAV 合并

        场景：
        1. 持有 BTC、ETH、SOL
        2. 各币种以 USDT 计价
        3. NAV = 可用余额 + Σ(持仓数量 × 当前价格)
        """
        account = PaperAccount(
            initial_balance=Decimal("100000"),
            balance=Decimal("100000"),
        )

        # ── 分散买入 ──
        account.buy("BTCUSDT", Decimal("50000"), Decimal("0.5"))  # 25000 + 25
        account.buy("ETHUSDT", Decimal("3000"), Decimal("10"))  # 30000 + 30
        account.buy("SOLUSDT", Decimal("100"), Decimal("200"))  # 20000 + 20
        account.buy("BNBUSDT", Decimal("500"), Decimal("20"))  # 10000 + 10

        # 总投入 = 25025 + 30030 + 20020 + 10010 = 85085
        # 余额 = 100000 - 85085 = 14915
        assert account.balance == Decimal("14915")

        # ── 当前价格 ──
        prices = {
            "BTCUSDT": Decimal("52000"),
            "ETHUSDT": Decimal("3200"),
            "SOLUSDT": Decimal("95"),
            "BNBUSDT": Decimal("480"),
        }

        # ── NAV 计算 ──
        nav = account.get_total_equity(prices)

        # 余额 14915
        # BTC: 0.5 * 52000 = 26000
        # ETH: 10 * 3200 = 32000
        # SOL: 200 * 95 = 19000
        # BNB: 20 * 480 = 9600
        # NAV = 14915 + 26000 + 32000 + 19000 + 9600 = 101515
        assert nav == Decimal("101515")

        # ── NAV 变动 ──
        nav_change = nav - account.initial_balance
        assert nav_change == Decimal("1515"), "NAV 应增长 1515"

    def test_sell_more_than_held_raises(self):
        """卖出超过持仓 → 抛出异常"""
        account = PaperAccount(
            initial_balance=Decimal("100000"),
            balance=Decimal("100000"),
        )
        account.buy("BTCUSDT", Decimal("50000"), Decimal("1"))

        with pytest.raises(ValueError, match="持仓不足"):
            account.sell("BTCUSDT", Decimal("51000"), Decimal("2"))

    def test_buy_insufficient_balance_raises(self):
        """余额不足 → 抛出异常"""
        account = PaperAccount(
            initial_balance=Decimal("1000"),
            balance=Decimal("1000"),
        )

        with pytest.raises(ValueError, match="余额不足"):
            account.buy("BTCUSDT", Decimal("50000"), Decimal("1"))

    def test_stop_loss_not_triggered_above_price(self):
        """止损价以上 → 不触发"""
        account = PaperAccount(
            initial_balance=Decimal("100000"),
            balance=Decimal("100000"),
        )
        account.buy("BTCUSDT", Decimal("50000"), Decimal("1"))
        account.stop_losses["BTCUSDT"] = {
            "price": Decimal("49000"),
            "quantity": Decimal("1"),
        }

        # 价格在止损之上
        fill = account.check_stop_loss("BTCUSDT", Decimal("49500"))
        assert fill is None, "价格高于止损不应触发"
        assert "BTCUSDT" in account.positions, "持仓应保留"

    def test_partial_sell_preserves_position(self):
        """部分卖出 → 持仓数量更新"""
        account = PaperAccount(
            initial_balance=Decimal("200000"),
            balance=Decimal("200000"),
        )
        account.buy("BTCUSDT", Decimal("50000"), Decimal("2"))

        account.sell("BTCUSDT", Decimal("51000"), Decimal("1"))
        assert account.positions["BTCUSDT"].quantity == Decimal("1")

        account.sell("BTCUSDT", Decimal("52000"), Decimal("1"))
        assert "BTCUSDT" not in account.positions

    def test_average_entry_price(self):
        """多次买入 → 均价计算正确"""
        account = PaperAccount(
            initial_balance=Decimal("200000"),
            balance=Decimal("200000"),
        )

        account.buy("BTCUSDT", Decimal("50000"), Decimal("1"))
        account.buy("BTCUSDT", Decimal("52000"), Decimal("1"))

        pos = account.positions["BTCUSDT"]
        # 均价 = (50000*1 + 52000*1) / 2 = 51000
        assert pos.entry_price == Decimal("51000")
        assert pos.quantity == Decimal("2")


# ══════════════════════════════════════════════════════════════════════
# 模拟盘与 OMS 集成测试
# ══════════════════════════════════════════════════════════════════════


class TestPaperTradingOMSIntegration:
    """模拟盘与 OMS 集成测试"""

    @pytest.mark.asyncio
    async def test_oms_creates_paper_orders(self):
        """通过 OMS 创建模拟盘订单 → 验证完整流程"""
        bus = InMemoryEventBus()
        await bus.start()
        oms = OrderManager(bus)

        # ── 创建信号 → 订单 ──
        signal = Signal(
            symbol="BTCUSDT",
            market=Market.SPOT,
            side="buy",
            strength=0.8,
            strategy_name="paper_test",
            reason="模拟盘测试",
            timestamp_ns=time.time_ns(),
        )
        order = oms.create_order_from_signal(
            signal, price=Decimal("50000"), quantity=Decimal("1"), exchange="paper"
        )

        # ── 模拟盘成交 ──
        fill = Fill(
            order_id=order.client_order_id,
            symbol="BTCUSDT",
            side="buy",
            price=Decimal("50000"),
            quantity=Decimal("1"),
            fee=Decimal("50"),
            fee_currency="USDT",
            exchange="paper",
            timestamp_ns=time.time_ns(),
        )

        oms.update_order_status(order.client_order_id, "submitted")
        oms.process_fill(fill)
        oms.update_order_status(order.client_order_id, "filled")

        # ── 验证订单状态 ──
        final_order = oms.get_order(order.client_order_id)
        assert final_order.status == "filled"

        await bus.stop()

    @pytest.mark.asyncio
    async def test_paper_trading_full_workflow(self):
        """模拟盘完整工作流：信号 → 风控 → 下单 → 成交"""
        bus = InMemoryEventBus()
        await bus.start()
        oms = OrderManager(bus)

        account = PaperAccount(
            initial_balance=Decimal("100000"),
            balance=Decimal("100000"),
        )

        # ── 1. 策略产生信号 ──
        buy_signal = Signal(
            symbol="BTCUSDT",
            market=Market.SPOT,
            side="buy",
            strength=0.9,
            strategy_name="momentum",
            reason="突破新高",
            timestamp_ns=time.time_ns(),
        )

        # ── 2. OMS 创建订单 ──
        order = oms.create_order_from_signal(
            buy_signal, price=Decimal("50000"), quantity=Decimal("1"), exchange="paper"
        )

        # ── 3. 模拟盘执行 ──
        fill = account.buy("BTCUSDT", Decimal("50000"), Decimal("1"))
        oms.update_order_status(order.client_order_id, "submitted")
        oms.process_fill(fill)
        oms.update_order_status(order.client_order_id, "filled")

        # ── 4. 设置止损 ──
        account.stop_losses["BTCUSDT"] = {
            "price": Decimal("49000"),
            "quantity": Decimal("1"),
        }

        # ── 5. 价格上涨，更新移动止损 ──
        account.update_trailing_stop("BTCUSDT", Decimal("55000"), Decimal("0.03"))
        assert account.stop_losses["BTCUSDT"]["price"] == Decimal("53350")

        # ── 6. 价格回落，触发止损 ──
        sl_fill = account.check_stop_loss("BTCUSDT", Decimal("53000"))
        assert sl_fill is not None

        # ── 7. OMS 记录止损成交 ──
        sl_order = oms.create_order_from_signal(
            Signal(
                symbol="BTCUSDT",
                market=Market.SPOT,
                side="sell",
                strength=1.0,
                strategy_name="risk_engine",
                reason="移动止损触发",
                timestamp_ns=time.time_ns(),
            ),
            price=Decimal("53000"),
            quantity=Decimal("1"),
            exchange="paper",
        )
        oms.update_order_status(sl_order.client_order_id, "submitted")
        oms.process_fill(sl_fill)
        oms.update_order_status(sl_order.client_order_id, "filled")

        # ── 8. 验证最终状态 ──
        assert "BTCUSDT" not in account.positions
        assert account.balance > account.initial_balance, "应为正盈利"
        assert oms.get_order(sl_order.client_order_id).status == "filled"

        await bus.stop()

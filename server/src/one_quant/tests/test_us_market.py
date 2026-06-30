"""
ONE量化 - 美股规则测试

覆盖：
  - PDT 检查
  - Reg-T 保证金
  - SSR 限制
  - LULD 限价带
  - 市场熔断
  - 综合规则引擎
"""

import time
from decimal import Decimal

import pytest

from one_quant.core.types import Market, Order
from one_quant.strategy.us_market_rules import (
    LULDChecker,
    MarketCircuitBreaker,
    PDTChecker,
    RegTMarginChecker,
    SSRChecker,
    USMarketRuleEngine,
)


# ──────────────────────────── 辅助工具 ────────────────────────────


def _make_order(
    side: str = "buy",
    price: str | None = "100",
    quantity: str = "10",
    symbol: str = "AAPL",
    order_type: str = "limit",
) -> Order:
    """构造订单对象。"""
    return Order(
        client_order_id="test-001",
        symbol=symbol,
        market=Market.STOCK,
        side=side,
        order_type=order_type,
        quantity=Decimal(quantity),
        price=Decimal(price) if price is not None else None,
        stop_price=None,
        status="pending",
        exchange="ibkr",
        timestamp_ns=time.time_ns(),
    )


# ──────────────────────────── PDT 检查测试 ────────────────────────────


class TestPDTChecker:
    """PDT 日内交易规则测试"""

    def test_rich_account_unlimited(self):
        """账户 >= $25k 不受 PDT 限制。"""
        checker = PDTChecker(account_value=Decimal("30000"))
        ok, msg = checker.check_pdt("AAPL", "buy")
        assert ok is True
        assert "不受 PDT 限制" in msg

    def test_poor_account_limited(self):
        """账户 < $25k 受 PDT 限制（3 次）。"""
        checker = PDTChecker(account_value=Decimal("10000"))
        # 记录 3 次日内交易
        for _ in range(3):
            checker.record_day_trade("AAPL", time.time_ns(), time.time_ns())

        ok, msg = checker.check_pdt("AAPL", "buy")
        assert ok is False
        assert "PDT 限制" in msg

    def test_poor_account_under_limit(self):
        """账户 < $25k，日内交易次数未达上限可交易。"""
        checker = PDTChecker(account_value=Decimal("10000"))
        # 记录 2 次（< 3 次上限）
        for _ in range(2):
            checker.record_day_trade("AAPL", time.time_ns(), time.time_ns())

        ok, msg = checker.check_pdt("AAPL", "buy")
        assert ok is True

    def test_exact_threshold_rich(self):
        """账户恰好 $25,000 不受限制（边界值）。"""
        checker = PDTChecker(account_value=Decimal("25000"))
        ok, msg = checker.check_pdt("AAPL", "buy")
        assert ok is True

    def test_just_below_threshold(self):
        """账户 $24,999 受限制（边界值）。"""
        checker = PDTChecker(account_value=Decimal("24999"))
        for _ in range(3):
            checker.record_day_trade("AAPL", time.time_ns(), time.time_ns())
        ok, msg = checker.check_pdt("AAPL", "buy")
        assert ok is False

    def test_is_pdt_account_property(self):
        """is_pdt_account 属性正确。"""
        assert PDTChecker(Decimal("30000")).is_pdt_account is True
        assert PDTChecker(Decimal("10000")).is_pdt_account is False

    def test_update_account_value(self):
        """更新账户净值后 PDT 状态变化。"""
        checker = PDTChecker(account_value=Decimal("10000"))
        assert checker.is_pdt_account is False
        checker.update_account_value(Decimal("30000"))
        assert checker.is_pdt_account is True

    def test_day_trade_count(self):
        """日内交易计数正确。"""
        checker = PDTChecker(account_value=Decimal("10000"))
        assert checker.day_trade_count == 0
        checker.record_day_trade("AAPL", time.time_ns(), time.time_ns())
        assert checker.day_trade_count == 1


# ──────────────────────────── Reg-T 保证金测试 ────────────────────────────


class TestRegTMargin:
    """Reg-T 保证金检查测试"""

    def test_initial_margin_sufficient(self):
        """现金充足时初始保证金检查通过。"""
        checker = RegTMarginChecker()
        # 订单价值 $10000，需要 $5000 (50%)，有 $8000
        ok, msg = checker.check_initial_margin(Decimal("10000"), Decimal("8000"))
        assert ok is True

    def test_initial_margin_insufficient(self):
        """现金不足时初始保证金检查失败。"""
        checker = RegTMarginChecker()
        # 订单价值 $10000，需要 $5000 (50%)，只有 $3000
        ok, msg = checker.check_initial_margin(Decimal("10000"), Decimal("3000"))
        assert ok is False
        assert "初始保证金不足" in msg

    def test_initial_margin_exact(self):
        """现金恰好等于初始保证金时通过（边界值）。"""
        checker = RegTMarginChecker()
        ok, msg = checker.check_initial_margin(Decimal("10000"), Decimal("5000"))
        assert ok is True

    def test_maintenance_margin_sufficient(self):
        """净值充足时维持保证金检查通过。"""
        checker = RegTMarginChecker()
        positions = [{"market_value": 10000}]
        ok, excess = checker.check_maintenance_margin(positions, Decimal("5000"))
        # 需要 $2500 (25%)，有 $5000 → 通过
        assert ok is True

    def test_maintenance_margin_insufficient(self):
        """净值不足时维持保证金检查失败。"""
        checker = RegTMarginChecker()
        positions = [{"market_value": 10000}]
        ok, deficit = checker.check_maintenance_margin(positions, Decimal("1000"))
        # 需要 $2500 (25%)，只有 $1000 → 失败
        assert ok is False
        assert deficit > 0

    def test_maintenance_margin_empty_positions(self):
        """空持仓时维持保证金检查通过。"""
        checker = RegTMarginChecker()
        ok, _ = checker.check_maintenance_margin([], Decimal("10000"))
        assert ok is True


# ──────────────────────────── SSR 限制测试 ────────────────────────────


class TestSSRChecker:
    """SSR 卖空限制测试"""

    def test_ssr_triggered_on_drop(self):
        """跌幅达 10% 时触发 SSR。"""
        checker = SSRChecker()
        checker.update_price("AAPL", Decimal("90"), Decimal("100"))
        assert checker.is_restricted("AAPL") is True

    def test_ssr_not_triggered_small_drop(self):
        """跌幅未达 10% 不触发 SSR。"""
        checker = SSRChecker()
        checker.update_price("AAPL", Decimal("95"), Decimal("100"))
        assert checker.is_restricted("AAPL") is False

    def test_ssr_exact_threshold(self):
        """跌幅恰好 10% 触发 SSR（边界值）。"""
        checker = SSRChecker()
        checker.update_price("AAPL", Decimal("90"), Decimal("100"))
        assert checker.is_restricted("AAPL") is True

    def test_ssr_just_below_threshold(self):
        """跌幅 9.9% 不触发 SSR（边界值）。"""
        checker = SSRChecker()
        checker.update_price("AAPL", Decimal("90.1"), Decimal("100"))
        assert checker.is_restricted("AAPL") is False

    def test_ssr_restricts_short_market_order(self):
        """SSR 期间禁止市价卖空。"""
        checker = SSRChecker()
        checker.update_price("AAPL", Decimal("90"), Decimal("100"))
        order = _make_order(side="sell", price=None, order_type="market")
        ok, msg = checker.validate_short_order(order)
        assert ok is False
        assert "不允许市价卖空" in msg

    def test_ssr_restricts_short_below_bid(self):
        """SSR 期间卖空价格必须高于 best bid。"""
        checker = SSRChecker()
        checker.update_price("AAPL", Decimal("90"), Decimal("100"))
        order = _make_order(side="sell", price="89")
        ok, msg = checker.validate_short_order(order, best_bid=Decimal("90"))
        assert ok is False
        assert "必须高于最优买价" in msg

    def test_ssr_allows_short_above_bid(self):
        """SSR 期间高于 best bid 的卖空价格允许。"""
        checker = SSRChecker()
        checker.update_price("AAPL", Decimal("90"), Decimal("100"))
        order = _make_order(side="sell", price="91")
        ok, msg = checker.validate_short_order(order, best_bid=Decimal("90"))
        assert ok is True

    def test_ssr_not_applies_to_buy(self):
        """SSR 对买单不生效。"""
        checker = SSRChecker()
        checker.update_price("AAPL", Decimal("90"), Decimal("100"))
        order = _make_order(side="buy")
        ok, msg = checker.validate_short_order(order)
        assert ok is True

    def test_ssr_not_restricted_unknown_symbol(self):
        """未触发 SSR 的标的不受限制。"""
        checker = SSRChecker()
        assert checker.is_restricted("UNKNOWN") is False


# ──────────────────────────── LULD 限价带测试 ────────────────────────────


class TestLULDChecker:
    """LULD 限价带检查测试"""

    def test_price_within_band(self):
        """价格在限价带内通过检查。"""
        checker = LULDChecker()
        checker.set_reference_price("AAPL", Decimal("100"), tier=1)
        ok, msg = checker.check_price_band("AAPL", Decimal("102"))
        assert ok is True

    def test_price_above_upper_band(self):
        """价格超过上限被拒绝。"""
        checker = LULDChecker()
        checker.set_reference_price("AAPL", Decimal("100"), tier=1)
        # Tier 1: ±5%，上限 = 105
        ok, msg = checker.check_price_band("AAPL", Decimal("106"))
        assert ok is False
        assert "上限突破" in msg

    def test_price_below_lower_band(self):
        """价格低于下限被拒绝。"""
        checker = LULDChecker()
        checker.set_reference_price("AAPL", Decimal("100"), tier=1)
        # Tier 1: ±5%，下限 = 95
        ok, msg = checker.check_price_band("AAPL", Decimal("94"))
        assert ok is False
        assert "下限突破" in msg

    def test_tier1_normal_band(self):
        """Tier 1 标的正常时段 ±5%。"""
        checker = LULDChecker()
        checker.set_reference_price("AAPL", Decimal("100"), tier=1)
        assert checker.check_price_band("AAPL", Decimal("105"))[0] is True
        assert checker.check_price_band("AAPL", Decimal("105.01"))[0] is False

    def test_tier1_open_close_band(self):
        """Tier 1 标的开盘/收盘时段 ±10%。"""
        checker = LULDChecker()
        checker.set_reference_price("AAPL", Decimal("100"), tier=1)
        ok, _ = checker.check_price_band("AAPL", Decimal("109"), is_open_close_period=True)
        assert ok is True
        ok, _ = checker.check_price_band("AAPL", Decimal("111"), is_open_close_period=True)
        assert ok is False

    def test_tier2_normal_band(self):
        """Tier 2 标的正常时段 ±10%。"""
        checker = LULDChecker()
        checker.set_reference_price("SMALL", Decimal("100"), tier=2)
        assert checker.check_price_band("SMALL", Decimal("110"))[0] is True
        assert checker.check_price_band("SMALL", Decimal("110.01"))[0] is False

    def test_no_reference_price_passes(self):
        """无参考价格时跳过检查。"""
        checker = LULDChecker()
        ok, msg = checker.check_price_band("UNKNOWN", Decimal("999999"))
        assert ok is True

    def test_zero_reference_price_passes(self):
        """参考价格为零时跳过检查。"""
        checker = LULDChecker()
        checker.set_reference_price("AAPL", Decimal("0"))
        ok, _ = checker.check_price_band("AAPL", Decimal("100"))
        assert ok is True


# ──────────────────────────── 市场熔断测试 ────────────────────────────


class TestMarketCircuitBreaker:
    """市场级熔断测试"""

    def test_level1_triggered(self):
        """S&P 500 跌 7% 触发 Level 1 熔断。"""
        cb = MarketCircuitBreaker()
        cb.set_sp500_prev_close(Decimal("4000"))
        level = cb.update_sp500_price(Decimal("3720"))  # 跌 7%
        assert level == 1

    def test_level2_triggered(self):
        """S&P 500 跌 13% 触发 Level 2 熔断。"""
        cb = MarketCircuitBreaker()
        cb.set_sp500_prev_close(Decimal("4000"))
        level = cb.update_sp500_price(Decimal("3480"))  # 跌 13%
        assert level == 2

    def test_level3_triggered(self):
        """S&P 500 跌 20% 触发 Level 3 熔断。"""
        cb = MarketCircuitBreaker()
        cb.set_sp500_prev_close(Decimal("4000"))
        level = cb.update_sp500_price(Decimal("3200"))  # 跌 20%
        assert level == 3

    def test_no_trigger_small_drop(self):
        """小幅下跌不触发熔断。"""
        cb = MarketCircuitBreaker()
        cb.set_sp500_prev_close(Decimal("4000"))
        level = cb.update_sp500_price(Decimal("3900"))  # 跌 2.5%
        assert level == 0

    def test_level1_exact_threshold(self):
        """跌幅恰好 7% 触发 Level 1（边界值）。"""
        cb = MarketCircuitBreaker()
        cb.set_sp500_prev_close(Decimal("1000"))
        level = cb.update_sp500_price(Decimal("930"))
        assert level == 1

    def test_level1_just_below(self):
        """跌幅 6.9% 不触发（边界值）。"""
        cb = MarketCircuitBreaker()
        cb.set_sp500_prev_close(Decimal("1000"))
        level = cb.update_sp500_price(Decimal("931"))
        assert level == 0

    def test_no_prev_close_no_trigger(self):
        """未设置前收盘价时不触发。"""
        cb = MarketCircuitBreaker()
        level = cb.update_sp500_price(Decimal("3000"))
        assert level == 0

    def test_check_market_halt(self):
        """熔断状态检查。"""
        cb = MarketCircuitBreaker()
        is_halted, level, msg = cb.check_market_halt()
        assert is_halted is False
        assert level == 0


# ──────────────────────────── 综合规则引擎测试 ────────────────────────────


class TestUSMarketRuleEngine:
    """综合规则引擎测试"""

    def test_valid_order_passes(self):
        """正常订单通过所有检查。"""
        engine = USMarketRuleEngine(
            account_value=Decimal("30000"),
            cash=Decimal("20000"),
            positions=[],
            equity=Decimal("30000"),
        )
        order = _make_order(side="buy", price="100", quantity="10")
        ok, reasons = engine.validate_order(order)
        assert ok is True
        assert len(reasons) == 0

    def test_pdt_blocks_order(self):
        """PDT 规则阻止订单。"""
        engine = USMarketRuleEngine(
            account_value=Decimal("10000"),  # < $25k
            cash=Decimal("10000"),
            positions=[],
            equity=Decimal("10000"),
        )
        # 记录 3 次日内交易
        for _ in range(3):
            engine.pdt.record_day_trade("AAPL", time.time_ns(), time.time_ns())

        order = _make_order(side="buy")
        ok, reasons = engine.validate_order(order)
        assert ok is False
        assert any("PDT" in r for r in reasons)

    def test_margin_blocks_order(self):
        """保证金不足阻止订单。"""
        engine = USMarketRuleEngine(
            account_value=Decimal("30000"),
            cash=Decimal("100"),  # 极少现金
            positions=[],
            equity=Decimal("30000"),
        )
        order = _make_order(side="buy", price="1000", quantity="10")  # 价值 $10000
        ok, reasons = engine.validate_order(order)
        assert ok is False
        assert any("保证金" in r for r in reasons)

    def test_luld_blocks_order(self):
        """LULD 限价带阻止订单。"""
        engine = USMarketRuleEngine(
            account_value=Decimal("30000"),
            cash=Decimal("20000"),
            positions=[],
            equity=Decimal("30000"),
        )
        engine.luld.set_reference_price("AAPL", Decimal("100"), tier=1)
        order = _make_order(side="buy", price="110")  # 超过 ±5% 限价带
        ok, reasons = engine.validate_order(order)
        assert ok is False
        assert any("LULD" in r for r in reasons)

    def test_circuit_breaker_blocks_all(self):
        """市场熔断阻止所有订单。"""
        engine = USMarketRuleEngine(
            account_value=Decimal("30000"),
            cash=Decimal("20000"),
            positions=[],
            equity=Decimal("30000"),
        )
        engine.circuit_breaker.set_sp500_prev_close(Decimal("4000"))
        engine.circuit_breaker.update_sp500_price(Decimal("3200"))  # Level 3

        order = _make_order(side="buy")
        ok, reasons = engine.validate_order(order)
        assert ok is False
        assert any("熔断" in r for r in reasons)

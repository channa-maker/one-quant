"""
ONE量化 - 风控规则完整测试 (L1/L2/L3/L4)

覆盖:
  L1: 白名单/停牌/数量/价格/偏离/名义 - 所有分支
  L2: 频率/敞口/杠杆/集中度 - 所有分支
  L3: 回撤/日内止损/保证金/halt/负权益 - 所有分支
  L4: 三态机/should_allow/check/record_success/failure - 所有分支
"""

from __future__ import annotations

import time
from decimal import Decimal

from one_quant.core.types import Market, Order, PositionState
from one_quant.risk.contracts import RiskDecision
from one_quant.risk.rules.l1_static import (
    MAX_ABSOLUTE_PRICE,
    L1StaticLimitRule,
)
from one_quant.risk.rules.l2_realtime import (
    MAX_ORDER_FREQ,
    L2RealtimeExposureRule,
)
from one_quant.risk.rules.l3_drawdown import (
    L3DrawdownRule,
)
from one_quant.risk.rules.l4_circuit_breaker import (
    FAILURE_THRESHOLD,
    HALF_OPEN_MAX_PROBES,
    RECOVERY_TIMEOUT_SEC,
    CircuitBreakerState,
    L4CircuitBreaker,
)

# ──────────────────── 辅助工具 ────────────────────


def _make_order(
    symbol: str = "BTC/USDT",
    side: str = "buy",
    order_type: str = "limit",
    quantity: str = "0.1",
    price: str | None = "50000",
    stop_price: str | None = None,
    market: Market = Market.SPOT,
) -> Order:
    return Order(
        client_order_id="test-uuid",
        symbol=symbol,
        market=market,
        side=side,
        order_type=order_type,
        quantity=Decimal(quantity),
        price=Decimal(price) if price is not None else None,
        stop_price=Decimal(stop_price) if stop_price is not None else None,
        status="pending",
        exchange="binance",
        timestamp_ns=time.time_ns(),
    )


def _make_position(
    symbol: str = "BTC/USDT",
    quantity: str = "1.0",
    entry_price: str = "50000",
    market: Market = Market.SPOT,
) -> PositionState:
    return PositionState(
        symbol=symbol,
        market=market,
        side="long",
        quantity=Decimal(quantity),
        entry_price=Decimal(entry_price),
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
        timestamp_ns=time.time_ns(),
    )


# ════════════════════════════════════════════════════════════════
# L1 静态限额测试
# ════════════════════════════════════════════════════════════════


class TestL1StaticLimits:
    """L1 静态限额 - 完整覆盖"""

    def test_tradable_symbol_passes(self):
        """白名单标的通过。"""
        rule = L1StaticLimitRule()
        for symbol in ["BTC/USDT", "ETH/USDT", "AAPL", "NVDA"]:
            result = rule.check(_make_order(symbol=symbol), [])
            assert result.decision == RiskDecision.APPROVE, f"{symbol} should pass"

    def test_suspended_symbol_rejected(self):
        """停牌标的被拒绝。"""
        rule = L1StaticLimitRule()
        for symbol in ["LUNA/USDT", "FTT/USDT", "UST/USDT"]:
            result = rule.check(_make_order(symbol=symbol), [])
            assert result.decision == RiskDecision.REJECT
            assert "停牌" in result.reason

    def test_unknown_symbol_rejected(self):
        """非白名单标的被拒绝。"""
        rule = L1StaticLimitRule()
        result = rule.check(_make_order(symbol="UNKNOWN/USDT"), [])
        assert result.decision == RiskDecision.REJECT
        assert "白名单" in result.reason

    def test_zero_quantity_rejected(self):
        """零数量被拒绝。"""
        rule = L1StaticLimitRule()
        result = rule.check(_make_order(quantity="0"), [])
        assert result.decision == RiskDecision.REJECT
        assert "大于 0" in result.reason

    def test_negative_quantity_rejected(self):
        """负数量被拒绝。"""
        rule = L1StaticLimitRule()
        result = rule.check(_make_order(quantity="-1"), [])
        assert result.decision == RiskDecision.REJECT

    def test_negative_price_rejected(self):
        """负价格被拒绝。"""
        rule = L1StaticLimitRule()
        result = rule.check(_make_order(price="-100"), [])
        assert result.decision == RiskDecision.REJECT
        assert "正数" in result.reason

    def test_zero_price_rejected(self):
        """零价格被拒绝。"""
        rule = L1StaticLimitRule()
        result = rule.check(_make_order(price="0"), [])
        assert result.decision == RiskDecision.REJECT

    def test_price_above_absolute_limit_rejected(self):
        """价格超过绝对上限被拒绝。"""
        rule = L1StaticLimitRule()
        result = rule.check(
            _make_order(price=str(MAX_ABSOLUTE_PRICE + 1)),
            [],
        )
        assert result.decision == RiskDecision.REJECT
        assert "绝对上限" in result.reason

    def test_price_at_absolute_limit_passes(self):
        """价格恰好等于绝对上限通过。"""
        rule = L1StaticLimitRule()
        # 名义 = MAX_ABSOLUTE_PRICE * 0.000001 很小但大于MIN
        result = rule.check(
            _make_order(price=str(MAX_ABSOLUTE_PRICE), quantity="0.001"),
            [],
        )
        # 名义 = MAX_ABSOLUTE_PRICE * 0.001 = 10000 > MIN_ORDER_NOTIONAL=10
        # 但 < MAX_ORDER_NOTIONAL=100000? MAX_ABSOLUTE_PRICE * 0.001 = 10000 < 100000 ✓
        assert result.decision == RiskDecision.APPROVE

    def test_negative_stop_price_rejected(self):
        """负止损价被拒绝。"""
        rule = L1StaticLimitRule()
        result = rule.check(
            _make_order(price=None, stop_price="-100", order_type="stop_market"),
            [],
        )
        assert result.decision == RiskDecision.REJECT
        assert "止损价格" in result.reason

    def test_zero_stop_price_rejected(self):
        """零止损价被拒绝。"""
        rule = L1StaticLimitRule()
        result = rule.check(
            _make_order(price=None, stop_price="0", order_type="stop_market"),
            [],
        )
        assert result.decision == RiskDecision.REJECT

    # ── 价格偏离测试 ──

    def test_price_deviation_within_limit_passes(self):
        """价格偏离在阈值内通过。"""
        rule = L1StaticLimitRule()
        latest_price = Decimal("50000")
        # 9% 偏离 < 10%
        order_price = Decimal("54500")
        result = rule.check(
            _make_order(price=str(order_price)),
            [],
            latest_price=latest_price,
        )
        assert result.decision == RiskDecision.APPROVE

    def test_price_deviation_exceeds_limit_rejected(self):
        """价格偏离超过阈值被拒绝。"""
        rule = L1StaticLimitRule()
        latest_price = Decimal("50000")
        # 11% 偏离 > 10%
        order_price = Decimal("55500")
        result = rule.check(
            _make_order(price=str(order_price)),
            [],
            latest_price=latest_price,
        )
        assert result.decision == RiskDecision.REJECT
        assert "偏离" in result.reason

    def test_price_deviation_exact_boundary_passes(self):
        """价格偏离恰好等于阈值通过 (>= 被拒绝，所以恰好等于应通过)。"""
        rule = L1StaticLimitRule()
        latest_price = Decimal("100")
        # 偏离 = 10 / 100 = 10% = MAX_PRICE_DEVIATION
        # deviation > MAX_PRICE_DEVIATION 时拒绝，所以等于时不拒绝
        result = rule.check(
            _make_order(price="110"),
            [],
            latest_price=latest_price,
        )
        assert result.decision == RiskDecision.APPROVE

    def test_price_deviation_below_limit_passes(self):
        """价格偏离略低于阈值通过。"""
        rule = L1StaticLimitRule()
        latest_price = Decimal("100")
        # 偏离 = 9.99 / 100 = 9.99% < 10%
        result = rule.check(
            _make_order(price="109.99"),
            [],
            latest_price=latest_price,
        )
        assert result.decision == RiskDecision.APPROVE

    def test_price_deviation_no_latest_price_skipped(self):
        """无最新价时跳过偏离检查。"""
        rule = L1StaticLimitRule()
        result = rule.check(_make_order(price="999999"), [], latest_price=None)
        # 价格 999999 < MAX_ABSOLUTE_PRICE，名义 = 999999*0.1 = 99999.9 < 100000
        assert result.decision == RiskDecision.APPROVE

    def test_price_deviation_zero_latest_price_skipped(self):
        """最新价为0时跳过偏离检查。"""
        rule = L1StaticLimitRule()
        result = rule.check(_make_order(), [], latest_price=Decimal("0"))
        assert result.decision == RiskDecision.APPROVE

    # ── 名义金额测试 ──

    def test_notional_below_minimum_rejected(self):
        """名义金额低于最小限额被拒绝。"""
        rule = L1StaticLimitRule()
        # 名义 = 5 * 1 = 5 < MIN=10
        result = rule.check(_make_order(quantity="5", price="1"), [])
        assert result.decision == RiskDecision.REJECT
        assert "最小限额" in result.reason

    def test_notional_at_minimum_passes(self):
        """名义金额恰好等于最小限额通过。"""
        rule = L1StaticLimitRule()
        # 名义 = 10 * 1 = 10 = MIN
        result = rule.check(_make_order(quantity="10", price="1"), [])
        assert result.decision == RiskDecision.APPROVE

    def test_notional_above_maximum_rejected(self):
        """名义金额超过最大限额被拒绝。"""
        rule = L1StaticLimitRule()
        # 名义 = 100001 * 1 = 100001 > MAX=100000
        result = rule.check(_make_order(quantity="100001", price="1"), [])
        assert result.decision == RiskDecision.REJECT
        assert "最大限额" in result.reason

    def test_notional_at_maximum_passes(self):
        """名义金额恰好等于最大限额通过。"""
        rule = L1StaticLimitRule()
        # 名义 = 100000 * 1 = 100000 = MAX
        result = rule.check(_make_order(quantity="100000", price="1"), [])
        assert result.decision == RiskDecision.APPROVE

    def test_notional_with_stop_price(self):
        """使用止损价计算名义。"""
        rule = L1StaticLimitRule()
        # 无 price，stop_price=1，quantity=5 → 名义=5 < MIN=10
        result = rule.check(
            _make_order(price=None, stop_price="1", quantity="5", order_type="stop_market"),
            [],
        )
        assert result.decision == RiskDecision.REJECT

    def test_notional_market_order_zero(self):
        """市价单无法计算名义，跳过名义检查。"""
        rule = L1StaticLimitRule()
        result = rule.check(
            _make_order(price=None, order_type="market"),
            [],
        )
        # 市价单 notional=0, 0 不 > 0 所以不触发最小限额, 0 不 > MAX
        assert result.decision == RiskDecision.APPROVE

    def test_calc_notional_with_price(self):
        """_calc_notional 使用 price。"""
        order = _make_order(quantity="2", price="50000")
        assert L1StaticLimitRule._calc_notional(order) == Decimal("100000")

    def test_calc_notional_with_stop_price_only(self):
        """_calc_notional 使用 stop_price (无 price)。"""
        order = _make_order(price=None, stop_price="50000", quantity="2", order_type="stop_market")
        assert L1StaticLimitRule._calc_notional(order) == Decimal("100000")

    def test_calc_notional_market_order(self):
        """_calc_notional 市价单返回 0。"""
        order = _make_order(price=None, order_type="market")
        assert L1StaticLimitRule._calc_notional(order) == Decimal("0")

    def test_check_pass_all_valid(self):
        """所有检查通过返回 APPROVE。"""
        rule = L1StaticLimitRule()
        result = rule.check(_make_order(), [])
        assert result.decision == RiskDecision.APPROVE
        assert result.rule_name == "L1_静态限额"


# ════════════════════════════════════════════════════════════════
# L2 实时敞口测试
# ════════════════════════════════════════════════════════════════


class TestL2RealtimeExposure:
    """L2 实时敞口 - 完整覆盖"""

    def test_basic_pass(self):
        """基本通过检查。"""
        rule = L2RealtimeExposureRule()
        order = _make_order()
        result = rule.check(
            order, [], total_equity=Decimal("1000000"), latest_price=Decimal("50000")
        )
        assert result.decision == RiskDecision.APPROVE

    # ── 频率限制 ──

    def test_order_frequency_within_limit(self):
        """下单频率在限制内通过。"""
        rule = L2RealtimeExposureRule()
        for _ in range(MAX_ORDER_FREQ - 1):
            rule.check(
                _make_order(), [], total_equity=Decimal("1000000"), latest_price=Decimal("50000")
            )
        # 第 MAX_ORDER_FREQ 次应该通过 (因为是 >= 才拒绝)
        result = rule.check(
            _make_order(), [], total_equity=Decimal("1000000"), latest_price=Decimal("50000")
        )
        assert result.decision == RiskDecision.APPROVE

    def test_order_frequency_exceeds_limit(self):
        """下单频率超过限制被拒绝。"""
        rule = L2RealtimeExposureRule()
        # 先下单 MAX_ORDER_FREQ 次
        for _ in range(MAX_ORDER_FREQ):
            rule.check(
                _make_order(), [], total_equity=Decimal("1000000"), latest_price=Decimal("50000")
            )
        # 第 MAX_ORDER_FREQ+1 次应被拒绝
        result = rule.check(
            _make_order(), [], total_equity=Decimal("1000000"), latest_price=Decimal("50000")
        )
        assert result.decision == RiskDecision.REJECT
        assert "频率" in result.reason

    def test_order_frequency_different_symbols(self):
        """不同标的独立计数。"""
        rule = L2RealtimeExposureRule()
        for _ in range(MAX_ORDER_FREQ):
            rule.check(
                _make_order(symbol="BTC/USDT"),
                [],
                total_equity=Decimal("1000000"),
                latest_price=Decimal("50000"),
            )
        # ETH 不受 BTC 频率限制
        result = rule.check(
            _make_order(symbol="ETH/USDT"),
            [],
            total_equity=Decimal("1000000"),
            latest_price=Decimal("3000"),
        )
        assert result.decision == RiskDecision.APPROVE

    # ── 总敞口检查 ──

    def test_total_exposure_within_limit(self):
        """总敞口在限制内通过。"""
        rule = L2RealtimeExposureRule()
        positions = [_make_position(quantity="0.5", entry_price="50000")]
        # 总敞口 = 25000 (持仓) + 5000 (新单) = 30000
        # 占比 = 30000 / 1000000 = 3% < 50%
        result = rule.check(
            _make_order(quantity="0.1", price="50000"),
            positions,
            total_equity=Decimal("1000000"),
            latest_price=Decimal("50000"),
        )
        assert result.decision == RiskDecision.APPROVE

    def test_total_exposure_exceeds_limit(self):
        """总敞口超过限制返回 REDUCE。"""
        rule = L2RealtimeExposureRule()
        # 大持仓: 10 * 50000 = 500000
        positions = [_make_position(quantity="10", entry_price="50000")]
        # 新单: 5 * 50000 = 250000
        # 总敞口 = 750000, 占比 = 750000/1000000 = 75% > 50%
        result = rule.check(
            _make_order(quantity="5", price="50000"),
            positions,
            total_equity=Decimal("1000000"),
            latest_price=Decimal("50000"),
        )
        assert result.decision == RiskDecision.REDUCE
        assert "总敞口" in result.reason

    def test_total_exposure_no_equity_skipped(self):
        """无总权益时跳过敞口检查。"""
        rule = L2RealtimeExposureRule()
        result = rule.check(_make_order(), [], total_equity=None, latest_price=Decimal("50000"))
        assert result.decision == RiskDecision.APPROVE

    def test_total_exposure_no_price_skipped(self):
        """无最新价时跳过敞口检查。"""
        rule = L2RealtimeExposureRule()
        result = rule.check(_make_order(), [], total_equity=Decimal("1000000"), latest_price=None)
        assert result.decision == RiskDecision.APPROVE

    def test_total_exposure_zero_equity_skipped(self):
        """权益为0时跳过敞口检查。"""
        rule = L2RealtimeExposureRule()
        result = rule.check(
            _make_order(), [], total_equity=Decimal("0"), latest_price=Decimal("50000")
        )
        assert result.decision == RiskDecision.APPROVE

    # ── 杠杆检查 ──

    def test_leverage_futures_within_limit(self):
        """合约杠杆在限制内通过。"""
        rule = L2RealtimeExposureRule()
        # 杠杆 = 25000 / 1000000 = 0.025x < 20x
        result = rule.check(
            _make_order(market=Market.FUTURES, quantity="0.5"),
            [],
            total_equity=Decimal("1000000"),
            latest_price=Decimal("50000"),
        )
        assert result.decision == RiskDecision.APPROVE

    def test_leverage_futures_exceeds_limit(self):
        """合约杠杆超过限制返回 REDUCE。"""
        rule = L2RealtimeExposureRule()
        # 不传 latest_price 跳过敞口检查, 直接检查杠杆
        # 总名义 = 500000 (持仓) + 0 (无price时=0) ≈ 500000
        # 权益 = 20000 → 杠杆 = 25x > 20x
        positions = [_make_position(quantity="10", entry_price="50000", market=Market.FUTURES)]
        result = rule.check(
            _make_order(market=Market.FUTURES, quantity="0.1"),
            positions,
            total_equity=Decimal("20000"),
            latest_price=None,  # 跳过敞口检查
        )
        assert result.decision == RiskDecision.REDUCE
        assert "杠杆" in result.reason

    def test_leverage_stock_within_limit(self):
        """美股杠杆在限制内通过。"""
        rule = L2RealtimeExposureRule()
        result = rule.check(
            _make_order(symbol="AAPL", market=Market.STOCK, quantity="1", price="150"),
            [],
            total_equity=Decimal("100000"),
            latest_price=Decimal("150"),
        )
        assert result.decision == RiskDecision.APPROVE

    def test_leverage_stock_exceeds_limit(self):
        """美股杠杆超过限制返回 REDUCE。"""
        rule = L2RealtimeExposureRule()
        # 不传 latest_price 跳过敞口检查
        # 总名义 = 15000 (持仓) + 0 (无price) = 15000
        # 但 order.price 存在 (150), 所以 15000 + 15000 = 30000
        # 权益 = 6000 → 杠杆 = 5x > 4x
        positions = [
            _make_position(symbol="AAPL", quantity="100", entry_price="150", market=Market.STOCK)
        ]
        result = rule.check(
            _make_order(symbol="AAPL", market=Market.STOCK, quantity="100", price="150"),
            positions,
            total_equity=Decimal("6000"),
            latest_price=None,  # 跳过敞口检查
        )
        assert result.decision == RiskDecision.REDUCE
        assert "杠杆" in result.reason

    def test_leverage_spot_skipped(self):
        """现货跳过杠杆检查 (return None)。"""
        rule = L2RealtimeExposureRule()
        positions = [_make_position(quantity="100", entry_price="50000")]
        result = rule.check(
            _make_order(market=Market.SPOT),
            positions,
            total_equity=Decimal("1000"),
            latest_price=Decimal("50000"),
        )
        # SPOT 不检查杠杆, 但可能触发其他检查
        # 总敞口 = 5000000 + 5000 = 5005000 / 1000 = 5005 > 0.5 → REDUCE
        assert result.decision in (RiskDecision.REDUCE, RiskDecision.APPROVE)

    def test_leverage_no_equity_skipped(self):
        """无权益时跳过杠杆检查。"""
        rule = L2RealtimeExposureRule()
        result = rule.check(
            _make_order(market=Market.FUTURES),
            [],
            total_equity=None,
        )
        assert result.decision == RiskDecision.APPROVE

    # ── 仓位集中度 ──

    def test_position_concentration_within_limit(self):
        """仓位集中在限制内通过。"""
        rule = L2RealtimeExposureRule()
        # 持仓名义 = 0.1 * 50000 = 5000, 新单 = 0.1 * 50000 = 5000
        # 总 = 10000, 占比 = 10000/1000000 = 1% < 10%
        result = rule.check(
            _make_order(quantity="0.1"),
            [_make_position(quantity="0.1")],
            total_equity=Decimal("1000000"),
            latest_price=Decimal("50000"),
        )
        assert result.decision == RiskDecision.APPROVE

    def test_position_concentration_exceeds_limit(self):
        """仓位集中超过限制被拒绝。"""
        rule = L2RealtimeExposureRule()
        # 持仓名义 = 1 * 50000 = 50000, 新单 = 0.5 * 50000 = 25000
        # 总 = 75000, 占比 = 75000/500000 = 15% > 10%
        result = rule.check(
            _make_order(quantity="0.5"),
            [_make_position(quantity="1")],
            total_equity=Decimal("500000"),
            latest_price=Decimal("50000"),
        )
        assert result.decision == RiskDecision.REJECT
        assert "仓位占比" in result.reason

    def test_position_concentration_no_equity_skipped(self):
        """无权益时跳过集中度检查。"""
        rule = L2RealtimeExposureRule()
        result = rule.check(_make_order(), [_make_position()], total_equity=None)
        assert result.decision == RiskDecision.APPROVE

    # ── reset ──

    def test_reset_clears_timestamps(self):
        """reset 清空频率记录。"""
        rule = L2RealtimeExposureRule()
        for _ in range(MAX_ORDER_FREQ):
            rule.check(_make_order(), [])
        rule.reset()
        result = rule.check(_make_order(), [])
        assert result.decision == RiskDecision.APPROVE

    def test_order_with_latest_price(self):
        """下单带最新价。"""
        rule = L2RealtimeExposureRule()
        result = rule.check(
            _make_order(price="52000"),
            [],
            total_equity=Decimal("1000000"),
            latest_price=Decimal("50000"),
        )
        assert result.decision == RiskDecision.APPROVE


# ════════════════════════════════════════════════════════════════
# L3 回撤监控测试
# ════════════════════════════════════════════════════════════════


class TestL3Drawdown:
    """L3 回撤监控 - 完整覆盖"""

    def test_normal_passes(self):
        """正常情况通过。"""
        rule = L3DrawdownRule()
        result = rule.check(
            equity=Decimal("100000"),
            peak_equity=Decimal("100000"),
            daily_pnl=Decimal("0"),
        )
        assert result.decision == RiskDecision.APPROVE

    # ── 最大回撤 ──

    def test_drawdown_below_threshold_passes(self):
        """回撤低于阈值通过。"""
        rule = L3DrawdownRule()
        # 14% 回撤 < 15%
        result = rule.check(
            equity=Decimal("86000"),
            peak_equity=Decimal("100000"),
            daily_pnl=Decimal("0"),
        )
        assert result.decision == RiskDecision.APPROVE

    def test_drawdown_exceeds_threshold_flatten(self):
        """回撤超过阈值触发 FLATTEN。"""
        rule = L3DrawdownRule()
        # 20% 回撤 > 15%
        result = rule.check(
            equity=Decimal("80000"),
            peak_equity=Decimal("100000"),
            daily_pnl=Decimal("0"),
        )
        assert result.decision == RiskDecision.FLATTEN
        assert "最大回撤" in result.reason
        assert rule.is_halted

    def test_drawdown_exact_boundary(self):
        """回撤恰好等于阈值 (15%) 触发 FLATTEN。"""
        rule = L3DrawdownRule()
        # (100000 - 85000) / 100000 = 0.15 = MAX_DRAWDOWN_PCT
        result = rule.check(
            equity=Decimal("85000"),
            peak_equity=Decimal("100000"),
            daily_pnl=Decimal("0"),
        )
        assert result.decision == RiskDecision.FLATTEN
        # drawdown >= MAX_DRAWDOWN_PCT 触发

    def test_drawdown_just_below_boundary_passes(self):
        """回撤略低于阈值通过。"""
        rule = L3DrawdownRule()
        # (100000 - 85001) / 100000 = 14.999% < 15%
        result = rule.check(
            equity=Decimal("85001"),
            peak_equity=Decimal("100000"),
            daily_pnl=Decimal("0"),
        )
        assert result.decision == RiskDecision.APPROVE

    def test_negative_equity_flatten(self):
        """权益为负触发 FLATTEN。"""
        rule = L3DrawdownRule()
        result = rule.check(
            equity=Decimal("-1000"),
            peak_equity=Decimal("0"),
            daily_pnl=Decimal("-1000"),
        )
        assert result.decision == RiskDecision.FLATTEN
        assert rule.is_halted

    def test_peak_equity_zero_negative_equity(self):
        """peak_equity=0 且 equity<0 触发熔断。"""
        rule = L3DrawdownRule()
        result = rule.check(
            equity=Decimal("-1"),
            peak_equity=Decimal("0"),
            daily_pnl=Decimal("-1"),
        )
        assert result.decision == RiskDecision.FLATTEN

    def test_peak_equity_zero_positive_equity_skips_drawdown(self):
        """peak_equity=0 且 equity>=0 跳过回撤检查。"""
        rule = L3DrawdownRule()
        result = rule.check(
            equity=Decimal("100"),
            peak_equity=Decimal("0"),
            daily_pnl=Decimal("0"),
        )
        assert result.decision == RiskDecision.APPROVE

    # ── 日内止损 ──

    def test_daily_loss_below_limit_passes(self):
        """日内亏损低于限制通过。"""
        rule = L3DrawdownRule()
        # 4.9% < 5%
        result = rule.check(
            equity=Decimal("95100"),
            peak_equity=Decimal("100000"),
            daily_pnl=Decimal("-4900"),
            initial_equity=Decimal("100000"),
        )
        assert result.decision == RiskDecision.APPROVE

    def test_daily_loss_exceeds_limit_flatten(self):
        """日内亏损超过限制触发 halt_all。"""
        rule = L3DrawdownRule()
        # 6% > 5%
        result = rule.check(
            equity=Decimal("94000"),
            peak_equity=Decimal("100000"),
            daily_pnl=Decimal("-6000"),
            initial_equity=Decimal("100000"),
        )
        assert result.decision == RiskDecision.FLATTEN
        assert "日内亏损" in result.reason

    def test_daily_loss_exact_boundary(self):
        """日内亏损恰好等于限制 (5%) 触发。"""
        rule = L3DrawdownRule()
        # 5000/100000 = 5% = DAILY_LOSS_LIMIT
        result = rule.check(
            equity=Decimal("95000"),
            peak_equity=Decimal("100000"),
            daily_pnl=Decimal("-5000"),
            initial_equity=Decimal("100000"),
        )
        assert result.decision == RiskDecision.FLATTEN

    def test_daily_loss_just_below_limit_passes(self):
        """日内亏损略低于限制通过。"""
        rule = L3DrawdownRule()
        # 4999/100000 = 4.999% < 5%
        result = rule.check(
            equity=Decimal("95001"),
            peak_equity=Decimal("100000"),
            daily_pnl=Decimal("-4999"),
            initial_equity=Decimal("100000"),
        )
        assert result.decision == RiskDecision.APPROVE

    def test_daily_loss_no_initial_uses_peak(self):
        """无 initial_equity 时使用 peak_equity。"""
        rule = L3DrawdownRule()
        # 6000/100000 = 6% > 5% → halt
        result = rule.check(
            equity=Decimal("94000"),
            peak_equity=Decimal("100000"),
            daily_pnl=Decimal("-6000"),
            initial_equity=None,
        )
        assert result.decision == RiskDecision.FLATTEN

    def test_daily_loss_positive_pnl_passes(self):
        """盈利时通过。"""
        rule = L3DrawdownRule()
        result = rule.check(
            equity=Decimal("110000"),
            peak_equity=Decimal("110000"),
            daily_pnl=Decimal("10000"),
            initial_equity=Decimal("100000"),
        )
        assert result.decision == RiskDecision.APPROVE

    def test_daily_loss_zero_initial_skips(self):
        """initial_equity <= 0 时跳过日内止损。"""
        rule = L3DrawdownRule()
        result = rule.check(
            equity=Decimal("100"),
            peak_equity=Decimal("100"),
            daily_pnl=Decimal("-100"),
            initial_equity=Decimal("0"),
        )
        assert result.decision == RiskDecision.APPROVE

    # ── 保证金率 ──

    def test_margin_within_limit_passes(self):
        """保证金率在限制内通过。"""
        rule = L3DrawdownRule()
        # 70% < 80%
        result = rule.check(
            equity=Decimal("100000"),
            peak_equity=Decimal("100000"),
            daily_pnl=Decimal("0"),
            used_margin=Decimal("70000"),
            total_margin=Decimal("100000"),
        )
        assert result.decision == RiskDecision.APPROVE

    def test_margin_exceeds_limit_reduce(self):
        """保证金率超过限制返回 REDUCE。"""
        rule = L3DrawdownRule()
        # 85% > 80%
        result = rule.check(
            equity=Decimal("100000"),
            peak_equity=Decimal("100000"),
            daily_pnl=Decimal("0"),
            used_margin=Decimal("85000"),
            total_margin=Decimal("100000"),
        )
        assert result.decision == RiskDecision.REDUCE
        assert "保证金" in result.reason

    def test_margin_exact_boundary(self):
        """保证金率恰好等于限制 (80%) 触发。"""
        rule = L3DrawdownRule()
        result = rule.check(
            equity=Decimal("100000"),
            peak_equity=Decimal("100000"),
            daily_pnl=Decimal("0"),
            used_margin=Decimal("80000"),
            total_margin=Decimal("100000"),
        )
        assert result.decision == RiskDecision.REDUCE

    def test_margin_just_below_limit_passes(self):
        """保证金率略低于限制通过。"""
        rule = L3DrawdownRule()
        # 79.99% < 80%
        result = rule.check(
            equity=Decimal("100000"),
            peak_equity=Decimal("100000"),
            daily_pnl=Decimal("0"),
            used_margin=Decimal("79990"),
            total_margin=Decimal("100000"),
        )
        assert result.decision == RiskDecision.APPROVE

    def test_margin_zero_total_skips(self):
        """total_margin <= 0 时跳过保证金检查。"""
        rule = L3DrawdownRule()
        result = rule.check(
            equity=Decimal("100000"),
            peak_equity=Decimal("100000"),
            daily_pnl=Decimal("0"),
            used_margin=Decimal("50000"),
            total_margin=Decimal("0"),
        )
        assert result.decision == RiskDecision.APPROVE

    def test_margin_not_provided_skips(self):
        """不提供保证金参数时跳过。"""
        rule = L3DrawdownRule()
        result = rule.check(
            equity=Decimal("100000"),
            peak_equity=Decimal("100000"),
            daily_pnl=Decimal("0"),
        )
        assert result.decision == RiskDecision.APPROVE

    # ── halt_all / reset ──

    def test_halt_all_sets_halted(self):
        """halt_all 设置熔断状态。"""
        rule = L3DrawdownRule()
        assert not rule.is_halted
        rule.halt_all()
        assert rule.is_halted

    def test_halted_blocks_subsequent_checks(self):
        """熔断后所有检查返回 FLATTEN。"""
        rule = L3DrawdownRule()
        rule.halt_all()
        result = rule.check(
            equity=Decimal("100000"),
            peak_equity=Decimal("100000"),
            daily_pnl=Decimal("0"),
        )
        assert result.decision == RiskDecision.FLATTEN
        assert "全局熔断" in result.reason

    def test_reset_clears_halt(self):
        """reset 清除熔断状态。"""
        rule = L3DrawdownRule()
        rule.halt_all()
        assert rule.is_halted
        rule.reset()
        assert not rule.is_halted

    def test_reset_after_drawdown_flatten(self):
        """回撤触发后 reset 可恢复。"""
        rule = L3DrawdownRule()
        rule.check(
            equity=Decimal("80000"),
            peak_equity=Decimal("100000"),
            daily_pnl=Decimal("0"),
        )
        assert rule.is_halted
        rule.reset()
        result = rule.check(
            equity=Decimal("100000"),
            peak_equity=Decimal("100000"),
            daily_pnl=Decimal("0"),
        )
        assert result.decision == RiskDecision.APPROVE

    # ── _check_max_drawdown 边界 ──

    def test_drawdown_division_by_zero_handled(self):
        """peak_equity 导致除零时返回 None。"""
        rule = L3DrawdownRule()
        # 直接调用 _check_max_drawdown 测试 except 分支
        # Decimal("NaN") 可能导致 InvalidOperation
        result = rule._check_max_drawdown(Decimal("100"), Decimal("0"), time.time_ns())
        # peak_equity=0 应该返回 None (DivisionByZero)
        assert result is None


# ════════════════════════════════════════════════════════════════
# L4 熔断器测试
# ════════════════════════════════════════════════════════════════


class TestL4CircuitBreaker:
    """L4 熔断器 - 完整覆盖"""

    def test_initial_state_closed(self):
        """初始状态为 CLOSED。"""
        cb = L4CircuitBreaker()
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.failure_count == 0
        assert cb.half_open_probes == 0

    # ── CLOSED 状态 ──

    def test_closed_should_allow(self):
        """CLOSED 状态允许请求。"""
        cb = L4CircuitBreaker()
        assert cb.should_allow() is True

    def test_closed_check_approves(self):
        """CLOSED 状态 check 返回 APPROVE。"""
        cb = L4CircuitBreaker()
        result = cb.check(_make_order(), [])
        assert result.decision == RiskDecision.APPROVE
        assert "正常" in result.reason

    def test_record_success_in_closed(self):
        """CLOSED 状态 record_success 重置计数。"""
        cb = L4CircuitBreaker()
        cb.record_failure()
        cb.record_failure()
        assert cb.failure_count == 2
        cb.record_success()
        assert cb.failure_count == 0
        assert cb.state == CircuitBreakerState.CLOSED

    def test_record_failure_below_threshold(self):
        """失败次数未达阈值保持 CLOSED。"""
        cb = L4CircuitBreaker()
        for _ in range(FAILURE_THRESHOLD - 1):
            cb.record_failure()
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.failure_count == FAILURE_THRESHOLD - 1

    def test_record_failure_reaches_threshold(self):
        """失败次数达到阈值触发 OPEN。"""
        cb = L4CircuitBreaker()
        for _ in range(FAILURE_THRESHOLD):
            cb.record_failure()
        assert cb.state == CircuitBreakerState.OPEN
        assert cb.failure_count == FAILURE_THRESHOLD

    # ── OPEN 状态 ──

    def test_open_should_not_allow(self):
        """OPEN 状态不允许请求。"""
        cb = L4CircuitBreaker()
        for _ in range(FAILURE_THRESHOLD):
            cb.record_failure()
        assert cb.should_allow() is False

    def test_open_check_returns_flatten(self):
        """OPEN 状态 check 返回 FLATTEN。"""
        cb = L4CircuitBreaker()
        for _ in range(FAILURE_THRESHOLD):
            cb.record_failure()
        result = cb.check(_make_order(), [])
        assert result.decision == RiskDecision.FLATTEN
        assert "熔断器已开启" in result.reason

    def test_open_to_half_open_after_timeout(self):
        """OPEN 超时后进入 HALF_OPEN。"""
        cb = L4CircuitBreaker()
        for _ in range(FAILURE_THRESHOLD):
            cb.record_failure()
        assert cb.state == CircuitBreakerState.OPEN

        # 模拟超时
        cb._open_since = time.time() - RECOVERY_TIMEOUT_SEC - 1
        assert cb.should_allow() is True
        assert cb.state == CircuitBreakerState.HALF_OPEN

    def test_open_check_transitions_to_half_open(self):
        """OPEN 超时后 check 转 HALF_OPEN 并允许探测。"""
        cb = L4CircuitBreaker()
        for _ in range(FAILURE_THRESHOLD):
            cb.record_failure()

        cb._open_since = time.time() - RECOVERY_TIMEOUT_SEC - 1
        result = cb.check(_make_order(), [])
        assert result.decision == RiskDecision.APPROVE
        assert "半开" in result.reason
        assert cb.state == CircuitBreakerState.HALF_OPEN

    def test_open_not_timed_out_still_flatten(self):
        """OPEN 未超时时 check 仍返回 FLATTEN。"""
        cb = L4CircuitBreaker()
        for _ in range(FAILURE_THRESHOLD):
            cb.record_failure()
        result = cb.check(_make_order(), [])
        assert result.decision == RiskDecision.FLATTEN

    # ── HALF_OPEN 状态 ──

    def test_half_open_should_allow_within_probes(self):
        """HALF_OPEN 在探测次数内允许。"""
        cb = L4CircuitBreaker()
        for _ in range(FAILURE_THRESHOLD):
            cb.record_failure()
        cb._open_since = time.time() - RECOVERY_TIMEOUT_SEC - 1
        cb.should_allow()  # transition to HALF_OPEN
        assert cb.state == CircuitBreakerState.HALF_OPEN

        for i in range(HALF_OPEN_MAX_PROBES):
            assert cb.should_allow() is True
        assert cb.half_open_probes == HALF_OPEN_MAX_PROBES

    def test_half_open_probes_exhausted_reopens(self):
        """HALF_OPEN 探测次数用完重新 OPEN。"""
        cb = L4CircuitBreaker()
        for _ in range(FAILURE_THRESHOLD):
            cb.record_failure()
        cb._open_since = time.time() - RECOVERY_TIMEOUT_SEC - 1
        cb.should_allow()  # → HALF_OPEN

        for _ in range(HALF_OPEN_MAX_PROBES):
            cb.should_allow()
        # 探测次数用完
        assert cb.should_allow() is False
        assert cb.state == CircuitBreakerState.OPEN

    def test_half_open_check_within_probes(self):
        """HALF_OPEN check 在探测次数内返回 APPROVE。"""
        cb = L4CircuitBreaker()
        for _ in range(FAILURE_THRESHOLD):
            cb.record_failure()
        cb._open_since = time.time() - RECOVERY_TIMEOUT_SEC - 1
        cb.check(_make_order(), [])  # → HALF_OPEN

        result = cb.check(_make_order(), [])
        assert result.decision == RiskDecision.APPROVE
        assert "探测" in result.reason

    def test_half_open_check_probes_exhausted(self):
        """HALF_OPEN check 探测次数用完返回 FLATTEN。"""
        cb = L4CircuitBreaker()
        for _ in range(FAILURE_THRESHOLD):
            cb.record_failure()
        cb._open_since = time.time() - RECOVERY_TIMEOUT_SEC - 1
        cb.check(_make_order(), [])  # OPEN → HALF_OPEN, probes=0

        # 第1次: probes 0→1, APPROVE
        cb.check(_make_order(), [])
        # 第2次: probes 1→2, APPROVE
        cb.check(_make_order(), [])
        # 第3次: probes 2→3, APPROVE
        cb.check(_make_order(), [])
        # 第4次: probes=3 >= HALF_OPEN_MAX_PROBES → OPEN, FLATTEN
        result = cb.check(_make_order(), [])
        assert result.decision == RiskDecision.FLATTEN
        assert "探测次数用完" in result.reason

    def test_half_open_success_returns_to_closed(self):
        """HALF_OPEN record_success 恢复 CLOSED。"""
        cb = L4CircuitBreaker()
        for _ in range(FAILURE_THRESHOLD):
            cb.record_failure()
        cb._open_since = time.time() - RECOVERY_TIMEOUT_SEC - 1
        cb.should_allow()  # → HALF_OPEN

        cb.record_success()
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.failure_count == 0
        assert cb.half_open_probes == 0

    def test_half_open_failure_reopens(self):
        """HALF_OPEN record_failure 重新 OPEN。"""
        cb = L4CircuitBreaker()
        for _ in range(FAILURE_THRESHOLD):
            cb.record_failure()
        cb._open_since = time.time() - RECOVERY_TIMEOUT_SEC - 1
        cb.should_allow()  # → HALF_OPEN

        cb.record_failure()
        assert cb.state == CircuitBreakerState.OPEN
        assert cb.half_open_probes == 0

    # ── should_all HALF_OPEN 分支 ──

    def test_half_open_should_allow_probes_tracked(self):
        """HALF_OPEN should_allow 跟踪探测次数。"""
        cb = L4CircuitBreaker()
        for _ in range(FAILURE_THRESHOLD):
            cb.record_failure()
        cb._open_since = time.time() - RECOVERY_TIMEOUT_SEC - 1
        cb.should_allow()  # → HALF_OPEN

        for i in range(HALF_OPEN_MAX_PROBES):
            cb.should_allow()
            assert cb.half_open_probes == i + 1

    # ── half_open_probes property ──

    def test_half_open_probes_property(self):
        """half_open_probes 属性正确返回。"""
        cb = L4CircuitBreaker()
        assert cb.half_open_probes == 0

    # ── reset ──

    def test_reset_restores_initial_state(self):
        """reset 恢复初始状态。"""
        cb = L4CircuitBreaker()
        for _ in range(FAILURE_THRESHOLD):
            cb.record_failure()
        cb.reset()
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.failure_count == 0
        assert cb.half_open_probes == 0
        assert cb._open_since == 0.0

    def test_reset_from_half_open(self):
        """从 HALF_OPEN 状态 reset。"""
        cb = L4CircuitBreaker()
        for _ in range(FAILURE_THRESHOLD):
            cb.record_failure()
        cb._open_since = time.time() - RECOVERY_TIMEOUT_SEC - 1
        cb.should_allow()  # → HALF_OPEN
        cb.reset()
        assert cb.state == CircuitBreakerState.CLOSED

    # ── 完整生命周期 ──

    def test_full_lifecycle_closed_open_half_open_closed(self):
        """完整生命周期: CLOSED → OPEN → HALF_OPEN → CLOSED。"""
        cb = L4CircuitBreaker()

        # CLOSED → OPEN
        assert cb.state == CircuitBreakerState.CLOSED
        for _ in range(FAILURE_THRESHOLD):
            cb.record_failure()
        assert cb.state == CircuitBreakerState.OPEN

        # OPEN → HALF_OPEN
        cb._open_since = time.time() - RECOVERY_TIMEOUT_SEC - 1
        cb.should_allow()
        assert cb.state == CircuitBreakerState.HALF_OPEN

        # HALF_OPEN → CLOSED
        cb.record_success()
        assert cb.state == CircuitBreakerState.CLOSED

    def test_full_lifecycle_with_reopen(self):
        """生命周期含重新熔断: CLOSED → OPEN → HALF_OPEN → OPEN → HALF_OPEN → CLOSED。"""
        cb = L4CircuitBreaker()

        # CLOSED → OPEN
        for _ in range(FAILURE_THRESHOLD):
            cb.record_failure()

        # OPEN → HALF_OPEN
        cb._open_since = time.time() - RECOVERY_TIMEOUT_SEC - 1
        cb.should_allow()

        # HALF_OPEN → OPEN (探测失败)
        cb.record_failure()
        assert cb.state == CircuitBreakerState.OPEN

        # OPEN → HALF_OPEN (再次)
        cb._open_since = time.time() - RECOVERY_TIMEOUT_SEC - 1
        cb.should_allow()

        # HALF_OPEN → CLOSED (探测成功)
        cb.record_success()
        assert cb.state == CircuitBreakerState.CLOSED

    def test_should_allow_unknown_state_returns_false(self):
        """should_allow 未知状态返回 False。"""
        cb = L4CircuitBreaker()
        # 设置一个无效状态
        cb._state = "invalid_state"  # type: ignore
        assert cb.should_allow() is False

    def test_check_unknown_state_returns_reject(self):
        """check 未知状态返回 REJECT。"""
        cb = L4CircuitBreaker()
        cb._state = "invalid_state"  # type: ignore
        result = cb.check(_make_order(), [])
        assert result.decision == RiskDecision.REJECT
        assert "未知状态" in result.reason

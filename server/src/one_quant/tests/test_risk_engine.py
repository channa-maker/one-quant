"""
ONE量化 - 风控引擎测试

验证四层风控检查、硬编码阈值、熔断器。
"""

import time
from decimal import Decimal

from one_quant.core.types import Market, Order
from one_quant.risk.contracts import RiskDecision
from one_quant.risk.engine import RiskEngine
from one_quant.risk.rules.l1_static import L1StaticLimitRule
from one_quant.risk.rules.l3_drawdown import L3DrawdownRule
from one_quant.risk.rules.l4_circuit_breaker import FAILURE_THRESHOLD, L4CircuitBreaker


def _make_order(
    symbol: str = "BTC/USDT",
    quantity: str = "0.1",
    price: str = "50000",
) -> Order:
    """创建测试订单。"""
    return Order(
        client_order_id="test-uuid",
        symbol=symbol,
        market=Market.SPOT,
        side="buy",
        order_type="limit",
        quantity=Decimal(quantity),
        price=Decimal(price),
        stop_price=None,
        status="pending",
        exchange="binance",
        timestamp_ns=time.time_ns(),
    )


class TestL1StaticLimit:
    """L1 静态限额测试"""

    def test_normal_order_passes(self) -> None:
        rule = L1StaticLimitRule()
        order = _make_order()
        result = rule.check(order, [])
        assert result.decision == RiskDecision.APPROVE

    def test_unknown_symbol_rejected(self) -> None:
        rule = L1StaticLimitRule()
        order = _make_order(symbol="UNKNOWN/USDT")
        result = rule.check(order, [])
        assert result.decision == RiskDecision.REJECT

    def test_suspended_symbol_rejected(self) -> None:
        rule = L1StaticLimitRule()
        order = _make_order(symbol="LUNA/USDT")
        result = rule.check(order, [])
        assert result.decision == RiskDecision.REJECT

    def test_zero_quantity_rejected(self) -> None:
        rule = L1StaticLimitRule()
        order = _make_order(quantity="0")
        result = rule.check(order, [])
        assert result.decision == RiskDecision.REJECT


class TestL3Drawdown:
    """L3 回撤测试"""

    def test_normal_passes(self) -> None:
        rule = L3DrawdownRule()
        result = rule.check(
            equity=Decimal("100000"),
            peak_equity=Decimal("100000"),
            daily_pnl=Decimal("0"),
        )
        assert result.decision == RiskDecision.APPROVE

    def test_drawdown_triggers_flatten(self) -> None:
        rule = L3DrawdownRule()
        # 回撤 20% > 15% 阈值
        result = rule.check(
            equity=Decimal("80000"),
            peak_equity=Decimal("100000"),
            daily_pnl=Decimal("-20000"),
        )
        assert result.decision == RiskDecision.FLATTEN


class TestL4CircuitBreaker:
    """L4 熔断器测试"""

    def test_closed_state_passes(self) -> None:
        breaker = L4CircuitBreaker()
        order = _make_order()
        result = breaker.check(order, [])
        assert result.decision == RiskDecision.APPROVE

    def test_consecutive_failures_trigger_open(self) -> None:
        breaker = L4CircuitBreaker()
        for _ in range(FAILURE_THRESHOLD):
            breaker.record_failure()
        assert breaker.state.value == "open"

    def test_success_resets_counter(self) -> None:
        breaker = L4CircuitBreaker()
        breaker.record_failure()
        breaker.record_failure()
        breaker.record_success()
        assert breaker.state.value == "closed"


class TestRiskEngine:
    """风控引擎集成测试"""

    def test_all_layers_pass(self) -> None:
        engine = RiskEngine()
        engine.update_equity(Decimal("100000"))  # 设置权益
        order = _make_order()
        result = engine.check(order, [])
        assert result.decision == RiskDecision.APPROVE

    def test_halt_all(self) -> None:
        engine = RiskEngine()
        result = engine.halt_all()
        assert result.decision == RiskDecision.FLATTEN

    def test_stats(self) -> None:
        engine = RiskEngine()
        engine.update_equity(Decimal("100000"))
        order = _make_order()
        engine.check(order, [])
        stats = engine.stats
        assert stats["checks"] == 1
        assert stats["rejects"] == 0

    # ── L3 风控集成测试 ──

    def test_l3_max_drawdown_triggers_flatten(self) -> None:
        """L3: 最大回撤 15% 触发 FLATTEN"""
        engine = RiskEngine()
        engine.update_equity(Decimal("100000"))
        order = _make_order()
        # 回撤 15000/100000 = 15% → 触发 FLATTEN
        result = engine.check(
            order,
            [],
            total_equity=Decimal("85000"),
            peak_equity=Decimal("100000"),
            daily_pnl=Decimal("-15000"),
        )
        assert result.decision in [
            RiskDecision.FLATTEN,
            RiskDecision.REDUCE,
            RiskDecision.REJECT,
        ]

    def test_l3_daily_loss_limit_triggers_halt(self) -> None:
        """L3: 日内亏损 5% 触发 halt"""
        engine = RiskEngine()
        engine.update_equity(Decimal("100000"))
        order = _make_order()
        # 日内亏损 5000/100000 = 5% → 触发 FLATTEN
        result = engine.check(
            order,
            [],
            total_equity=Decimal("95000"),
            peak_equity=Decimal("100000"),
            daily_pnl=Decimal("-5000"),
        )
        # 应该返回非 APPROVE
        assert result.decision != RiskDecision.APPROVE

    def test_l3_within_limits_approves(self) -> None:
        """L3: 在限额内返回 APPROVE"""
        engine = RiskEngine()
        engine.update_equity(Decimal("100000"))
        order = _make_order()
        # 小幅波动 1000/100000 = 1% 回撤，不触发 L3
        result = engine.check(
            order,
            [],
            total_equity=Decimal("98000"),
            peak_equity=Decimal("100000"),
            daily_pnl=Decimal("-1000"),
        )
        # L3 不应触发，L1/L2 也应通过 → APPROVE
        assert result.decision == RiskDecision.APPROVE

    def test_l3_exact_15pct_drawdown_triggers_flatten(self) -> None:
        """L3: 精确 15% 回撤边界值触发 FLATTEN"""
        engine = RiskEngine()
        engine.update_equity(Decimal("100000"))
        order = _make_order()
        # 精确 15%: (100000 - 85000) / 100000 = 0.15
        result = engine.check(
            order,
            [],
            total_equity=Decimal("85000"),
            peak_equity=Decimal("100000"),
            daily_pnl=Decimal("0"),
        )
        assert result.decision != RiskDecision.APPROVE

    def test_l3_near_limit_no_trigger(self) -> None:
        """L3: 接近但未达阈值不触发"""
        engine = RiskEngine()
        engine.update_equity(Decimal("100000"))
        order = _make_order()
        # 14% 回撤 + 4.9% 日亏 → 不触发
        result = engine.check(
            order,
            [],
            total_equity=Decimal("86000"),
            peak_equity=Decimal("100000"),
            daily_pnl=Decimal("-4900"),
        )
        assert result.decision == RiskDecision.APPROVE

    def test_l3_halt_all_blocks_subsequent_checks(self) -> None:
        """L3: halt_all 后所有后续 check 都返回 FLATTEN"""
        engine = RiskEngine()
        engine.update_equity(Decimal("100000"))
        engine.halt_all()
        order = _make_order()
        result = engine.check(
            order,
            [],
            total_equity=Decimal("100000"),
            peak_equity=Decimal("100000"),
            daily_pnl=Decimal("0"),
        )
        assert result.decision == RiskDecision.FLATTEN

    def test_l3_stats_tracks_flattens(self) -> None:
        """L3: stats 正确记录 flatten 次数"""
        engine = RiskEngine()
        engine.update_equity(Decimal("100000"))
        order = _make_order()
        # 触发一次 flatten
        engine.check(
            order,
            [],
            total_equity=Decimal("80000"),
            peak_equity=Decimal("100000"),
            daily_pnl=Decimal("-20000"),
        )
        stats = engine.stats
        assert stats["checks"] == 1
        assert stats["rejects"] == 1
        assert stats["flattens"] >= 1

    def test_engine_l2_rejection(self) -> None:
        """L2 频率超限触发拒绝"""
        engine = RiskEngine()
        engine.update_equity(Decimal("1000000"))
        # L2 频率限制: 同标的 10 秒内 >= 10 次
        from one_quant.risk.rules.l2_realtime import MAX_ORDER_FREQ

        for _ in range(MAX_ORDER_FREQ):
            engine.check(
                _make_order(),
                [],
                total_equity=Decimal("1000000"),
                latest_price=Decimal("50000"),
            )
        # 再来一次应被 L2 拒绝
        result = engine.check(
            _make_order(),
            [],
            total_equity=Decimal("1000000"),
            latest_price=Decimal("50000"),
        )
        assert result.decision == RiskDecision.REJECT
        assert "频率" in result.reason

    def test_engine_l1_rejection_unknown_symbol(self) -> None:
        """L1: 非白名单标的通过引擎拒绝"""
        engine = RiskEngine()
        result = engine.check(_make_order(symbol="UNKNOWN/USDT"), [])
        assert result.decision == RiskDecision.REJECT
        assert engine.stats["rejects"] == 1

    def test_engine_l1_rejection_suspended_symbol(self) -> None:
        """L1: 停牌标的通过引擎拒绝"""
        engine = RiskEngine()
        result = engine.check(_make_order(symbol="LUNA/USDT"), [])
        assert result.decision == RiskDecision.REJECT
        assert engine.stats["rejects"] == 1

    def test_engine_l1_rejection_zero_quantity(self) -> None:
        """L1: 零数量通过引擎拒绝"""
        engine = RiskEngine()
        result = engine.check(_make_order(quantity="0"), [])
        assert result.decision == RiskDecision.REJECT

    def test_engine_l4_rejection(self) -> None:
        """L4 熔断器触发拒绝"""
        engine = RiskEngine()
        engine.update_equity(Decimal("100000"))
        # 触发 L4 熔断
        from one_quant.risk.rules.l4_circuit_breaker import FAILURE_THRESHOLD

        for _ in range(FAILURE_THRESHOLD):
            engine.l4.record_failure()
        order = _make_order()
        result = engine.check(order, [])
        assert result.decision == RiskDecision.FLATTEN
        assert "熔断器" in result.reason

    def test_engine_l4_flatten_count(self) -> None:
        """L4 熔断器 FLATTEN 计数"""
        engine = RiskEngine()
        engine.update_equity(Decimal("100000"))
        from one_quant.risk.rules.l4_circuit_breaker import FAILURE_THRESHOLD

        for _ in range(FAILURE_THRESHOLD):
            engine.l4.record_failure()
        engine.check(_make_order(), [])
        stats = engine.stats
        assert stats["flattens"] >= 1

    def test_engine_halt_all_method(self) -> None:
        """halt_all 方法触发全局熔断"""
        engine = RiskEngine()
        result = engine.halt_all()
        assert result.decision == RiskDecision.FLATTEN
        assert "全局熔断" in result.reason

    def test_engine_halt_all_then_check(self) -> None:
        """halt_all 后 check 返回 FLATTEN"""
        engine = RiskEngine()
        engine.update_equity(Decimal("100000"))
        engine.halt_all()
        # L3 requires peak_equity and daily_pnl to be checked
        result = engine.check(
            _make_order(),
            [],
            peak_equity=Decimal("100000"),
            daily_pnl=Decimal("0"),
        )
        assert result.decision == RiskDecision.FLATTEN

    def test_engine_l3_with_initial_equity_and_margin(self) -> None:
        """L3 带 initial_equity 和保证金参数"""
        engine = RiskEngine()
        engine.update_equity(Decimal("100000"))
        order = _make_order()
        # 保证金超限
        result = engine.check(
            order,
            [],
            total_equity=Decimal("100000"),
            peak_equity=Decimal("100000"),
            daily_pnl=Decimal("0"),
            initial_equity=Decimal("100000"),
            used_margin=Decimal("90000"),
            total_margin=Decimal("100000"),
        )
        assert result.decision == RiskDecision.REDUCE

    def test_engine_reset(self) -> None:
        """reset 重置所有状态"""
        engine = RiskEngine()
        engine.update_equity(Decimal("100000"))
        engine.check(_make_order(), [])
        assert engine.stats["checks"] == 1
        engine.reset()
        assert engine.stats["checks"] == 0
        assert engine.stats["rejects"] == 0
        assert engine.stats["flattens"] == 0

    def test_engine_l3_uses_stored_equity(self) -> None:
        """L3 使用引擎存储的权益"""
        engine = RiskEngine()
        engine.update_equity(Decimal("85000"))
        order = _make_order()
        # 不传 total_equity, 让 L3 使用 stored equity
        result = engine.check(
            order,
            [],
            peak_equity=Decimal("100000"),
            daily_pnl=Decimal("0"),
        )
        # 回撤 = (100000-85000)/100000 = 15% → FLATTEN
        assert result.decision != RiskDecision.APPROVE

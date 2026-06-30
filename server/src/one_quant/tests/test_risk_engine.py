"""
ONE量化 - 风控引擎测试

验证四层风控检查、硬编码阈值、熔断器。
"""

import time
from decimal import Decimal

from one_quant.core.types import Market, Order, PositionState
from one_quant.risk.contracts import RiskDecision
from one_quant.risk.engine import RiskEngine
from one_quant.risk.rules.l1_static import L1StaticLimitRule, TRADABLE_SYMBOLS
from one_quant.risk.rules.l3_drawdown import L3DrawdownRule
from one_quant.risk.rules.l4_circuit_breaker import L4CircuitBreaker, FAILURE_THRESHOLD


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

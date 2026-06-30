"""
ONE量化 - 压力测试引擎测试

覆盖：
  - 危机场景定义完整性
  - 模拟场景回放
  - 压力 VaR 计算
  - 风控触发验证
  - 多场景汇总
"""

import asyncio
import time
from decimal import Decimal

import pytest

from one_quant.risk.stress_test import (
    CrisisScenario,
    StressResult,
    StressTestEngine,
)


# ──────────────────────────── 辅助工具 ────────────────────────────


def _make_portfolio() -> list[dict]:
    """构造测试组合。"""
    return [
        {"symbol": "BTC", "weight": 0.5, "value": Decimal("50000")},
        {"symbol": "ETH", "weight": 0.3, "value": Decimal("30000")},
        {"symbol": "SOL", "weight": 0.2, "value": Decimal("20000")},
    ]


# ──────────────────────────── 危机场景测试 ────────────────────────────


class TestCrisisScenarios:
    """危机场景定义测试"""

    def test_scenario_count(self):
        """危机场景库包含预定义场景。"""
        engine = StressTestEngine()
        scenarios = engine.get_scenarios()
        assert len(scenarios) >= 4

    def test_scenario_fields(self):
        """每个场景包含必要字段。"""
        engine = StressTestEngine()
        for scenario in engine.get_scenarios():
            assert isinstance(scenario, CrisisScenario)
            assert len(scenario.name) > 0
            assert scenario.start_time > 0
            assert scenario.end_time > scenario.start_time
            assert len(scenario.description) > 0
            assert len(scenario.tick_data_path) > 0
            assert isinstance(scenario.expected_impact, dict)

    def test_scenario_expected_impact_keys(self):
        """场景预期影响包含必要键。"""
        engine = StressTestEngine()
        required_keys = {"btc_drawdown_pct", "alt_drawdown_pct", "duration_hours"}
        for scenario in engine.get_scenarios():
            for key in required_keys:
                assert key in scenario.expected_impact, f"场景 {scenario.name} 缺少 {key}"

    def test_scenario_frozen(self):
        """场景对象不可变。"""
        engine = StressTestEngine()
        scenario = engine.get_scenarios()[0]
        with pytest.raises(Exception):
            scenario.name = "modified"


# ──────────────────────────── 模拟场景回放测试 ────────────────────────────


class TestScenarioReplay:
    """场景回放测试"""

    def test_simulate_scenario_returns_result(self):
        """模拟场景返回 StressResult。"""
        engine = StressTestEngine()
        scenario = engine.get_scenarios()[0]
        # tick 数据文件不存在，走模拟路径
        result = asyncio.get_event_loop().run_until_complete(
            engine.run_scenario(scenario, "test_strategy")
        )
        assert isinstance(result, StressResult)
        assert result.scenario == scenario.name

    def test_simulate_scenario_loss_positive(self):
        """模拟场景最大亏损为正数。"""
        engine = StressTestEngine()
        scenario = engine.get_scenarios()[0]
        result = asyncio.get_event_loop().run_until_complete(
            engine.run_scenario(scenario, "test", initial_equity=Decimal("100000"))
        )
        assert result.max_loss > Decimal("0")

    def test_simulate_scenario_drawdown_pct(self):
        """模拟场景回撤百分比合理。"""
        engine = StressTestEngine()
        scenario = engine.get_scenarios()[0]
        result = asyncio.get_event_loop().run_until_complete(
            engine.run_scenario(scenario, "test")
        )
        assert 0 < result.max_drawdown_pct < 100

    def test_simulate_scenario_risk_controls(self):
        """大幅回撤时触发风控。"""
        engine = StressTestEngine()
        # 找一个预期回撤大的场景
        worst = max(engine.get_scenarios(), key=lambda s: abs(s.expected_impact.get("alt_drawdown_pct", 0)))
        result = asyncio.get_event_loop().run_until_complete(
            engine.run_scenario(worst, "test")
        )
        # 如果回撤 > 15%，应有风控触发
        if result.max_drawdown_pct > 15:
            assert len(result.risk_controls_triggered) > 0

    def test_run_all_scenarios(self):
        """运行所有场景返回结果列表。"""
        engine = StressTestEngine()
        results = asyncio.get_event_loop().run_until_complete(
            engine.run_all_scenarios("test_strategy")
        )
        assert len(results) == len(engine.get_scenarios())
        for r in results:
            assert isinstance(r, StressResult)

    def test_results_history_accumulated(self):
        """历史结果累积。"""
        engine = StressTestEngine()
        asyncio.get_event_loop().run_until_complete(
            engine.run_all_scenarios("test")
        )
        assert len(engine.results_history) == len(engine.get_scenarios())


# ──────────────────────────── 压力 VaR 测试 ────────────────────────────


class TestStressVaR:
    """压力 VaR 计算测试"""

    def test_stress_var_positive(self):
        """压力 VaR 为正数。"""
        engine = StressTestEngine()
        portfolio = _make_portfolio()
        var = engine.stress_var(portfolio)
        assert var > Decimal("0")

    def test_stress_var_with_confidence(self):
        """更高置信度对应更高 VaR。"""
        engine = StressTestEngine()
        portfolio = _make_portfolio()
        var_95 = engine.stress_var(portfolio, confidence=0.95)
        var_99 = engine.stress_var(portfolio, confidence=0.99)
        assert var_99 >= var_95

    def test_stress_var_empty_portfolio(self):
        """空组合 VaR 为零。"""
        engine = StressTestEngine()
        assert engine.stress_var([]) == Decimal("0")

    def test_stress_var_larger_portfolio_larger_var(self):
        """更大持仓对应更大 VaR。"""
        engine = StressTestEngine()
        small = [{"symbol": "BTC", "weight": 1.0, "value": Decimal("10000")}]
        large = [{"symbol": "BTC", "weight": 1.0, "value": Decimal("100000")}]
        var_small = engine.stress_var(small)
        var_large = engine.stress_var(large)
        assert var_large > var_small

    def test_stress_var_specific_scenarios(self):
        """指定场景列表计算 VaR。"""
        engine = StressTestEngine()
        portfolio = _make_portfolio()
        scenarios = engine.get_scenarios()[:2]
        var = engine.stress_var(portfolio, scenarios=scenarios)
        assert var > Decimal("0")


# ──────────────────────────── 风控触发验证测试 ────────────────────────────


class TestRiskControlTriggers:
    """风控触发验证测试"""

    def test_stress_result_has_risk_controls_field(self):
        """StressResult 包含风控触发字段。"""
        engine = StressTestEngine()
        scenario = engine.get_scenarios()[0]
        result = asyncio.get_event_loop().run_until_complete(
            engine.run_scenario(scenario, "test")
        )
        assert hasattr(result, "risk_controls_triggered")
        assert isinstance(result.risk_controls_triggered, list)

    def test_stress_result_fields_complete(self):
        """StressResult 所有字段完整。"""
        engine = StressTestEngine()
        scenario = engine.get_scenarios()[0]
        result = asyncio.get_event_loop().run_until_complete(
            engine.run_scenario(scenario, "test")
        )
        assert result.scenario != ""
        assert result.max_loss >= Decimal("0")
        assert result.max_drawdown >= Decimal("0")
        assert isinstance(result.max_drawdown_pct, float)
        assert isinstance(result.sharpe_during_crisis, float)
        assert isinstance(result.trade_count, int)
        assert isinstance(result.notes, str)
        assert result.timestamp_ns > 0

    def test_stress_result_frozen(self):
        """StressResult 不可变。"""
        result = StressResult(
            scenario="test",
            max_loss=Decimal("1000"),
            max_loss_pct=10.0,
            max_drawdown=Decimal("1000"),
            max_drawdown_pct=10.0,
            recovery_time_sec=-1,
            total_pnl=Decimal("-1000"),
            sharpe_during_crisis=-2.0,
            risk_controls_triggered=["L3"],
            trade_count=0,
            notes="test",
            timestamp_ns=time.time_ns(),
        )
        with pytest.raises(Exception):
            result.scenario = "modified"


# ──────────────────────────── 多场景汇总测试 ────────────────────────────


class TestStressSummary:
    """多场景汇总测试"""

    def test_all_scenarios_covered(self):
        """所有场景都有结果。"""
        engine = StressTestEngine()
        results = asyncio.get_event_loop().run_until_complete(
            engine.run_all_scenarios("test")
        )
        scenario_names = {s.name for s in engine.get_scenarios()}
        result_names = {r.scenario for r in results}
        assert scenario_names == result_names

    def test_worst_scenario_identifiable(self):
        """可识别最差场景。"""
        engine = StressTestEngine()
        results = asyncio.get_event_loop().run_until_complete(
            engine.run_all_scenarios("test")
        )
        worst = max(results, key=lambda r: r.max_drawdown_pct)
        assert worst.max_drawdown_pct > 0

    def test_results_history_persists(self):
        """运行后历史结果持久化。"""
        engine = StressTestEngine()
        asyncio.get_event_loop().run_until_complete(
            engine.run_all_scenarios("test")
        )
        assert len(engine.results_history) > 0

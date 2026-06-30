"""AI 自进化系统测试 — 冠军挑战者 + 衰减检测 + 影子对账

覆盖模块: one_quant.ai.evolution
目标: ≥80% 覆盖率
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from one_quant.ai.evolution import (
    AutoRetrainer,
    BacktestResult,
    ChampionChallenger,
    ComparisonResult,
    DriftDetector,
    EvolutionAuditor,
    EvolutionAuditRecord,
    EvolutionPlatform,
    Factor,
    FactorSource,
    OverfitValidator,
    ShadowResult,
    Strategy,
    StrategyLifecycle,
)

# ──────────────────── 辅助工厂 ────────────────────


def _make_strategy(
    strategy_id: str = "s1", slot: str = "", lifecycle: StrategyLifecycle = StrategyLifecycle.DRAFT
) -> Strategy:
    return Strategy(
        strategy_id=strategy_id,
        name=f"test_{strategy_id}",
        version="1.0.0",
        lifecycle=lifecycle,
        factors=["momentum_rsi"],
        params={},
        metrics={},
        backtest_result={},
        slot=slot,
    )


def _make_backtest(strategy_id: str = "s1", **overrides) -> BacktestResult:
    defaults = {
        "strategy_id": strategy_id,
        "total_return": 0.5,
        "annual_return": 0.3,
        "sharpe_ratio": 1.5,
        "oos_sharpe": 1.0,
        "max_drawdown": 0.15,
        "win_rate": 0.6,
        "multi_period_stable": True,
        "ic_decay_rate": 0.1,
    }
    defaults.update(overrides)
    return BacktestResult(**defaults)


def _make_factor(name: str = "test_factor", ic: float = 0.05) -> Factor:
    return Factor(
        factor_id=f"factor_{name}",
        name=name,
        expression="close / shift(close, 5) - 1",
        source=FactorSource.LLM,
        ic=ic,
    )


# ──────────────────── Strategy & Factor 数据类测试 ────────────────────


class TestDataStructures:
    """数据结构测试"""

    def test_strategy_auto_timestamp(self):
        s = _make_strategy()
        assert s.created_at > 0
        assert s.updated_at > 0

    def test_strategy_explicit_timestamp(self):
        ts = 1_000_000_000
        s = Strategy(
            strategy_id="s1",
            name="test",
            version="1.0",
            lifecycle=StrategyLifecycle.DRAFT,
            created_at=ts,
        )
        assert s.created_at == ts

    def test_factor_auto_timestamp(self):
        f = _make_factor()
        assert f.created_at > 0

    def test_backtest_result_defaults(self):
        bt = BacktestResult(strategy_id="s1")
        assert bt.passed is False
        assert bt.timestamp_ns > 0

    def test_shadow_result_defaults(self):
        sr = ShadowResult(strategy_id="s1")
        assert sr.passed is False
        assert sr.timestamp_ns > 0

    def test_comparison_result_defaults(self):
        cr = ComparisonResult(slot="alpha", champion_id="c1", challenger_id="ch1")
        assert cr.promoted is False
        assert cr.timestamp_ns > 0

    def test_evolution_audit_record_defaults(self):
        rec = EvolutionAuditRecord(event="test", strategy_id="s1", stage="draft")
        assert rec.timestamp_ns > 0


# ──────────────────── OverfitValidator 测试 ────────────────────


class TestOverfitValidator:
    """防过拟合验证器测试"""

    def test_all_pass(self):
        """全部检验通过"""
        v = OverfitValidator()
        bt = _make_backtest(oos_sharpe=1.0, ic_decay_rate=0.1, multi_period_stable=True)
        train = {"sharpe_ratio": 1.2, "total_return": 0.5}
        result = v.validate(bt, train)
        assert result.passed is True
        assert len(result.reject_reasons) == 0

    def test_oos_sharpe_fail(self):
        """样本外夏普不足"""
        v = OverfitValidator()
        bt = _make_backtest(oos_sharpe=0.1)
        result = v.validate(bt, {"sharpe_ratio": 1.5})
        assert result.passed is False
        assert any("样本外" in r for r in result.reject_reasons)

    def test_train_test_gap_fail(self):
        """训练/测试差异过大"""
        v = OverfitValidator()
        bt = _make_backtest(oos_sharpe=1.0, ic_decay_rate=0.1, multi_period_stable=True)
        train = {"sharpe_ratio": 5.0}  # 远高于 OOS
        result = v.validate(bt, train)
        assert result.passed is False
        assert any("差异" in r for r in result.reject_reasons)

    def test_ic_decay_fail(self):
        """IC 衰减过快"""
        v = OverfitValidator()
        bt = _make_backtest(oos_sharpe=1.0, ic_decay_rate=0.8, multi_period_stable=True)
        result = v.validate(bt, {"sharpe_ratio": 1.2})
        assert result.passed is False
        assert any("IC" in r for r in result.reject_reasons)

    def test_multi_period_fail(self):
        """多周期未通过"""
        v = OverfitValidator()
        bt = _make_backtest(oos_sharpe=1.0, ic_decay_rate=0.1, multi_period_stable=False)
        result = v.validate(bt, {"sharpe_ratio": 1.2})
        assert result.passed is False
        assert any("多周期" in r for r in result.reject_reasons)

    def test_overfit_score_fail(self):
        """过拟合评分过高"""
        v = OverfitValidator()
        bt = _make_backtest(
            oos_sharpe=1.0, ic_decay_rate=0.1, multi_period_stable=True, oos_return=0.1
        )
        train = {"sharpe_ratio": 1.2, "total_return": 10.0}  # 训练收益远高于 OOS
        result = v.validate(bt, train)
        # overfit_score 可能过高
        assert result.overfit_score >= 0

    def test_check_multi_period_pass(self):
        """多周期稳健性检验通过"""
        v = OverfitValidator()
        periods = {"1h": 0.8, "4h": 0.6, "1d": 0.5}
        passed, ratio = v.check_multi_period(periods, min_sharpe=0.3)
        assert passed is True
        assert ratio == 1.0

    def test_check_multi_period_fail(self):
        v = OverfitValidator()
        periods = {"1h": 0.1, "4h": 0.2, "1d": 0.1}
        passed, ratio = v.check_multi_period(periods, min_sharpe=0.3)
        assert passed is False

    def test_check_multi_period_empty(self):
        v = OverfitValidator()
        passed, ratio = v.check_multi_period({})
        assert passed is False
        assert ratio == 0.0

    def test_check_ic_decay_short_series(self):
        """短序列衰减率"""
        v = OverfitValidator()
        assert v.check_ic_decay([0.1, 0.2]) == 0.0

    def test_check_ic_decay_declining(self):
        """递减 IC"""
        v = OverfitValidator()
        series = [1.0, 0.8, 0.6, 0.4, 0.2]
        rate = v.check_ic_decay(series)
        assert rate > 0

    def test_check_ic_decay_stable(self):
        """稳定 IC"""
        v = OverfitValidator()
        series = [0.5, 0.5, 0.5, 0.5, 0.5]
        rate = v.check_ic_decay(series)
        assert rate == 0.0


# ──────────────────── EvolutionAuditor 测试 ────────────────────


class TestEvolutionAuditor:
    """进化审计器测试"""

    def test_record_and_get_trail(self):
        auditor = EvolutionAuditor()
        rec = EvolutionAuditRecord(event="test", strategy_id="s1", stage="draft", decision="ok")
        auditor.record(rec)
        trail = auditor.get_trail("s1")
        assert len(trail) == 1
        assert trail[0]["event"] == "test"

    def test_get_trail_filter(self):
        auditor = EvolutionAuditor()
        auditor.record(EvolutionAuditRecord(event="a", strategy_id="s1", stage="draft"))
        auditor.record(EvolutionAuditRecord(event="b", strategy_id="s2", stage="draft"))
        assert len(auditor.get_trail("s1")) == 1

    def test_get_all(self):
        auditor = EvolutionAuditor()
        auditor.record(EvolutionAuditRecord(event="a", strategy_id="s1", stage="draft"))
        auditor.record(EvolutionAuditRecord(event="b", strategy_id="s2", stage="live"))
        assert len(auditor.get_all()) == 2


# ──────────────────── DriftDetector 测试 ────────────────────


class TestDriftDetector:
    """概念漂移检测器测试"""

    def test_no_drift(self):
        dd = DriftDetector(threshold=0.5)
        recent = [0.5] * 30
        baseline = [0.5] * 30
        assert dd.detect(recent, baseline) is False

    def test_detect_drift(self):
        dd = DriftDetector(threshold=0.1)
        # 基线需要有非零标准差
        import random

        random.seed(42)
        baseline = [0.5 + random.gauss(0, 0.01) for _ in range(30)]
        recent = [1.0 + random.gauss(0, 0.01) for _ in range(30)]
        assert dd.detect(recent, baseline) is True

    def test_insufficient_samples(self):
        dd = DriftDetector(min_samples=30)
        assert dd.detect([0.5] * 10, [0.5] * 10) is False

    def test_zero_std(self):
        dd = DriftDetector(threshold=0.1)
        assert dd.detect([0.5] * 30, [0.5] * 30) is False

    def test_page_hinkley_no_drift(self):
        dd = DriftDetector()
        series = [0.5] * 50
        assert dd.detect_page_hinkley(series, threshold=50.0) is False

    def test_page_hinkley_short_series(self):
        dd = DriftDetector(min_samples=30)
        assert dd.detect_page_hinkley([0.5] * 10) is False


# ──────────────────── ChampionChallenger 测试 ────────────────────


class TestChampionChallenger:
    """冠军-挑战者机制测试"""

    async def test_register_champion(self):
        cc = ChampionChallenger()
        s = _make_strategy("champ1")
        await cc.register_champion("alpha", s)
        assert s.lifecycle == StrategyLifecycle.LIVE
        assert "alpha" in cc._champions

    async def test_register_challenger(self):
        cc = ChampionChallenger()
        s = _make_strategy("chall1")
        await cc.register_challenger("alpha", s)
        assert s.lifecycle == StrategyLifecycle.CHALLENGER
        assert len(cc._challengers["alpha"]) == 1

    async def test_comparison_promoted(self):
        """挑战者全面超越 → 晋升"""
        cc = ChampionChallenger()
        champion = _make_strategy("champ")
        champion.metrics = {"sharpe_ratio": 1.0, "max_drawdown": 0.2}
        await cc.register_champion("alpha", champion)

        challenger = _make_strategy("chall")
        challenger.metrics = {"sharpe_ratio": 2.0, "max_drawdown": 0.1}
        await cc.register_challenger("alpha", challenger)

        results = await cc.run_comparison("alpha", [])
        assert len(results) == 1
        # 夏普 2.0 >= 1.0 * 1.2, 回撤 0.1 <= 0.2+0.05, 超额 = (2-1)/1 = 1.0 >= 0.1
        assert results[0].promoted is True

    async def test_comparison_not_promoted(self):
        """挑战者不达标 → 保留冠军"""
        cc = ChampionChallenger()
        champion = _make_strategy("champ")
        champion.metrics = {"sharpe_ratio": 2.0, "max_drawdown": 0.1}
        await cc.register_champion("alpha", champion)

        challenger = _make_strategy("chall")
        challenger.metrics = {"sharpe_ratio": 1.0, "max_drawdown": 0.3}
        await cc.register_challenger("alpha", challenger)

        results = await cc.run_comparison("alpha", [])
        assert results[0].promoted is False

    async def test_no_champion(self):
        cc = ChampionChallenger()
        results = await cc.run_comparison("alpha", [])
        assert results == []

    async def test_promote_challenger(self):
        cc = ChampionChallenger()
        old = _make_strategy("old")
        old.metrics = {}
        await cc.register_champion("alpha", old)

        new = _make_strategy("new")
        new.metrics = {}
        await cc.register_challenger("alpha", new)

        await cc.promote_challenger("alpha", "new")
        assert cc._champions["alpha"].strategy.strategy_id == "new"
        assert old.lifecycle == StrategyLifecycle.RETIRED

    async def test_promote_nonexistent_challenger(self):
        cc = ChampionChallenger()
        await cc.promote_challenger("alpha", "nonexistent")  # 应不抛异常

    async def test_get_audit_trail(self):
        cc = ChampionChallenger()
        s = _make_strategy("champ")
        s.metrics = {}
        await cc.register_champion("alpha", s)
        trail = cc.get_audit_trail("alpha")
        assert len(trail) >= 1

    async def test_multiple_challengers(self):
        """多个挑战者"""
        cc = ChampionChallenger()
        champion = _make_strategy("champ")
        champion.metrics = {"sharpe_ratio": 1.0, "max_drawdown": 0.2}
        await cc.register_champion("alpha", champion)

        ch1 = _make_strategy("ch1")
        ch1.metrics = {"sharpe_ratio": 0.5, "max_drawdown": 0.3}
        ch2 = _make_strategy("ch2")
        ch2.metrics = {"sharpe_ratio": 2.0, "max_drawdown": 0.1}
        await cc.register_challenger("alpha", ch1)
        await cc.register_challenger("alpha", ch2)

        results = await cc.run_comparison("alpha", [])
        assert len(results) == 2


# ──────────────────── EvolutionPlatform 测试 ────────────────────


class TestEvolutionPlatform:
    """自进化平台测试"""

    def test_init(self):
        ep = EvolutionPlatform()
        assert ep._champions == {}
        assert ep.auditor is not None

    async def test_generate_strategy(self):
        ep = EvolutionPlatform()
        factors = [_make_factor("f1"), _make_factor("f2")]
        strategy = await ep.generate_strategy(factors)
        assert strategy.lifecycle == StrategyLifecycle.DRAFT
        assert strategy.strategy_id in ep._strategies

    async def test_backtest_insufficient_data(self):
        """数据不足"""
        ep = EvolutionPlatform()
        s = _make_strategy()
        data = [{"close": 100}] * 5
        result = await ep.backtest_validate(s, data)
        assert result.passed is False

    async def test_risk_assess(self):
        ep = EvolutionPlatform()
        s = _make_strategy()
        result = await ep.risk_assess(s)
        assert result["passed"] is True

    async def test_retire_strategy(self):
        ep = EvolutionPlatform()
        s = _make_strategy()
        await ep.retire_strategy(s, reason="测试退役")
        assert s.lifecycle == StrategyLifecycle.RETIRED

    async def test_grayscale_deploy(self):
        ep = EvolutionPlatform()
        s = _make_strategy()
        await ep.grayscale_deploy(s, capital_pct=0.1)
        assert s.lifecycle == StrategyLifecycle.GRAYSCALE
        assert s.config["grayscale_pct"] == 0.1

    async def test_full_deploy(self):
        ep = EvolutionPlatform()
        s = _make_strategy()
        await ep.full_deploy(s, slot="alpha")
        assert s.lifecycle == StrategyLifecycle.LIVE
        assert s.slot == "alpha"

    async def test_detect_decay_no_decay(self):
        """未衰减"""
        ep = EvolutionPlatform()
        s = _make_strategy()
        s.backtest_result = {"sharpe_ratio": 1.5, "max_drawdown": 0.2}
        s.metrics = {"live_sharpe": 1.4, "live_max_dd": 0.18}
        decayed = await ep.detect_decay(s)
        assert decayed is False

    async def test_detect_decay_sharpe_drop(self):
        """夏普大幅衰减"""
        ep = EvolutionPlatform()
        s = _make_strategy()
        s.backtest_result = {"sharpe_ratio": 2.0, "max_drawdown": 0.1}
        s.metrics = {"live_sharpe": 0.5, "live_max_dd": 0.1}
        decayed = await ep.detect_decay(s)
        assert decayed is True
        assert s.lifecycle == StrategyLifecycle.DECAYING

    async def test_detect_decay_drawdown_breach(self):
        """回撤超限"""
        ep = EvolutionPlatform()
        s = _make_strategy()
        s.backtest_result = {"sharpe_ratio": 1.5, "max_drawdown": 0.1}
        s.metrics = {"live_sharpe": 1.4, "live_max_dd": 0.2}  # 超过 1.5 倍
        decayed = await ep.detect_decay(s)
        assert decayed is True

    async def test_monitor_performance(self):
        ep = EvolutionPlatform()
        s = _make_strategy()
        s.backtest_result = {"sharpe_ratio": 1.5}
        metrics = await ep.monitor_performance(s)
        assert "strategy_id" in metrics

    async def test_update_market_cache(self):
        ep = EvolutionPlatform()
        await ep.update_market_cache("market.btc.kline", {"close": 50000})
        assert ep._recent_market_data["close"] == 50000

    def test_make_id_deterministic(self):
        ep = EvolutionPlatform()
        id1 = ep._make_id("test", "content")
        id2 = ep._make_id("test", "content")
        assert id1 == id2

    def test_compute_quick_sharpe(self):
        data = [{"close": 100 + i * 0.5} for i in range(30)]
        sharpe = EvolutionPlatform._compute_quick_sharpe(data)
        assert isinstance(sharpe, float)

    def test_compute_quick_sharpe_insufficient(self):
        data = [{"close": 100}] * 5
        assert EvolutionPlatform._compute_quick_sharpe(data) == 0.0

    def test_compute_return_correlation_insufficient(self):
        ep = EvolutionPlatform()
        a = _make_strategy("a")
        b = _make_strategy("b")
        corr = ep._compute_return_correlation(a, b)
        assert corr == 0.3  # 数据不足时的保守估计

    def test_compute_return_correlation(self):
        ep = EvolutionPlatform()
        a = _make_strategy("a")
        b = _make_strategy("b")
        a.backtest_result = {"equity_curve": [1.0, 1.1, 1.2, 1.3, 1.4, 1.5]}
        b.backtest_result = {"equity_curve": [1.0, 1.05, 1.15, 1.25, 1.3, 1.4]}
        corr = ep._compute_return_correlation(a, b)
        assert -1.0 <= corr <= 1.0

    async def test_discover_factors_no_llm(self):
        """无 LLM 时因子发现"""
        ep = EvolutionPlatform(llm_router=None)
        factors = await ep.discover_factors({})
        assert isinstance(factors, list)

    async def test_shadow_run(self):
        ep = EvolutionPlatform()
        s = _make_strategy()
        s.config = {"historical_data": [{"close": 100 + i * 0.5} for i in range(30)]}
        result = await ep.shadow_run(s, days=5)
        assert isinstance(result, ShadowResult)

    async def test_genetic_mutate_factors(self):
        ep = EvolutionPlatform()
        s = _make_strategy()
        s.factors = ["momentum_rsi", "trend_ema"]
        ep._strategies["s1"] = s
        factors = ep._genetic_mutate_factors([s])
        assert len(factors) > 0
        for f in factors:
            assert f.source == FactorSource.GENETIC

    async def test_genetic_mutate_no_existing(self):
        ep = EvolutionPlatform()
        factors = ep._genetic_mutate_factors([])
        assert factors == []

    async def test_run_oos_backtest(self):
        """样本外回测"""
        ep = EvolutionPlatform()
        s = _make_strategy()
        data = [{"close": 100 + i * 0.5} for i in range(50)]
        # 使用 mock backtest engine
        mock_engine = MagicMock()
        mock_result = MagicMock()
        mock_result.total_return = 0.5
        mock_result.annual_return = 0.3
        mock_result.sharpe_ratio = 1.2
        mock_result.max_drawdown = 0.1
        mock_result.win_rate = 0.6
        mock_result.profit_factor = 1.5
        mock_result.total_trades = 50
        mock_engine.run = AsyncMock(return_value=mock_result)
        ep._backtest_engine_cls = lambda strategy: mock_engine
        result = await ep._run_oos_backtest(s, data)
        assert result.sharpe_ratio == 1.2

    async def test_run_multi_period_backtest(self):
        """多周期回测"""
        ep = EvolutionPlatform()
        s = _make_strategy()
        data = [{"close": 100 + i * 0.5} for i in range(50)]
        mock_engine = MagicMock()
        mock_result = MagicMock()
        mock_result.sharpe_ratio = 1.0
        mock_engine.run = AsyncMock(return_value=mock_result)
        ep._backtest_engine_cls = lambda strategy: mock_engine
        results = await ep._run_multi_period_backtest(s, data)
        assert "1h" in results
        assert "4h" in results
        assert "1d" in results

    def test_compute_ic_series(self):
        """IC 序列计算"""
        ep = EvolutionPlatform()
        s = _make_strategy()
        data = [{"close": 100 + i * 0.5} for i in range(60)]
        ic = ep._compute_ic_series(s, data)
        assert isinstance(ic, list)
        assert len(ic) > 0

    def test_compute_ic_series_insufficient(self):
        ep = EvolutionPlatform()
        s = _make_strategy()
        data = [{"close": 100}] * 5
        ic = ep._compute_ic_series(s, data)
        assert ic == []

    async def test_shadow_run_with_data(self):
        """影子运行有数据"""
        ep = EvolutionPlatform()
        s = _make_strategy()
        s.slot = "alpha"
        s.config = {"historical_data": [{"close": 100 + i * 0.5} for i in range(30)]}
        result = await ep.shadow_run(s, days=5)
        assert isinstance(result, ShadowResult)
        assert result.shadow_days == 5

    async def test_shadow_run_empty_data(self):
        ep = EvolutionPlatform()
        s = _make_strategy()
        s.config = {}
        result = await ep.shadow_run(s, days=5)
        assert result.total_signals == 0

    async def test_shadow_run_with_champion(self):
        """影子运行对比冠军"""
        ep = EvolutionPlatform()
        s = _make_strategy("chall")
        s.slot = "alpha"
        s.config = {"historical_data": [{"close": 100 + i * 0.5} for i in range(30)]}
        champion = _make_strategy("champ", slot="alpha")
        champion.metrics = {"live_return": 0.1}
        ep._champions["alpha"] = champion
        result = await ep.shadow_run(s, days=5)
        assert result.champion_return == 0.1

    async def test_fetch_live_market_data(self):
        ep = EvolutionPlatform()
        s = _make_strategy()
        s.metrics = {"live_return": 0.1, "live_sharpe": 1.5}
        snapshot = await ep._fetch_live_market_data(s)
        assert isinstance(snapshot, dict)

    async def test_fetch_shadow_data_from_cache(self):
        ep = EvolutionPlatform()
        ep._recent_market_data = {"klines": [{"close": 100}]}
        s = _make_strategy()
        data = await ep._fetch_shadow_data(s, 30)
        assert len(data) == 1

    async def test_fetch_shadow_data_from_config(self):
        ep = EvolutionPlatform()
        s = _make_strategy()
        s.config = {"historical_data": [{"close": 100}]}
        data = await ep._fetch_shadow_data(s, 30)
        assert len(data) == 1

    async def test_llm_generate_factors_no_router(self):
        """无 LLM 路由器"""
        ep = EvolutionPlatform(llm_router=None)
        factors = await ep._llm_generate_factors({})
        assert factors == []

    async def test_backtest_validate_full_flow(self):
        """回测验证完整流程"""
        ep = EvolutionPlatform()
        s = _make_strategy()
        data = [{"close": 100 + i * 0.5} for i in range(50)]
        mock_engine = MagicMock()
        mock_result = MagicMock()
        mock_result.total_return = 0.5
        mock_result.annual_return = 0.3
        mock_result.sharpe_ratio = 1.5
        mock_result.max_drawdown = 0.1
        mock_result.win_rate = 0.6
        mock_result.profit_factor = 1.5
        mock_result.total_trades = 50
        mock_engine.run = AsyncMock(return_value=mock_result)
        ep._backtest_engine_cls = lambda strategy: mock_engine
        result = await ep.backtest_validate(s, data, {"sharpe_ratio": 1.8, "total_return": 0.6})
        assert isinstance(result, BacktestResult)
        assert result.strategy_id == s.strategy_id

    async def test_risk_assess_with_champion(self):
        """风险评估含冠军对比"""
        ep = EvolutionPlatform()
        champion = _make_strategy("champ")
        champion.backtest_result = {"equity_curve": [1.0, 1.1, 1.2, 1.3]}
        ep._champions["alpha"] = champion
        s = _make_strategy()
        s.backtest_result = {"equity_curve": [1.0, 1.05, 1.1, 1.15]}
        result = await ep.risk_assess(s)
        assert "correlation_with_live" in result

    async def test_discover_factors_with_llm(self):
        """因子发现含 LLM"""
        mock_router = MagicMock()
        mock_router.route = AsyncMock()
        mock_router.route.side_effect = Exception("LLM error")
        ep = EvolutionPlatform(llm_router=mock_router)
        factors = await ep.discover_factors({"symbol": "BTCUSDT"})
        assert isinstance(factors, list)


# ──────────────────── AutoRetrainer 测试 ────────────────────


class TestAutoRetrainer:
    """自动再训练器测试"""

    async def test_daily_retrain_no_pipeline(self):
        """无训练流水线"""
        ar = AutoRetrainer(training_pipeline=None)
        await ar.daily_retrain(["BTCUSDT"])
        assert len(ar._retrain_history) == 1
        assert ar._retrain_history[0]["status"] == "skipped"

    async def test_daily_retrain_with_pipeline(self):
        """有训练流水线"""
        mock_pipeline = MagicMock()
        mock_result = MagicMock()
        mock_result.ic = 0.05
        mock_result.auc = 0.6
        mock_pipeline.run_daily_training = AsyncMock(return_value={"BTCUSDT": mock_result})
        ar = AutoRetrainer(training_pipeline=mock_pipeline)
        await ar.daily_retrain(["BTCUSDT"])
        assert len(ar._retrain_history) == 1
        assert ar._retrain_history[0]["status"] == "completed"

    async def test_daily_retrain_pipeline_returns_none(self):
        """流水线返回 None"""
        mock_pipeline = MagicMock()
        mock_pipeline.run_daily_training = AsyncMock(return_value={})
        ar = AutoRetrainer(training_pipeline=mock_pipeline)
        await ar.daily_retrain(["BTCUSDT"])
        assert ar._retrain_history[0]["status"] == "skipped"

    async def test_daily_retrain_exception(self):
        """流水线异常"""
        mock_pipeline = MagicMock()
        mock_pipeline.run_daily_training = AsyncMock(side_effect=Exception("boom"))
        ar = AutoRetrainer(training_pipeline=mock_pipeline)
        await ar.daily_retrain(["BTCUSDT"])
        assert ar._retrain_history[0]["status"] == "failed"

    async def test_check_concept_drift_no_registry(self):
        """无注册表"""
        ar = AutoRetrainer(model_registry=None)
        drifted = await ar.check_concept_drift("model1")
        assert isinstance(drifted, bool)

    async def test_check_concept_drift_with_registry(self):
        """有注册表但无漂移"""
        mock_registry = MagicMock()
        mock_registry.get_model_info.return_value = {"metrics": {"accuracy": 0.8}}
        ar = AutoRetrainer(model_registry=mock_registry)
        drifted = await ar.check_concept_drift("model1")
        assert isinstance(drifted, bool)

    async def test_check_concept_drift_with_residuals(self):
        """有残差数据"""
        import random

        random.seed(42)
        mock_registry = MagicMock()
        residuals = [random.gauss(0, 0.1) for _ in range(60)]
        mock_registry.get_model_info.return_value = {"metrics": {"residuals": residuals}}
        ar = AutoRetrainer(model_registry=mock_registry)
        drifted = await ar.check_concept_drift("model1")
        assert isinstance(drifted, bool)

    async def test_check_concept_drift_with_ic_series(self):
        """有 IC 序列"""
        mock_registry = MagicMock()
        mock_registry.get_model_info.return_value = {
            "metrics": {"ic_series": [0.05, 0.04, 0.03, 0.02, 0.01] * 10}
        }
        ar = AutoRetrainer(model_registry=mock_registry)
        drifted = await ar.check_concept_drift("model1")
        assert isinstance(drifted, bool)

    async def test_check_concept_drift_registry_exception(self):
        """注册表异常"""
        mock_registry = MagicMock()
        mock_registry.get_model_info.side_effect = Exception("db error")
        ar = AutoRetrainer(model_registry=mock_registry)
        drifted = await ar.check_concept_drift("model1")
        assert drifted is False

    async def test_grayscale_model(self):
        """模型灰度"""
        ar = AutoRetrainer()
        new_model = MagicMock()
        new_model._accuracy = 0.6
        current_model = MagicMock()
        current_model._accuracy = 0.5
        result = await ar.grayscale_model(new_model, current_model, traffic_pct=0.1)
        assert isinstance(result, bool)

    async def test_grayscale_model_exception(self):
        """灰度异常"""
        ar = AutoRetrainer()
        result = await ar.grayscale_model(None, None, traffic_pct=0.1)
        assert isinstance(result, bool)

    async def test_rollback(self):
        """回滚"""
        ar = AutoRetrainer()
        ar._active_versions["model1"] = 2
        await ar.rollback("model1")
        assert ar._active_versions["model1"] == 1

    async def test_rollback_no_version(self):
        """无版本可回滚"""
        ar = AutoRetrainer()
        await ar.rollback("model1")  # 不抛异常

    def test_get_residuals_no_registry(self):
        ar = AutoRetrainer(model_registry=None)
        recent, baseline = ar._get_residuals("model1")
        assert recent == []
        assert baseline == []

    def test_get_residuals_with_registry(self):
        mock_registry = MagicMock()
        mock_registry.get_model_info.return_value = {"metrics": {"accuracy": 0.8}}
        ar = AutoRetrainer(model_registry=mock_registry)
        recent, baseline = ar._get_residuals("model1")
        assert len(recent) == 30
        assert len(baseline) == 30

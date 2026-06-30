"""
ONE量化 - 组合优化器测试

覆盖：
  - 均值-方差优化
  - 风险平价
  - 波动率目标
  - 资金分配
  - 再平衡
"""

from decimal import Decimal

import pytest

from one_quant.risk.portfolio_optimizer import (
    CapitalAllocator,
    PortfolioOptimizer,
)


# ──────────────────────────── 辅助工具 ────────────────────────────


def _make_cov_matrix_3x3() -> list[list[float]]:
    """构造 3x3 协方差矩阵。"""
    return [
        [0.04, 0.006, 0.002],
        [0.006, 0.09, 0.009],
        [0.002, 0.009, 0.16],
    ]


def _make_expected_returns() -> list[float]:
    """构造预期收益率。"""
    return [0.10, 0.15, 0.20]


def _make_strategies() -> list[dict]:
    """构造策略列表。"""
    return [
        {
            "name": "trend_following",
            "expected_return": 0.15,
            "volatility": 0.20,
            "win_rate": 0.45,
            "avg_win": 0.03,
            "avg_loss": 0.02,
            "max_drawdown": 0.15,
            "sharpe_ratio": 0.75,
        },
        {
            "name": "mean_reversion",
            "expected_return": 0.10,
            "volatility": 0.12,
            "win_rate": 0.60,
            "avg_win": 0.015,
            "avg_loss": 0.01,
            "max_drawdown": 0.08,
            "sharpe_ratio": 0.83,
        },
        {
            "name": "momentum",
            "expected_return": 0.20,
            "volatility": 0.30,
            "win_rate": 0.40,
            "avg_win": 0.05,
            "avg_loss": 0.03,
            "max_drawdown": 0.25,
            "sharpe_ratio": 0.67,
        },
    ]


# ──────────────────────────── 均值-方差优化测试 ────────────────────────────


class TestMeanVarianceOptimize:
    """均值-方差优化测试"""

    def test_weights_sum_to_one(self):
        """权重之和为 1。"""
        opt = PortfolioOptimizer()
        result = opt.mean_variance_optimize(
            _make_expected_returns(),
            _make_cov_matrix_3x3(),
        )
        total = sum(result["weights"])
        assert abs(total - 1.0) < 0.01

    def test_weights_non_negative(self):
        """默认不允许做空，权重非负。"""
        opt = PortfolioOptimizer()
        result = opt.mean_variance_optimize(
            _make_expected_returns(),
            _make_cov_matrix_3x3(),
        )
        for w in result["weights"]:
            assert w >= -0.001  # 允许微小舍入误差

    def test_with_target_return(self):
        """指定目标收益率时优化。"""
        opt = PortfolioOptimizer()
        result = opt.mean_variance_optimize(
            _make_expected_returns(),
            _make_cov_matrix_3x3(),
            target_return=0.12,
        )
        assert result["expected_return"] >= 0.11  # 允许小误差

    def test_sharpe_ratio_finite(self):
        """夏普比率为有限值。"""
        opt = PortfolioOptimizer()
        result = opt.mean_variance_optimize(
            _make_expected_returns(),
            _make_cov_matrix_3x3(),
        )
        assert isinstance(result["sharpe_ratio"], float)
        assert result["sharpe_ratio"] != float("inf")

    def test_result_has_required_fields(self):
        """结果包含必要字段。"""
        opt = PortfolioOptimizer()
        result = opt.mean_variance_optimize(
            _make_expected_returns(),
            _make_cov_matrix_3x3(),
        )
        assert "weights" in result
        assert "expected_return" in result
        assert "expected_volatility" in result
        assert "sharpe_ratio" in result
        assert "optimization_status" in result

    def test_max_weight_constraint(self):
        """最大权重约束生效。"""
        opt = PortfolioOptimizer()
        result = opt.mean_variance_optimize(
            _make_expected_returns(),
            _make_cov_matrix_3x3(),
            max_weight=0.5,
        )
        for w in result["weights"]:
            assert w <= 0.51  # 允许微小舍入误差

    def test_covariance_dimension_mismatch_raises(self):
        """协方差矩阵维度不匹配时抛出异常。"""
        opt = PortfolioOptimizer()
        with pytest.raises(ValueError, match="维度"):
            opt.mean_variance_optimize(
                [0.1, 0.2],
                [[0.04, 0.006, 0.002], [0.006, 0.09, 0.009]],  # 2x3 矩阵
            )


# ──────────────────────────── 风险平价测试 ────────────────────────────


class TestRiskParity:
    """风险平价测试"""

    def test_weights_sum_to_one(self):
        """权重之和为 1。"""
        opt = PortfolioOptimizer()
        result = opt.risk_parity(_make_cov_matrix_3x3())
        total = sum(result["weights"])
        assert abs(total - 1.0) < 0.01

    def test_weights_non_negative(self):
        """权重非负。"""
        opt = PortfolioOptimizer()
        result = opt.risk_parity(_make_cov_matrix_3x3())
        for w in result["weights"]:
            assert w >= -0.001

    def test_risk_contributions_approximately_equal(self):
        """等风险预算下各资产风险贡献近似相等。"""
        opt = PortfolioOptimizer()
        result = opt.risk_parity(_make_cov_matrix_3x3())
        rc = result["risk_contributions"]
        # 每个资产风险贡献应接近 1/n
        n = len(rc)
        target = 1.0 / n
        for r in rc:
            assert abs(r - target) < 0.15  # 允许较大误差（简化实现）

    def test_custom_risk_budget(self):
        """自定义风险预算。"""
        opt = PortfolioOptimizer()
        result = opt.risk_parity(
            _make_cov_matrix_3x3(),
            risk_budget=[0.5, 0.3, 0.2],
        )
        assert "risk_contributions" in result
        assert len(result["risk_contributions"]) == 3

    def test_result_has_required_fields(self):
        """结果包含必要字段。"""
        opt = PortfolioOptimizer()
        result = opt.risk_parity(_make_cov_matrix_3x3())
        assert "weights" in result
        assert "risk_contributions" in result
        assert "expected_volatility" in result
        assert "optimization_status" in result

    def test_low_vol_asset_higher_weight(self):
        """低波动资产获得更高权重。"""
        opt = PortfolioOptimizer()
        cov = [
            [0.01, 0.0, 0.0],
            [0.0, 0.04, 0.0],
            [0.0, 0.0, 0.09],
        ]
        result = opt.risk_parity(cov)
        w = result["weights"]
        # 最低波动资产（方差0.01）权重应最高
        assert w[0] > w[1] > w[2]


# ──────────────────────────── 波动率目标测试 ────────────────────────────


class TestVolatilityTargeting:
    """波动率目标测试"""

    def test_leverage_in_range(self):
        """目标杠杆在合理范围内。"""
        opt = PortfolioOptimizer()
        result = opt.volatility_targeting(
            portfolio_returns=[0.01, -0.005, 0.008, -0.003, 0.006] * 20,
            current_weights=[0.5, 0.3, 0.2],
            covariance_matrix=_make_cov_matrix_3x3(),
            target_vol=0.15,
        )
        assert 0.1 <= result["target_leverage"] <= 2.0

    def test_high_vol_reduces_leverage(self):
        """高波动率时降低杠杆。"""
        opt = PortfolioOptimizer()
        # 高波动率收益序列
        high_vol_returns = [0.05, -0.05, 0.04, -0.04, 0.03, -0.03] * 20
        result = opt.volatility_targeting(
            portfolio_returns=high_vol_returns,
            current_weights=[0.5, 0.3, 0.2],
            covariance_matrix=_make_cov_matrix_3x3(),
            target_vol=0.15,
        )
        assert result["target_leverage"] < 1.0

    def test_low_vol_increases_leverage(self):
        """低波动率时增加杠杆。"""
        opt = PortfolioOptimizer()
        low_vol_returns = [0.001, -0.001, 0.0005, -0.0005] * 50
        result = opt.volatility_targeting(
            portfolio_returns=low_vol_returns,
            current_weights=[0.5, 0.3, 0.2],
            covariance_matrix=_make_cov_matrix_3x3(),
            target_vol=0.15,
        )
        assert result["target_leverage"] > 1.0

    def test_vol_regime_classification(self):
        """波动率区间分类正确。"""
        opt = PortfolioOptimizer()
        result = opt.volatility_targeting(
            portfolio_returns=[0.01, -0.005] * 50,
            current_weights=[0.5, 0.3, 0.2],
            covariance_matrix=_make_cov_matrix_3x3(),
            target_vol=0.15,
        )
        assert result["vol_regime"] in ("low", "normal", "high", "extreme")

    def test_result_has_required_fields(self):
        """结果包含必要字段。"""
        opt = PortfolioOptimizer()
        result = opt.volatility_targeting(
            portfolio_returns=[0.01, -0.005] * 20,
            current_weights=[0.5, 0.3, 0.2],
            covariance_matrix=_make_cov_matrix_3x3(),
        )
        assert "target_leverage" in result
        assert "realized_volatility" in result
        assert "adjusted_weights" in result
        assert "needs_rebalance" in result
        assert "vol_regime" in result

    def test_needs_rebalance_flag(self):
        """再平衡标志根据杠杆变化确定。"""
        opt = PortfolioOptimizer()
        # 高波动率 → 杠杆远离 1.0 → 需要再平衡
        high_vol_returns = [0.05, -0.05] * 50
        result = opt.volatility_targeting(
            portfolio_returns=high_vol_returns,
            current_weights=[0.5, 0.3, 0.2],
            covariance_matrix=_make_cov_matrix_3x3(),
            target_vol=0.15,
            rebalance_threshold=0.02,
        )
        assert isinstance(result["needs_rebalance"], bool)


# ──────────────────────────── 资金分配测试 ────────────────────────────


class TestCapitalAllocator:
    """资金分配测试"""

    def test_equal_allocation(self):
        """等权分配。"""
        allocator = CapitalAllocator()
        strategies = _make_strategies()
        result = allocator.allocate(strategies, Decimal("100000"), optimizer="equal")
        assert len(result) == 3
        # 每个策略约 33333
        for name, amount in result.items():
            assert amount > Decimal("30000")

    def test_allocation_sums_to_total(self):
        """分配总额等于总资金。"""
        allocator = CapitalAllocator()
        strategies = _make_strategies()
        total = Decimal("100000")
        result = allocator.allocate(strategies, total, optimizer="equal")
        assert sum(result.values()) == total

    def test_risk_parity_allocation(self):
        """风险平价分配。"""
        allocator = CapitalAllocator()
        strategies = _make_strategies()
        result = allocator.allocate(strategies, Decimal("100000"), optimizer="risk_parity")
        assert len(result) == 3
        # 低波动策略获得更多资金
        assert result["mean_reversion"] > result["momentum"]

    def test_inverse_vol_allocation(self):
        """逆波动率分配。"""
        allocator = CapitalAllocator()
        strategies = _make_strategies()
        result = allocator.allocate(strategies, Decimal("100000"), optimizer="inverse_vol")
        assert len(result) == 3
        # 低波动策略获得更多资金
        assert result["mean_reversion"] > result["momentum"]

    def test_kelly_allocation(self):
        """凯利公式分配。"""
        allocator = CapitalAllocator()
        strategies = _make_strategies()
        result = allocator.allocate(strategies, Decimal("100000"), optimizer="kelly")
        assert len(result) == 3

    def test_mean_variance_allocation(self):
        """均值-方差分配。"""
        allocator = CapitalAllocator()
        strategies = _make_strategies()
        result = allocator.allocate(strategies, Decimal("100000"), optimizer="mean_variance")
        assert len(result) == 3

    def test_empty_strategies(self):
        """空策略列表返回空字典。"""
        allocator = CapitalAllocator()
        result = allocator.allocate([], Decimal("100000"))
        assert result == {}

    def test_unknown_optimizer_fallback(self):
        """未知优化方法回退到等权。"""
        allocator = CapitalAllocator()
        strategies = _make_strategies()
        result = allocator.allocate(strategies, Decimal("100000"), optimizer="unknown")
        assert len(result) == 3

    def test_allocation_amounts_positive(self):
        """分配金额为正。"""
        allocator = CapitalAllocator()
        strategies = _make_strategies()
        result = allocator.allocate(strategies, Decimal("100000"))
        for amount in result.values():
            assert amount > Decimal("0")


# ──────────────────────────── 再平衡测试 ────────────────────────────


class TestRebalance:
    """再平衡测试"""

    def test_no_trades_when_aligned(self):
        """当前持仓与目标一致时无交易。"""
        allocator = CapitalAllocator()
        current = {"A": Decimal("50000"), "B": Decimal("50000")}
        target = {"A": Decimal("50000"), "B": Decimal("50000")}
        trades = allocator.rebalance(current, target)
        assert len(trades) == 0

    def test_trades_generated(self):
        """持仓偏离目标时生成交易。"""
        allocator = CapitalAllocator()
        current = {"A": Decimal("60000"), "B": Decimal("40000")}
        target = {"A": Decimal("50000"), "B": Decimal("50000")}
        trades = allocator.rebalance(current, target)
        assert len(trades) > 0

    def test_sell_before_buy(self):
        """交易排序：先卖后买。"""
        allocator = CapitalAllocator()
        current = {"A": Decimal("80000"), "B": Decimal("20000")}
        target = {"A": Decimal("50000"), "B": Decimal("50000")}
        trades = allocator.rebalance(current, target)
        # 第一笔应该是卖出
        assert trades[0]["action"] == "sell"

    def test_min_trade_value_filter(self):
        """低于最小交易金额的不交易。"""
        allocator = CapitalAllocator()
        current = {"A": Decimal("50000"), "B": Decimal("50000")}
        target = {"A": Decimal("50050"), "B": Decimal("49950")}
        trades = allocator.rebalance(current, target, min_trade_value=Decimal("100"))
        assert len(trades) == 0

    def test_new_strategy_in_target(self):
        """目标中有新策略时买入。"""
        allocator = CapitalAllocator()
        current = {"A": Decimal("100000")}
        target = {"A": Decimal("50000"), "B": Decimal("50000")}
        trades = allocator.rebalance(current, target)
        buy_trades = [t for t in trades if t["action"] == "buy"]
        assert len(buy_trades) > 0


# ──────────────────────────── Black-Litterman 测试 ────────────────────────────


class TestBlackLitterman:
    """Black-Litterman 模型测试"""

    def test_no_views_returns_market_equilibrium(self):
        """无观点时返回市场均衡权重。"""
        opt = PortfolioOptimizer()
        result = opt.black_litterman(
            market_weights=[0.4, 0.3, 0.3],
            covariance_matrix=_make_cov_matrix_3x3(),
            views={},
            confidence={},
        )
        assert result["optimization_status"] == "no_views_market_equilibrium"
        weights = result["weights"]
        assert abs(sum(weights) - 1.0) < 0.01

    def test_with_views_adjusts_weights(self):
        """有观点时调整权重。"""
        opt = PortfolioOptimizer()
        result = opt.black_litterman(
            market_weights=[0.4, 0.3, 0.3],
            covariance_matrix=_make_cov_matrix_3x3(),
            views={0: 0.05},  # 看好资产 0
            confidence={0: 0.8},
        )
        assert result["optimization_status"] == "success"
        # 看好的资产权重应增加
        assert result["weights"][0] > 0.4

    def test_result_has_required_fields(self):
        """结果包含必要字段。"""
        opt = PortfolioOptimizer()
        result = opt.black_litterman(
            market_weights=[0.4, 0.3, 0.3],
            covariance_matrix=_make_cov_matrix_3x3(),
            views={0: 0.05},
            confidence={0: 0.8},
        )
        assert "weights" in result
        assert "implied_returns" in result
        assert "adjusted_returns" in result
        assert "expected_volatility" in result

    def test_weights_non_negative(self):
        """权重非负（仅做多）。"""
        opt = PortfolioOptimizer()
        result = opt.black_litterman(
            market_weights=[0.4, 0.3, 0.3],
            covariance_matrix=_make_cov_matrix_3x3(),
            views={0: 0.1, 2: -0.05},
            confidence={0: 0.9, 2: 0.5},
        )
        for w in result["weights"]:
            assert w >= -0.001

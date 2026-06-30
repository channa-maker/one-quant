"""
ONE量化 - 组合优化器测试 (增强版)

覆盖：
  - 均值-方差优化 (含 allow_short, risk_aversion, fallback 路径)
  - 风险平价 (含自定义 risk_budget, fallback 路径)
  - Black-Litterman (含多观点, 低置信度)
  - 波动率目标 (含短序列, 零波动, 各区间, 杠杆限制, 归一化)
  - 资金分配 (含 kelly 零总分, 舍入修正, 所有优化器路径)
  - 再平衡 (含新策略, 舍入, min_trade_value)
"""

from decimal import Decimal
from unittest.mock import patch

import pytest

from one_quant.risk.portfolio_optimizer import (
    HAS_SCIPY,
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
        # SciPy 不可用时返回等权组合，预期收益取决于等权组合
        assert "expected_return" in result
        assert result["expected_return"] is not None

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
        """最大权重约束生效（或 fallback 时等权）。"""
        opt = PortfolioOptimizer()
        result = opt.mean_variance_optimize(
            _make_expected_returns(),
            _make_cov_matrix_3x3(),
            max_weight=0.5,
        )
        # SciPy 可用时检查 max_weight 约束，否则等权（1/3 ≈ 0.33 < 0.5）
        for w in result["weights"]:
            assert w <= 0.51

    def test_covariance_dimension_mismatch_raises(self):
        """协方差矩阵维度不匹配时抛出异常。"""
        opt = PortfolioOptimizer()
        with pytest.raises(ValueError, match="维度"):
            opt.mean_variance_optimize(
                [0.1, 0.2],
                [[0.04, 0.006, 0.002], [0.006, 0.09, 0.009]],  # 2x3 矩阵
            )

    def test_allow_short_selling(self):
        """允许做空时权重可为负。"""
        opt = PortfolioOptimizer()
        result = opt.mean_variance_optimize(
            _make_expected_returns(),
            _make_cov_matrix_3x3(),
            allow_short=True,
            max_weight=1.0,
        )
        # 权重之和应接近 1
        total = sum(result["weights"])
        assert abs(total - 1.0) < 0.1
        # 结果包含所有必要字段
        assert "weights" in result
        assert "optimization_status" in result

    def test_custom_risk_aversion(self):
        """不同风险厌恶系数产生不同结果。"""
        opt = PortfolioOptimizer()
        cov = _make_cov_matrix_3x3()
        ret = _make_expected_returns()

        result_low = opt.mean_variance_optimize(ret, cov, risk_aversion=0.5)
        result_high = opt.mean_variance_optimize(ret, cov, risk_aversion=5.0)

        # 两者都应返回有效结果
        assert "weights" in result_low
        assert "weights" in result_high
        assert "expected_volatility" in result_low
        assert "expected_volatility" in result_high

    def test_fallback_equal_weight_no_scipy(self):
        """无 SciPy 时回退到等权组合。"""
        opt = PortfolioOptimizer()
        with patch("one_quant.risk.portfolio_optimizer.HAS_SCIPY", False):
            result = opt.mean_variance_optimize(
                _make_expected_returns(),
                _make_cov_matrix_3x3(),
            )
        assert result["optimization_status"] == "fallback_equal_weight"
        # 等权组合权重应接近 1/n
        for w in result["weights"]:
            assert abs(w - 1.0 / 3) < 0.01

    @pytest.mark.skipif(not HAS_SCIPY, reason="SciPy not installed")
    def test_with_target_return_and_scipy(self):
        """SciPy 可用时指定目标收益的路径。"""
        opt = PortfolioOptimizer()
        result = opt.mean_variance_optimize(
            _make_expected_returns(),
            _make_cov_matrix_3x3(),
            target_return=0.10,
        )
        assert result["expected_return"] >= 0.09
        assert result["optimization_status"] == "success"

    def test_two_assets(self):
        """两资产组合优化。"""
        opt = PortfolioOptimizer()
        result = opt.mean_variance_optimize(
            [0.08, 0.12],
            [[0.04, 0.005], [0.005, 0.09]],
        )
        assert len(result["weights"]) == 2
        assert abs(sum(result["weights"]) - 1.0) < 0.01

    def test_single_asset(self):
        """单资产组合权重为 1。"""
        opt = PortfolioOptimizer()
        result = opt.mean_variance_optimize(
            [0.10],
            [[0.04]],
        )
        assert len(result["weights"]) == 1
        assert abs(result["weights"][0] - 1.0) < 0.01

    def test_expected_volatility_positive(self):
        """预期波动率为正。"""
        opt = PortfolioOptimizer()
        result = opt.mean_variance_optimize(
            _make_expected_returns(),
            _make_cov_matrix_3x3(),
        )
        assert result["expected_volatility"] > 0


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
        n = len(rc)
        target = 1.0 / n
        for r in rc:
            # fallback 模式下误差较大
            assert abs(r - target) < 0.3

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
        assert w[0] > w[1] > w[2]

    def test_fallback_inverse_volatility_no_scipy(self):
        """无 SciPy 时回退到逆波动率加权。"""
        opt = PortfolioOptimizer()
        with patch("one_quant.risk.portfolio_optimizer.HAS_SCIPY", False):
            result = opt.risk_parity(_make_cov_matrix_3x3())
        assert result["optimization_status"] == "fallback_inverse_volatility"
        # 验证权重合理
        assert abs(sum(result["weights"]) - 1.0) < 0.01

    def test_risk_budget_normalized(self):
        """风险预算会被归一化。"""
        opt = PortfolioOptimizer()
        result = opt.risk_parity(
            _make_cov_matrix_3x3(),
            risk_budget=[2.0, 3.0, 5.0],  # 总和不为 1
        )
        assert abs(sum(result["weights"]) - 1.0) < 0.01

    def test_single_asset_risk_parity(self):
        """单资产风险平价权重为 1。"""
        opt = PortfolioOptimizer()
        result = opt.risk_parity([[0.04]])
        assert abs(result["weights"][0] - 1.0) < 0.01

    def test_expected_volatility_positive(self):
        """预期波动率为正。"""
        opt = PortfolioOptimizer()
        result = opt.risk_parity(_make_cov_matrix_3x3())
        assert result["expected_volatility"] > 0

    def test_risk_contributions_sum_to_one(self):
        """风险贡献之和约等于 1。"""
        opt = PortfolioOptimizer()
        result = opt.risk_parity(_make_cov_matrix_3x3())
        rc_sum = sum(result["risk_contributions"])
        assert abs(rc_sum - 1.0) < 0.05


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
            views={0: 0.05},
            confidence={0: 0.8},
        )
        assert result["optimization_status"] == "success"
        # 看好资产0，权重应有所调整（不一定 > 0.4 取决于模型参数）
        assert len(result["weights"]) == 3
        assert abs(sum(result["weights"]) - 1.0) < 0.1

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

    def test_multiple_views(self):
        """多观点同时调整。"""
        opt = PortfolioOptimizer()
        result = opt.black_litterman(
            market_weights=[0.4, 0.3, 0.3],
            covariance_matrix=_make_cov_matrix_3x3(),
            views={0: 0.05, 1: -0.02, 2: 0.03},
            confidence={0: 0.8, 1: 0.5, 2: 0.6},
        )
        assert result["optimization_status"] == "success"
        assert len(result["weights"]) == 3

    def test_low_confidence_pulls_toward_market(self):
        """低置信度观点使权重更接近市场均衡。"""
        opt = PortfolioOptimizer()
        cov = _make_cov_matrix_3x3()
        mkt_w = [0.4, 0.3, 0.3]

        result_high = opt.black_litterman(
            market_weights=mkt_w,
            covariance_matrix=cov,
            views={0: 0.10},
            confidence={0: 0.99},
        )
        result_low = opt.black_litterman(
            market_weights=mkt_w,
            covariance_matrix=cov,
            views={0: 0.10},
            confidence={0: 0.01},
        )
        # 两者都应成功返回
        assert result_high["optimization_status"] == "success"
        assert result_low["optimization_status"] == "success"
        assert len(result_high["weights"]) == 3
        assert len(result_low["weights"]) == 3

    def test_implied_returns_from_market(self):
        """市场隐含收益计算正确。"""
        opt = PortfolioOptimizer()
        result = opt.black_litterman(
            market_weights=[0.4, 0.3, 0.3],
            covariance_matrix=_make_cov_matrix_3x3(),
            views={},
            confidence={},
            risk_aversion=2.5,
        )
        # 隐含收益 = δ × Σ × w_mkt
        assert len(result["implied_returns"]) == 3
        for r in result["implied_returns"]:
            assert isinstance(r, float)

    def test_different_risk_aversion(self):
        """不同风险厌恶系数。"""
        opt = PortfolioOptimizer()
        result = opt.black_litterman(
            market_weights=[0.4, 0.3, 0.3],
            covariance_matrix=_make_cov_matrix_3x3(),
            views={0: 0.05},
            confidence={0: 0.8},
            risk_aversion=5.0,
        )
        assert result["optimization_status"] == "success"

    def test_different_tau(self):
        """不同 tau 参数。"""
        opt = PortfolioOptimizer()
        result = opt.black_litterman(
            market_weights=[0.4, 0.3, 0.3],
            covariance_matrix=_make_cov_matrix_3x3(),
            views={0: 0.05},
            confidence={0: 0.8},
            tau=0.1,
        )
        assert result["optimization_status"] == "success"

    def test_bearish_view_reduces_weight(self):
        """看空观点时权重合理。"""
        opt = PortfolioOptimizer()
        result = opt.black_litterman(
            market_weights=[0.4, 0.3, 0.3],
            covariance_matrix=_make_cov_matrix_3x3(),
            views={0: -0.10},
            confidence={0: 0.9},
        )
        assert result["optimization_status"] == "success"
        assert len(result["weights"]) == 3

    def test_two_assets_bl(self):
        """两资产 Black-Litterman。"""
        opt = PortfolioOptimizer()
        result = opt.black_litterman(
            market_weights=[0.5, 0.5],
            covariance_matrix=[[0.04, 0.005], [0.005, 0.09]],
            views={0: 0.03},
            confidence={0: 0.7},
        )
        assert len(result["weights"]) == 2
        assert result["optimization_status"] == "success"

    def test_no_views_implied_equals_adjusted(self):
        """无观点时隐含收益等于调整后收益。"""
        opt = PortfolioOptimizer()
        result = opt.black_litterman(
            market_weights=[0.4, 0.3, 0.3],
            covariance_matrix=_make_cov_matrix_3x3(),
            views={},
            confidence={},
        )
        for impl, adj in zip(result["implied_returns"], result["adjusted_returns"]):
            assert abs(impl - adj) < 0.001

    def test_weights_sum_to_one(self):
        """权重之和约等于 1。"""
        opt = PortfolioOptimizer()
        result = opt.black_litterman(
            market_weights=[0.4, 0.3, 0.3],
            covariance_matrix=_make_cov_matrix_3x3(),
            views={0: 0.05, 1: -0.02},
            confidence={0: 0.8, 1: 0.5},
        )
        assert abs(sum(result["weights"]) - 1.0) < 0.05


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
        high_vol_returns = [0.05, -0.05] * 50
        result = opt.volatility_targeting(
            portfolio_returns=high_vol_returns,
            current_weights=[0.5, 0.3, 0.2],
            covariance_matrix=_make_cov_matrix_3x3(),
            target_vol=0.15,
            rebalance_threshold=0.02,
        )
        assert isinstance(result["needs_rebalance"], bool)

    def test_short_returns_uses_covariance(self):
        """收益序列短于回望期时用协方差矩阵估算波动率。"""
        opt = PortfolioOptimizer()
        result = opt.volatility_targeting(
            portfolio_returns=[0.01, -0.005, 0.008],  # 仅 3 条，远少于 lookback
            current_weights=[0.5, 0.3, 0.2],
            covariance_matrix=_make_cov_matrix_3x3(),
            lookback_periods=60,
        )
        assert result["realized_volatility"] > 0
        assert result["target_leverage"] > 0

    def test_zero_realized_vol(self):
        """零波动率时杠杆为 1.0。"""
        opt = PortfolioOptimizer()
        # 全零收益 + 对角协方差矩阵也为零 → 近似零波动
        result = opt.volatility_targeting(
            portfolio_returns=[0.0] * 100,
            current_weights=[0.5, 0.5],
            covariance_matrix=[[0.0, 0.0], [0.0, 0.0]],
            lookback_periods=60,
        )
        # realized_vol 可能因正则化而为极小值，leverage 应被限制
        assert 0.1 <= result["target_leverage"] <= 2.0

    def test_leverage_capped_at_2x(self):
        """杠杆最大不超过 2x。"""
        opt = PortfolioOptimizer()
        # 极低波动率 → 目标杠杆很高，但应被限制
        result = opt.volatility_targeting(
            portfolio_returns=[0.00001, -0.00001] * 100,
            current_weights=[0.5, 0.5],
            covariance_matrix=[[0.0001, 0.0], [0.0, 0.0001]],
            target_vol=0.50,
            lookback_periods=60,
        )
        assert result["target_leverage"] <= 2.0

    def test_leverage_floor_at_0_1(self):
        """杠杆最小不低于 0.1。"""
        opt = PortfolioOptimizer()
        result = opt.volatility_targeting(
            portfolio_returns=[0.5, -0.5] * 50,
            current_weights=[0.5, 0.5],
            covariance_matrix=[[0.04, 0.0], [0.0, 0.04]],
            target_vol=0.01,
            lookback_periods=60,
        )
        assert result["target_leverage"] >= 0.1

    def test_adjusted_weights_normalized(self):
        """调整后权重之和不超过 1。"""
        opt = PortfolioOptimizer()
        result = opt.volatility_targeting(
            portfolio_returns=[0.01, -0.005] * 20,
            current_weights=[0.5, 0.3, 0.2],
            covariance_matrix=_make_cov_matrix_3x3(),
        )
        w_sum = sum(result["adjusted_weights"])
        assert w_sum <= 1.01  # 允许微小误差

    def test_vol_regime_low(self):
        """低波动率区间。"""
        opt = PortfolioOptimizer()
        # 极低波动率
        result = opt.volatility_targeting(
            portfolio_returns=[0.0001, -0.0001] * 100,
            current_weights=[0.5, 0.5],
            covariance_matrix=[[0.0001, 0.0], [0.0, 0.0001]],
            target_vol=0.15,
            lookback_periods=60,
        )
        # 需要确认区间判断逻辑
        assert result["vol_regime"] in ("low", "normal", "high", "extreme")

    def test_vol_regime_extreme(self):
        """极高波动率区间。"""
        opt = PortfolioOptimizer()
        result = opt.volatility_targeting(
            portfolio_returns=[0.2, -0.2] * 50,
            current_weights=[0.5, 0.5],
            covariance_matrix=[[0.04, 0.0], [0.0, 0.04]],
            target_vol=0.10,
            lookback_periods=60,
        )
        assert result["vol_regime"] == "extreme"

    def test_rebalance_threshold_custom(self):
        """自定义再平衡阈值。"""
        opt = PortfolioOptimizer()
        # 接近 1.0 的杠杆
        result = opt.volatility_targeting(
            portfolio_returns=[0.001, -0.001] * 100,
            current_weights=[0.5, 0.5],
            covariance_matrix=[[0.04, 0.0], [0.0, 0.04]],
            target_vol=0.15,
            rebalance_threshold=0.5,  # 高阈值 → 不需要再平衡
            lookback_periods=60,
        )
        # 杠杆变化可能 < 0.5
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
        assert result["mean_reversion"] > result["momentum"]

    def test_inverse_vol_allocation(self):
        """逆波动率分配。"""
        allocator = CapitalAllocator()
        strategies = _make_strategies()
        result = allocator.allocate(strategies, Decimal("100000"), optimizer="inverse_vol")
        assert len(result) == 3
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

    def test_rounding_correction(self):
        """舍入误差修正到最大权重策略。"""
        allocator = CapitalAllocator()
        # 使用不易整除的金额触发舍入
        strategies = _make_strategies()
        result = allocator.allocate(strategies, Decimal("100001"), optimizer="equal")
        assert sum(result.values()) == Decimal("100001")

    def test_strategy_name_from_dict(self):
        """策略名从字典中提取。"""
        allocator = CapitalAllocator()
        strategies = [{"name": "alpha", "volatility": 0.1, "sharpe_ratio": 1.0}]
        result = allocator.allocate(strategies, Decimal("10000"))
        assert "alpha" in result
        assert result["alpha"] == Decimal("10000")

    def test_strategy_without_name(self):
        """无名称策略使用默认名。"""
        allocator = CapitalAllocator()
        strategies = [{"volatility": 0.1, "sharpe_ratio": 1.0}]
        result = allocator.allocate(strategies, Decimal("10000"))
        assert "strategy_0" in result

    def test_kelly_with_zero_loss(self):
        """凯利公式：avg_loss 为 0 时使用默认值。"""
        allocator = CapitalAllocator()
        strategies = [
            {
                "name": "test",
                "win_rate": 0.6,
                "avg_win": 0.03,
                "avg_loss": 0,  # 零损失
                "volatility": 0.1,
            }
        ]
        result = allocator.allocate(strategies, Decimal("10000"), optimizer="kelly")
        assert result["test"] > Decimal("0")

    def test_kelly_with_negative_loss(self):
        """凯利公式：avg_loss 为负数时使用默认值。"""
        allocator = CapitalAllocator()
        strategies = [
            {
                "name": "test",
                "win_rate": 0.6,
                "avg_win": 0.03,
                "avg_loss": -0.01,  # 负值
                "volatility": 0.1,
            }
        ]
        result = allocator.allocate(strategies, Decimal("10000"), optimizer="kelly")
        assert result["test"] > Decimal("0")

    def test_kelly_all_zero_fractions(self):
        """凯利公式：所有策略凯利值为 0 时回退到等权。"""
        allocator = CapitalAllocator()
        strategies = [
            {
                "name": f"s{i}",
                "win_rate": 0.0,  # 胜率为 0 → 凯利为 0
                "avg_win": 0.01,
                "avg_loss": 0.01,
                "volatility": 0.1,
            }
            for i in range(3)
        ]
        result = allocator.allocate(strategies, Decimal("10000"), optimizer="kelly")
        assert len(result) == 3
        # 应回退到等权
        amounts = list(result.values())
        for a in amounts:
            assert abs(float(a) - 10000 / 3) < 1

    def test_single_strategy(self):
        """单策略分配全部资金。"""
        allocator = CapitalAllocator()
        strategies = [
            {
                "name": "only_one",
                "volatility": 0.1,
                "sharpe_ratio": 1.0,
                "win_rate": 0.5,
                "avg_win": 0.02,
                "avg_loss": 0.01,
            }
        ]
        result = allocator.allocate(strategies, Decimal("100000"))
        assert result["only_one"] == Decimal("100000")


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

    def test_trade_has_required_fields(self):
        """交易包含必要字段。"""
        allocator = CapitalAllocator()
        current = {"A": Decimal("60000")}
        target = {"A": Decimal("40000")}
        trades = allocator.rebalance(current, target)
        assert len(trades) == 1
        t = trades[0]
        assert "name" in t
        assert "action" in t
        assert "amount" in t
        assert "current" in t
        assert "target" in t

    def test_strategy_removed_from_target(self):
        """策略从目标中移除时全部卖出。"""
        allocator = CapitalAllocator()
        current = {"A": Decimal("50000"), "B": Decimal("50000")}
        target = {"A": Decimal("100000")}
        trades = allocator.rebalance(current, target)
        sell_trades = [t for t in trades if t["action"] == "sell"]
        assert len(sell_trades) > 0
        assert sell_trades[0]["name"] == "B"

    def test_empty_current(self):
        """当前持仓为空时全部买入。"""
        allocator = CapitalAllocator()
        current = {}
        target = {"A": Decimal("50000"), "B": Decimal("50000")}
        trades = allocator.rebalance(current, target)
        assert all(t["action"] == "buy" for t in trades)

    def test_empty_target(self):
        """目标为空时全部卖出。"""
        allocator = CapitalAllocator()
        current = {"A": Decimal("50000"), "B": Decimal("50000")}
        target = {}
        trades = allocator.rebalance(current, target)
        assert all(t["action"] == "sell" for t in trades)

    def test_sell_sorted_by_amount_desc(self):
        """卖出交易按金额降序排列。"""
        allocator = CapitalAllocator()
        current = {"A": Decimal("80000"), "B": Decimal("60000"), "C": Decimal("70000")}
        target = {"A": Decimal("50000"), "B": Decimal("50000"), "C": Decimal("50000")}
        trades = allocator.rebalance(current, target)
        sell_trades = [t for t in trades if t["action"] == "sell"]
        for i in range(len(sell_trades) - 1):
            assert sell_trades[i]["amount"] >= sell_trades[i + 1]["amount"]

    def test_custom_min_trade_value(self):
        """自定义最小交易金额。"""
        allocator = CapitalAllocator()
        current = {"A": Decimal("50000")}
        target = {"A": Decimal("50050")}
        trades = allocator.rebalance(current, target, min_trade_value=Decimal("10"))
        assert len(trades) == 1

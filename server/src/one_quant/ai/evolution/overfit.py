"""防过拟合验证器 — 样本外 + IC/ICIR衰减 + 多周期稳健"""

from __future__ import annotations

from typing import Any

from one_quant.ai.evolution.models import BacktestResult
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class OverfitValidator:
    """防过拟合验证器 — 样本外 + IC/ICIR衰减 + 多周期稳健"""

    MIN_OOS_SHARPE: float = 0.5
    MAX_TRAIN_TEST_GAP: float = 0.3
    MAX_IC_DECAY_RATE: float = 0.5
    MIN_MULTI_PERIOD_STABLE_RATIO: float = 0.6
    MAX_OVERFIT_SCORE: float = 0.7

    def validate(self, backtest: BacktestResult, train_metrics: dict[str, Any]) -> BacktestResult:
        """综合防过拟合验证"""
        reasons: list[str] = []

        if backtest.oos_sharpe < self.MIN_OOS_SHARPE:
            reasons.append(f"样本外夏普 {backtest.oos_sharpe:.2f} < 阈值 {self.MIN_OOS_SHARPE}")

        train_sharpe = float(train_metrics.get("sharpe_ratio", 0))
        if train_sharpe > 0:
            gap = abs(train_sharpe - backtest.oos_sharpe) / train_sharpe
            backtest.train_test_gap = gap
            if gap > self.MAX_TRAIN_TEST_GAP:
                reasons.append(f"训练/测试差异 {gap:.2%} > 阈值 {self.MAX_TRAIN_TEST_GAP:.0%}")

        if backtest.ic_decay_rate > self.MAX_IC_DECAY_RATE:
            reasons.append(f"IC衰减率 {backtest.ic_decay_rate:.2f} > 阈值 {self.MAX_IC_DECAY_RATE}")

        if not backtest.multi_period_stable:
            reasons.append("多周期稳健性检验未通过")

        overfit_score = self._compute_overfit_score(backtest, train_metrics)
        backtest.overfit_score = overfit_score
        if overfit_score > self.MAX_OVERFIT_SCORE:
            reasons.append(f"过拟合评分 {overfit_score:.2f} > 阈值 {self.MAX_OVERFIT_SCORE}")

        backtest.reject_reasons = reasons
        backtest.passed = len(reasons) == 0

        if not backtest.passed:
            logger.warning(
                "策略 %s 防过拟合验证未通过: %s", backtest.strategy_id, "; ".join(reasons)
            )
        else:
            logger.info("策略 %s 防过拟合验证通过", backtest.strategy_id)

        return backtest

    def _compute_overfit_score(
        self, backtest: BacktestResult, train_metrics: dict[str, Any]
    ) -> float:
        """计算综合过拟合评分 (0-1, 越低越好)"""
        scores: list[float] = []

        train_ret = float(train_metrics.get("total_return", 0))
        if train_ret > 0:
            ret_gap = max(0, (train_ret - backtest.oos_return) / train_ret)
            scores.append(min(ret_gap, 1.0))

        train_sharpe = float(train_metrics.get("sharpe_ratio", 0))
        if train_sharpe > 0:
            sharpe_gap = max(0, (train_sharpe - backtest.oos_sharpe) / train_sharpe)
            scores.append(min(sharpe_gap, 1.0))

        scores.append(min(backtest.ic_decay_rate, 1.0))

        return sum(scores) / len(scores) if scores else 0.0

    def check_multi_period(
        self,
        period_results: dict[str, float],
        min_sharpe: float = 0.3,
    ) -> tuple[bool, float]:
        """多周期稳健性检验"""
        if not period_results:
            return False, 0.0

        passing = sum(1 for s in period_results.values() if s >= min_sharpe)
        ratio = passing / len(period_results)
        passed = ratio >= self.MIN_MULTI_PERIOD_STABLE_RATIO
        return passed, ratio

    def check_ic_decay(self, ic_series: list[float]) -> float:
        """计算 IC 衰减率（线性回归斜率）"""
        if len(ic_series) < 3:
            return 0.0

        n = len(ic_series)
        x_mean = (n - 1) / 2
        y_mean = sum(ic_series) / n

        numerator = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(ic_series))
        denominator = sum((i - x_mean) ** 2 for i in range(n))

        if denominator == 0:
            return 0.0

        slope = numerator / denominator
        return abs(min(slope, 0.0))

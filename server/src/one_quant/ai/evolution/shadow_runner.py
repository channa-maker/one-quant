"""影子运行 — 只读跟单对比预测"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from one_quant.ai.evolution.models import (
    EvolutionAuditRecord,
    ShadowResult,
    StrategyLifecycle,
)
from one_quant.infra.logging import get_logger

if TYPE_CHECKING:
    from one_quant.ai.evolution.platform import EvolutionPlatform

logger = get_logger(__name__)


class ShadowRunnerMixin:
    """影子运行相关方法"""

    # 类型标注仅供 IDE；运行时由 EvolutionPlatform 提供
    _champions: dict[str, Any]
    _recent_market_data: dict[str, Any]
    _auditor: Any

    async def shadow_run(  # type: ignore[misc]
        self: EvolutionPlatform,
        strategy: Any,
        days: int = 30,
    ) -> ShadowResult:
        """⑤影子运行：只读跟单对比预测"""
        strategy.lifecycle = StrategyLifecycle.SHADOW

        correct_count = 0
        total_count = 0
        simulated_pnl = 0.0

        shadow_data = await self._fetch_shadow_data(strategy, days)

        if shadow_data and len(shadow_data) >= 10:
            prices = [d.get("close", 0) for d in shadow_data if "close" in d]
            for i in range(len(prices) - 1):
                if i < 5:
                    continue
                window = prices[max(0, i - 20) : i + 1]
                predicted_direction = 1 if window[-1] > sum(window) / len(window) else -1

                actual_direction = 1 if prices[i + 1] > prices[i] else -1
                total_count += 1
                if predicted_direction == actual_direction:
                    correct_count += 1

                ret = (prices[i + 1] - prices[i]) / prices[i] if prices[i] != 0 else 0
                simulated_pnl += ret * predicted_direction

        signal_accuracy = correct_count / total_count if total_count > 0 else 0.0

        champion_return = 0.0
        if strategy.slot in self._champions:
            champion = self._champions[strategy.slot]
            champion_return = float(champion.metrics.get("live_return", 0))

        result = ShadowResult(
            strategy_id=strategy.strategy_id,
            shadow_days=days,
            total_signals=total_count,
            correct_signals=correct_count,
            signal_accuracy=signal_accuracy,
            simulated_return=simulated_pnl,
            champion_return=champion_return,
            outperformance=simulated_pnl - champion_return,
            sharpe_ratio=self._compute_quick_sharpe(shadow_data) if shadow_data else 0.0,
            max_drawdown=0.0,
        )

        result.passed = result.signal_accuracy > 0.55 and result.outperformance > 0

        self._auditor.record(
            EvolutionAuditRecord(
                event="shadow_run",
                strategy_id=strategy.strategy_id,
                stage="shadow",
                data_used={"shadow_days": days},
                comparison={
                    "signal_accuracy": result.signal_accuracy,
                    "simulated_return": result.simulated_return,
                    "champion_return": result.champion_return,
                },
                decision="通过" if result.passed else "未通过",
                reason=f"信号准确率 {result.signal_accuracy:.1%}, 超额 {result.outperformance:.2%}",
            )
        )

        return result

    async def _fetch_shadow_data(  # type: ignore[misc]
        self: EvolutionPlatform,
        strategy: Any,
        days: int,
    ) -> list[dict[str, Any]]:
        """获取影子运行数据"""
        if self._recent_market_data:
            return self._recent_market_data.get("klines", [])
        return strategy.config.get("historical_data", [])

    @staticmethod
    def _compute_quick_sharpe(data: list[dict[str, Any]]) -> float:
        """快速计算夏普比率"""
        prices = [d.get("close", 0) for d in data if "close" in d]
        if len(prices) < 10:
            return 0.0

        returns = []
        for i in range(1, len(prices)):
            if prices[i - 1] != 0:
                returns.append((prices[i] - prices[i - 1]) / prices[i - 1])

        if not returns:
            return 0.0

        mean_ret = sum(returns) / len(returns)
        std_ret = (sum((r - mean_ret) ** 2 for r in returns) / len(returns)) ** 0.5

        if std_ret == 0:
            return 0.0

        return (mean_ret / std_ret) * (252**0.5)

"""自进化平台 — 策略全生命周期 + 冠军挑战者 + 自动再训练"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any

from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class StrategyLifecycle(str, Enum):
    """策略生命周期阶段"""
    DRAFT = "draft"  # 草稿
    SHADOW = "shadow"  # 影子运行
    GRAYSCALE = "grayscale"  # 灰度
    LIVE = "live"  # 实盘
    CHALLENGER = "challenger"  # 挑战者
    RETIRED = "retired"  # 退役


@dataclass
class StrategyVersion:
    """策略版本记录"""
    strategy_name: str
    version: str
    lifecycle: StrategyLifecycle
    config: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    created_at: int = 0
    promoted_at: int = 0
    retired_at: int = 0

    def __post_init__(self) -> None:
        if self.created_at == 0:
            self.created_at = time.time_ns()


class ChampionChallengerSystem:
    """冠军-挑战者机制。

    影子 PK → 自动晋升 流程：
    1. 挑战者策略在影子模式下运行（不实际交易）
    2. 与冠军策略对比关键指标
    3. 超过阈值则自动晋升为新冠军
    """

    def __init__(
        self,
        min_shadow_days: int = 30,
        min_trades: int = 100,
        outperformance_threshold: Decimal = Decimal("0.05"),
    ) -> None:
        self._min_shadow_days = min_shadow_days
        self._min_trades = min_trades
        self._outperformance_threshold = outperformance_threshold
        self._champions: dict[str, StrategyVersion] = {}  # strategy_name → champion
        self._challengers: dict[str, list[StrategyVersion]] = {}  # strategy_name → [challengers]
        self._history: list[dict[str, Any]] = []

    def register_champion(self, version: StrategyVersion) -> None:
        """注册冠军策略"""
        version.lifecycle = StrategyLifecycle.LIVE
        self._champions[version.strategy_name] = version
        logger.info("冠军策略注册: %s v%s", version.strategy_name, version.version)

    def submit_challenger(self, version: StrategyVersion) -> None:
        """提交挑战者"""
        version.lifecycle = StrategyLifecycle.SHADOW
        if version.strategy_name not in self._challengers:
            self._challengers[version.strategy_name] = []
        self._challengers[version.strategy_name].append(version)
        logger.info("挑战者提交: %s v%s", version.strategy_name, version.version)

    def evaluate(self, strategy_name: str) -> dict[str, Any]:
        """评估挑战者 vs 冠军

        Returns:
            评估结果
        """
        champion = self._champions.get(strategy_name)
        challengers = self._challengers.get(strategy_name, [])

        if not champion or not challengers:
            return {"status": "no_evaluation", "reason": "缺少冠军或挑战者"}

        results = []
        for challenger in challengers:
            if challenger.lifecycle != StrategyLifecycle.SHADOW:
                continue

            c_sharpe = Decimal(str(champion.metrics.get("sharpe_ratio", 0)))
            ch_sharpe = Decimal(str(challenger.metrics.get("sharpe_ratio", 0)))
            c_return = Decimal(str(champion.metrics.get("total_return", 0)))
            ch_return = Decimal(str(challenger.metrics.get("total_return", 0)))

            outperformance = ch_return - c_return
            promoted = outperformance > self._outperformance_threshold

            if promoted:
                # 自动晋升
                challenger.lifecycle = StrategyLifecycle.LIVE
                champion.lifecycle = StrategyLifecycle.RETIRED
                champion.retired_at = time.time_ns()
                self._champions[strategy_name] = challenger

                self._history.append({
                    "event": "champion_promoted",
                    "old_champion": f"{champion.strategy_name} v{champion.version}",
                    "new_champion": f"{challenger.strategy_name} v{challenger.version}",
                    "outperformance": str(outperformance),
                    "timestamp_ns": time.time_ns(),
                })
                logger.info(
                    "新冠军晋升！%s v%s → v%s (超额收益: %s)",
                    strategy_name, champion.version, challenger.version, outperformance,
                )

            results.append({
                "challenger_version": challenger.version,
                "outperformance": str(outperformance),
                "promoted": promoted,
            })

        return {"status": "evaluated", "results": results}

    @property
    def history(self) -> list[dict[str, Any]]:
        return list(self._history)


class AutoRetrainer:
    """自动再训练器 — 滚动窗口 + 概念漂移检测"""

    def __init__(
        self,
        drift_threshold: float = 0.1,
        retrain_window_days: int = 30,
    ) -> None:
        self._drift_threshold = drift_threshold
        self._window_days = retrain_window_days
        self._retrain_history: list[dict[str, Any]] = []

    def detect_drift(self, recent_metrics: list[float], baseline_metrics: list[float]) -> tuple[bool, float]:
        """检测概念漂移

        Args:
            recent_metrics: 近期指标
            baseline_metrics: 基线指标

        Returns:
            (是否漂移, 漂移程度)
        """
        if not recent_metrics or not baseline_metrics:
            return False, 0.0

        recent_avg = sum(recent_metrics) / len(recent_metrics)
        baseline_avg = sum(baseline_metrics) / len(baseline_metrics)

        if baseline_avg == 0:
            return False, 0.0

        drift = abs(recent_avg - baseline_avg) / abs(baseline_avg)
        detected = drift > self._drift_threshold

        if detected:
            logger.warning("概念漂移检测: drift=%.4f (阈值=%.4f)", drift, self._drift_threshold)

        return detected, drift

    def trigger_retrain(self, strategy_name: str, reason: str) -> dict[str, Any]:
        """触发再训练"""
        record = {
            "strategy": strategy_name,
            "reason": reason,
            "timestamp_ns": time.time_ns(),
        }
        self._retrain_history.append(record)
        logger.info("触发再训练: %s (原因: %s)", strategy_name, reason)
        return record

    @property
    def retrain_history(self) -> list[dict[str, Any]]:
        return list(self._retrain_history)

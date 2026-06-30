"""冠军-挑战者机制 — 影子运行 PK → 自动晋升"""

from __future__ import annotations

import time
from typing import Any

from one_quant.ai.evolution.auditor import EvolutionAuditor
from one_quant.ai.evolution.models import (
    ChallengerRecord,
    ChampionRecord,
    ComparisonResult,
    EvolutionAuditRecord,
    Strategy,
    StrategyLifecycle,
)
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class ChampionChallenger:
    """冠军-挑战者机制"""

    MIN_SHADOW_DAYS: int = 14
    MIN_TRADES: int = 50
    OUTPERFORMANCE_THRESHOLD: float = 0.1
    SHARPE_IMPROVEMENT: float = 0.2
    MAX_DD_IMPROVEMENT: float = 0.05

    def __init__(self, auditor: EvolutionAuditor | None = None) -> None:
        self._champions: dict[str, ChampionRecord] = {}
        self._challengers: dict[str, list[ChallengerRecord]] = {}
        self._auditor = auditor or EvolutionAuditor()

    @property
    def auditor(self) -> EvolutionAuditor:
        return self._auditor

    async def register_champion(self, slot: str, strategy: Strategy) -> None:
        """注册冠军策略"""
        strategy.lifecycle = StrategyLifecycle.LIVE
        strategy.slot = slot

        self._champions[slot] = ChampionRecord(
            strategy=strategy,
            promoted_at=time.time_ns(),
            metrics_at_promotion=dict(strategy.metrics),
        )

        self._auditor.record(
            EvolutionAuditRecord(
                event="register_champion",
                strategy_id=strategy.strategy_id,
                stage="live",
                data_used={"slot": slot},
                decision="注册冠军",
                reason=f"成为槽位 {slot} 的冠军策略",
            )
        )

        logger.info("冠军注册: 槽位=%s 策略=%s", slot, strategy.strategy_id)

    async def register_challenger(self, slot: str, strategy: Strategy) -> None:
        """注册挑战者"""
        strategy.lifecycle = StrategyLifecycle.CHALLENGER
        strategy.slot = slot

        if slot not in self._challengers:
            self._challengers[slot] = []

        self._challengers[slot].append(
            ChallengerRecord(
                strategy=strategy,
                submitted_at=time.time_ns(),
            )
        )

        self._auditor.record(
            EvolutionAuditRecord(
                event="register_challenger",
                strategy_id=strategy.strategy_id,
                stage="challenger",
                data_used={"slot": slot},
                decision="注册挑战者",
                reason=f"挑战槽位 {slot} 的冠军",
            )
        )

        logger.info("挑战者注册: 槽位=%s 策略=%s", slot, strategy.strategy_id)

    async def run_comparison(
        self, slot: str, market_data: list[dict[str, Any]]
    ) -> list[ComparisonResult]:
        """影子运行 PK"""
        champion = self._champions.get(slot)
        if not champion:
            logger.warning("槽位 %s 无冠军策略", slot)
            return []

        challengers = self._challengers.get(slot, [])
        results: list[ComparisonResult] = []

        for ch_record in challengers:
            challenger = ch_record.strategy

            comp = ComparisonResult(
                slot=slot,
                champion_id=champion.strategy.strategy_id,
                challenger_id=challenger.strategy_id,
                champion_sharpe=float(champion.strategy.metrics.get("sharpe_ratio", 0)),
                challenger_sharpe=float(challenger.metrics.get("sharpe_ratio", 0)),
                champion_max_dd=float(champion.strategy.metrics.get("max_drawdown", 0)),
                challenger_max_dd=float(challenger.metrics.get("max_drawdown", 0)),
            )

            if comp.champion_sharpe > 0:
                comp.outperformance = (
                    comp.challenger_sharpe - comp.champion_sharpe
                ) / comp.champion_sharpe

            sharpe_pass = comp.challenger_sharpe >= comp.champion_sharpe * (
                1 + self.SHARPE_IMPROVEMENT
            )
            dd_pass = comp.challenger_max_dd <= comp.champion_max_dd + self.MAX_DD_IMPROVEMENT
            return_pass = comp.outperformance >= self.OUTPERFORMANCE_THRESHOLD

            comp.promoted = sharpe_pass and dd_pass and return_pass
            comp.stability_score = sum([sharpe_pass, dd_pass, return_pass]) / 3.0

            if comp.promoted:
                comp.reason = (
                    f"挑战者全面超越: 夏普 {comp.challenger_sharpe:.2f} "
                    f"vs {comp.champion_sharpe:.2f}, "
                    f"回撤 {comp.challenger_max_dd:.2%} vs {comp.champion_max_dd:.2%}, "
                    f"超额 {comp.outperformance:.2%}"
                )
            else:
                failed = []
                if not sharpe_pass:
                    failed.append("夏普未达标")
                if not dd_pass:
                    failed.append("回撤未改善")
                if not return_pass:
                    failed.append("超额收益不足")
                comp.reason = f"未通过: {', '.join(failed)}"

            ch_record.comparison_results.append(
                {
                    "promoted": comp.promoted,
                    "outperformance": comp.outperformance,
                    "stability_score": comp.stability_score,
                    "timestamp_ns": time.time_ns(),
                }
            )

            results.append(comp)

            self._auditor.record(
                EvolutionAuditRecord(
                    event="run_comparison",
                    strategy_id=challenger.strategy_id,
                    stage="challenger",
                    data_used={"market_data_points": len(market_data)},
                    comparison={
                        "champion_sharpe": comp.champion_sharpe,
                        "challenger_sharpe": comp.challenger_sharpe,
                        "champion_max_dd": comp.champion_max_dd,
                        "challenger_max_dd": comp.challenger_max_dd,
                        "outperformance": comp.outperformance,
                        "stability_score": comp.stability_score,
                    },
                    decision="晋升" if comp.promoted else "保留冠军",
                    reason=comp.reason,
                )
            )

        promoted = [r for r in results if r.promoted]
        if promoted:
            best = max(promoted, key=lambda r: r.challenger_sharpe)
            await self.promote_challenger(slot, best.challenger_id)

        return results

    async def promote_challenger(self, slot: str, challenger_id: str) -> None:
        """挑战者晋升"""
        challengers = self._challengers.get(slot, [])
        target = None
        for ch in challengers:
            if ch.strategy.strategy_id == challenger_id:
                target = ch
                break

        if not target:
            logger.warning("挑战者 %s 未找到", challenger_id)
            return

        old_champion = self._champions.get(slot)
        if old_champion:
            old_champion.strategy.lifecycle = StrategyLifecycle.RETIRED
            old_champion.strategy.updated_at = time.time_ns()

        target.strategy.lifecycle = StrategyLifecycle.LIVE
        target.strategy.slot = slot
        self._champions[slot] = ChampionRecord(
            strategy=target.strategy,
            promoted_at=time.time_ns(),
            metrics_at_promotion=dict(target.strategy.metrics),
        )

        self._challengers[slot] = [
            ch for ch in challengers if ch.strategy.strategy_id != challenger_id
        ]

        self._auditor.record(
            EvolutionAuditRecord(
                event="promote_challenger",
                strategy_id=challenger_id,
                stage="live",
                data_used={
                    "slot": slot,
                    "old_champion": old_champion.strategy.strategy_id if old_champion else "none",
                },
                decision="晋升成功",
                reason=f"挑战者 {challenger_id} 晋升为槽位 {slot} 新冠军",
            )
        )

        logger.info(
            "挑战者晋升: 槽位=%s 旧冠军=%s 新冠军=%s",
            slot,
            old_champion.strategy.strategy_id if old_champion else "none",
            challenger_id,
        )

    def get_audit_trail(self, slot: str) -> list[dict[str, Any]]:
        """获取槽位的换代审计记录"""
        records: list[dict[str, Any]] = []

        champion = self._champions.get(slot)
        if champion:
            records.append(
                {
                    "event": "current_champion",
                    "strategy_id": champion.strategy.strategy_id,
                    "promoted_at": champion.promoted_at,
                    "metrics_at_promotion": champion.metrics_at_promotion,
                }
            )

        all_audits = self._auditor.get_all()
        slot_ids = set()
        if champion:
            slot_ids.add(champion.strategy.strategy_id)
        for ch in self._challengers.get(slot, []):
            slot_ids.add(ch.strategy.strategy_id)

        for audit in all_audits:
            if audit["strategy_id"] in slot_ids:
                records.append(audit)

        return records

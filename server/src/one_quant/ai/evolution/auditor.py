"""进化审计器 — 全链路可追溯"""

from __future__ import annotations

from typing import Any

from one_quant.ai.evolution.models import EvolutionAuditRecord
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class EvolutionAuditor:
    """进化审计器 — 全链路可追溯"""

    def __init__(self) -> None:
        self._records: list[EvolutionAuditRecord] = []

    def record(self, record: EvolutionAuditRecord) -> None:
        """记录审计事件"""
        self._records.append(record)
        logger.info(
            "审计记录: event=%s strategy=%s stage=%s decision=%s",
            record.event,
            record.strategy_id,
            record.stage,
            record.decision,
        )

    def get_trail(self, strategy_id: str) -> list[dict[str, Any]]:
        """获取策略的完整审计轨迹"""
        return [
            {
                "event": r.event,
                "stage": r.stage,
                "data_used": r.data_used,
                "comparison": r.comparison,
                "decision": r.decision,
                "reason": r.reason,
                "metrics_snapshot": r.metrics_snapshot,
                "timestamp_ns": r.timestamp_ns,
            }
            for r in self._records
            if r.strategy_id == strategy_id
        ]

    def get_all(self) -> list[dict[str, Any]]:
        """获取全部审计记录"""
        return [
            {
                "event": r.event,
                "strategy_id": r.strategy_id,
                "stage": r.stage,
                "decision": r.decision,
                "reason": r.reason,
                "timestamp_ns": r.timestamp_ns,
            }
            for r in self._records
        ]

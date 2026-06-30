"""模型治理 — 模型风险管理 MRM + AI 防护"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class ModelStatus(str, Enum):
    DRAFT = "draft"
    VALIDATION = "validation"
    APPROVED = "approved"
    LIVE = "live"
    RETIRED = "retired"


@dataclass
class ModelCard:
    """模型卡 — 模型元信息与治理记录"""
    model_id: str
    name: str
    version: str
    description: str
    status: ModelStatus = ModelStatus.DRAFT
    owner: str = ""
    validation_results: dict[str, Any] = field(default_factory=dict)
    approval_chain: list[dict[str, Any]] = field(default_factory=list)
    created_at: int = 0
    approved_at: int = 0
    retired_at: int = 0

    def __post_init__(self) -> None:
        if self.created_at == 0:
            self.created_at = time.time_ns()


class ModelRiskManager:
    """模型风险管理器 (MRM)。

    - 模型清单管理
    - 独立验证流程
    - 审批链
    - 退役机制
    """

    def __init__(self) -> None:
        self._models: dict[str, ModelCard] = {}

    def register(self, card: ModelCard) -> None:
        self._models[card.model_id] = card
        logger.info("模型注册: %s v%s", card.name, card.version)

    def submit_validation(self, model_id: str, results: dict[str, Any]) -> bool:
        card = self._models.get(model_id)
        if not card:
            return False
        card.validation_results = results
        card.status = ModelStatus.VALIDATION
        logger.info("模型提交验证: %s", model_id)
        return True

    def approve(self, model_id: str, approver: str, notes: str = "") -> bool:
        card = self._models.get(model_id)
        if not card:
            return False
        card.approval_chain.append({
            "approver": approver,
            "action": "approve",
            "notes": notes,
            "timestamp_ns": time.time_ns(),
        })
        card.status = ModelStatus.APPROVED
        card.approved_at = time.time_ns()
        logger.info("模型审批通过: %s by %s", model_id, approver)
        return True

    def retire(self, model_id: str, reason: str) -> bool:
        card = self._models.get(model_id)
        if not card:
            return False
        card.status = ModelStatus.RETIRED
        card.retired_at = time.time_ns()
        logger.info("模型退役: %s (原因: %s)", model_id, reason)
        return True

    def list_models(self, status: ModelStatus | None = None) -> list[ModelCard]:
        if status:
            return [m for m in self._models.values() if m.status == status]
        return list(self._models.values())


class AIDataPoisoning防护:
    """AI 数据投毒防护。

    - 新闻源可信度加权
    - 多源交叉验证
    - 低置信度拒绝行动
    """

    def __init__(self, min_confidence: float = 0.6) -> None:
        self._min_confidence = min_confidence
        self._source_trust: dict[str, float] = {}

    def set_trust(self, source: str, trust_score: float) -> None:
        self._source_trust[source] = max(0.0, min(1.0, trust_score))

    def get_trust(self, source: str) -> float:
        return self._source_trust.get(source, 0.5)

    def cross_validate(self, claims: list[dict[str, Any]]) -> tuple[bool, float]:
        """多源交叉验证

        Args:
            claims: [{source, claim, confidence}]

        Returns:
            (是否可信, 综合置信度)
        """
        if not claims:
            return False, 0.0

        weighted_sum = 0.0
        weight_total = 0.0
        for c in claims:
            trust = self.get_trust(c.get("source", ""))
            conf = c.get("confidence", 0.0)
            weighted_sum += trust * conf
            weight_total += trust

        avg_confidence = weighted_sum / weight_total if weight_total > 0 else 0.0
        credible = avg_confidence >= self._min_confidence

        if not credible:
            logger.warning("数据投毒检测: 置信度 %.3f < 阈值 %.3f", avg_confidence, self._min_confidence)

        return credible, avg_confidence

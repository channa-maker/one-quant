"""
LLM Provider — 响应模型与枚举
"""

from __future__ import annotations

from dataclasses import field
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class LLMResponse(BaseModel, frozen=True):
    """LLM 响应 — 不可变，保证数据一致性。"""

    content: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: Decimal = Decimal("0")
    model: str = ""
    provider: str = ""
    latency_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    class Config:
        arbitrary_types_allowed = True


class TaskComplexity(StrEnum):
    """任务复杂度等级，用于路由决策。"""

    HIGH = "high"  # 推理/规划/复杂分析
    MEDIUM = "medium"  # 分析/解读/总结
    LOW = "low"  # 分类/提取/格式化

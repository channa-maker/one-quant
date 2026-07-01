"""
LLM Provider — 抽象基类
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any

from one_quant.ai.llm_provider.models import LLMResponse


class LLMProvider(ABC):
    """LLM Provider 抽象基类。

    所有 Provider 实现此类，提供统一的 complete 接口。
    """

    name: str
    supported_models: list[str]

    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> LLMResponse:
        """调用 LLM 生成补全。"""
        ...

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """估算文本 token 数量。"""
        ...

    @abstractmethod
    def estimate_cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        """估算调用成本（USD）。"""
        ...

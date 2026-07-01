"""
LLM Provider — 路由器
"""

from __future__ import annotations

import logging
from typing import Any

from one_quant.ai.llm_provider.base import LLMProvider
from one_quant.ai.llm_provider.models import LLMResponse, TaskComplexity
from one_quant.ai.llm_provider.security import sanitize_user_text, wrap_user_content

logger = logging.getLogger(__name__)


class LLMRouter:
    """LLM 路由器：按任务复杂度/成本自动选择最优 Provider。

    路由策略：
    - 高复杂度 (推理/规划) → Claude Opus 或 DeepSeek Reasoner
    - 中复杂度 (分析/解读) → Claude Sonnet 或 DeepSeek Chat
    - 低复杂度 (分类/提取) → DeepSeek Chat 或 Claude Haiku
    """

    ROUTE_TABLE: dict[TaskComplexity, list[tuple[str, str]]] = {
        TaskComplexity.HIGH: [
            ("claude", "claude-opus-4-20250514"),
            ("deepseek", "deepseek-reasoner"),
            ("claude", "claude-sonnet-4-20250514"),
        ],
        TaskComplexity.MEDIUM: [
            ("claude", "claude-sonnet-4-20250514"),
            ("deepseek", "deepseek-chat"),
        ],
        TaskComplexity.LOW: [
            ("deepseek", "deepseek-chat"),
            ("claude", "claude-3-5-haiku-20241022"),
        ],
    }

    def __init__(self, providers: dict[str, LLMProvider]) -> None:
        self._providers = providers

    async def route(
        self,
        task_complexity: TaskComplexity | str,
        messages: list[dict[str, str]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> LLMResponse:
        """根据任务复杂度路由到最优 Provider。"""
        if isinstance(task_complexity, str):
            task_complexity = TaskComplexity(task_complexity)

        routes = self.ROUTE_TABLE.get(task_complexity) or self.ROUTE_TABLE.get(
            TaskComplexity.MEDIUM, []
        )

        errors: list[str] = []
        for provider_name, model in routes:
            provider = self._providers.get(provider_name)
            if not provider:
                errors.append(f"Provider '{provider_name}' 未注册")
                continue

            try:
                resp = await provider.complete(
                    messages=messages,
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    **kwargs,
                )
                return resp
            except Exception as exc:
                error_msg = f"{provider_name}/{model} 调用失败: {exc}"
                logger.warning("路由降级: %s", error_msg)
                errors.append(error_msg)
                continue

        raise RuntimeError(f"所有 Provider 均失败: {'; '.join(errors)}")

    async def route_with_sanitize(
        self,
        task_complexity: TaskComplexity | str,
        system_prompt: str,
        user_text: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> LLMResponse:
        """带 Prompt 注入防护的路由调用。"""
        safe_text = sanitize_user_text(user_text)
        wrapped_text = wrap_user_content(safe_text)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": wrapped_text},
        ]

        return await self.route(
            task_complexity=task_complexity,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs,
        )

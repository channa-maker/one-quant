"""AI 智能体框架 — 多 Provider + token 计量 + 日预算硬上限"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


@dataclass
class LLMResponse:
    """LLM 响应"""
    content: str
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal("0")
    latency_ms: float = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class LLMProvider(ABC):
    """LLM 提供商基类"""

    name: str

    @abstractmethod
    async def complete(self, prompt: str, system: str = "", **kwargs: Any) -> LLMResponse:
        ...

    @abstractmethod
    def estimate_cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        ...


class DeepSeekProvider(LLMProvider):
    """DeepSeek 提供商"""
    name = "deepseek"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        # pricing: ~$0.14/M input, ~$0.28/M output
        self._input_price = Decimal("0.00000014")
        self._output_price = Decimal("0.00000028")

    async def complete(self, prompt: str, system: str = "", **kwargs: Any) -> LLMResponse:
        import httpx
        start = time.time()
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    **kwargs,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            usage = data.get("usage", {})
            content = data["choices"][0]["message"]["content"]
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)
            cost = self.estimate_cost(input_tokens, output_tokens)
            return LLMResponse(
                content=content, model="deepseek-chat", provider="deepseek",
                input_tokens=input_tokens, output_tokens=output_tokens,
                cost_usd=cost, latency_ms=(time.time() - start) * 1000,
            )

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        return Decimal(input_tokens) * self._input_price + Decimal(output_tokens) * self._output_price


class AnthropicProvider(LLMProvider):
    """Anthropic (Claude) 提供商"""
    name = "anthropic"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._input_price = Decimal("0.000003")
        self._output_price = Decimal("0.000015")

    async def complete(self, prompt: str, system: str = "", **kwargs: Any) -> LLMResponse:
        import httpx
        start = time.time()
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 4096,
                    "system": system,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            usage = data.get("usage", {})
            content = data["content"][0]["text"]
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)
            return LLMResponse(
                content=content, model="claude-sonnet-4", provider="anthropic",
                input_tokens=input_tokens, output_tokens=output_tokens,
                cost_usd=self.estimate_cost(input_tokens, output_tokens),
                latency_ms=(time.time() - start) * 1000,
            )

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        return Decimal(input_tokens) * self._input_price + Decimal(output_tokens) * self._output_price


class LLMTokenMeter:
    """Token 计量器 + 日预算硬上限"""

    def __init__(self, daily_budget_usd: Decimal = Decimal("50")) -> None:
        self._daily_budget = daily_budget_usd
        self._daily_cost = Decimal("0")
        self._daily_date = ""
        self._total_cost = Decimal("0")
        self._call_count = 0

    def check_budget(self) -> bool:
        """检查日预算是否超限"""
        import datetime
        today = datetime.date.today().isoformat()
        if today != self._daily_date:
            self._daily_cost = Decimal("0")
            self._daily_date = today
        return self._daily_cost < self._daily_budget

    def record(self, response: LLMResponse) -> None:
        """记录消费"""
        self._daily_cost += response.cost_usd
        self._total_cost += response.cost_usd
        self._call_count += 1

        if self._daily_cost >= self._daily_budget:
            logger.error(
                "LLM 日预算已耗尽！今日消费: $%s / 预算: $%s",
                self._daily_cost, self._daily_budget,
            )

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "daily_cost_usd": str(self._daily_cost),
            "daily_budget_usd": str(self._daily_budget),
            "total_cost_usd": str(self._total_cost),
            "call_count": self._call_count,
            "budget_remaining_pct": str((1 - self._daily_cost / self._daily_budget) * 100) if self._daily_budget > 0 else "0",
        }

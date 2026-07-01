"""
LLM Provider — Claude Provider
"""

from __future__ import annotations

import re
import time
from decimal import Decimal
from typing import Any

from one_quant.ai.llm_provider.base import LLMProvider
from one_quant.ai.llm_provider.models import LLMResponse
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class ClaudeProvider(LLMProvider):
    """Claude Provider (Anthropic Messages API)。"""

    name = "claude"
    supported_models = [
        "claude-sonnet-4-20250514",
        "claude-opus-4-20250514",
        "claude-3-5-haiku-20241022",
    ]

    PRICING: dict[str, dict[str, Decimal]] = {
        "claude-sonnet-4-20250514": {
            "input": Decimal("0.000003"),
            "output": Decimal("0.000015"),
        },
        "claude-opus-4-20250514": {
            "input": Decimal("0.000015"),
            "output": Decimal("0.000075"),
        },
        "claude-3-5-haiku-20241022": {
            "input": Decimal("0.0000008"),
            "output": Decimal("0.000004"),
        },
    }

    def __init__(self, api_key: str, default_model: str = "claude-sonnet-4-20250514") -> None:
        self._api_key = api_key
        self._default_model = default_model

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> LLMResponse:
        """调用 Anthropic Messages API。"""
        import httpx

        model = model or self._default_model
        start = time.time()

        system_text = ""
        user_messages: list[dict[str, str]] = []
        for msg in messages:
            if msg.get("role") == "system":
                system_text = msg.get("content", "")
            else:
                user_messages.append(msg)

        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": user_messages,
        }
        if system_text:
            payload["system"] = system_text

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        usage = data.get("usage", {})
        content = data["content"][0]["text"]
        tokens_in = usage.get("input_tokens", 0)
        tokens_out = usage.get("output_tokens", 0)
        cost = self.estimate_cost(tokens_in, tokens_out, model)
        latency = (time.time() - start) * 1000

        logger.info(
            "Claude 调用完成: model=%s tokens_in=%d tokens_out=%d cost=$%s latency=%.0fms",
            model,
            tokens_in,
            tokens_out,
            cost,
            latency,
        )

        return LLMResponse(
            content=content,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
            model=model,
            provider=self.name,
            latency_ms=latency,
        )

    def count_tokens(self, text: str) -> int:
        """粗略估算 token 数。"""
        cn_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
        en_chars = len(text) - cn_chars
        return int(cn_chars / 1.5 + en_chars / 4)

    def estimate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        model: str = "",
    ) -> Decimal:
        """估算 Claude 调用成本。"""
        model = model or self._default_model
        pricing = self.PRICING.get(model, self.PRICING[self._default_model])
        return Decimal(input_tokens) * pricing["input"] + Decimal(output_tokens) * pricing["output"]

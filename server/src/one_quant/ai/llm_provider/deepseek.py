"""
LLM Provider — DeepSeek Provider
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


class DeepSeekProvider(LLMProvider):
    """DeepSeek Provider（兼容 OpenAI 格式）。"""

    name = "deepseek"
    supported_models = ["deepseek-chat", "deepseek-reasoner"]

    PRICING: dict[str, dict[str, Decimal]] = {
        "deepseek-chat": {
            "input": Decimal("0.00000014"),
            "output": Decimal("0.00000028"),
        },
        "deepseek-reasoner": {
            "input": Decimal("0.00000055"),
            "output": Decimal("0.00000219"),
        },
    }

    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com") -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> LLMResponse:
        """调用 DeepSeek Chat API（OpenAI 兼容格式）。"""
        import httpx

        model = model or "deepseek-chat"
        start = time.time()

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self._base_url}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    **kwargs,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        usage = data.get("usage", {})
        content = data["choices"][0]["message"]["content"]
        tokens_in = usage.get("prompt_tokens", 0)
        tokens_out = usage.get("completion_tokens", 0)
        cost = self.estimate_cost(tokens_in, tokens_out, model)
        latency = (time.time() - start) * 1000

        logger.info(
            "DeepSeek 调用完成: model=%s tokens_in=%d tokens_out=%d cost=$%s latency=%.0fms",
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
        """估算 DeepSeek 调用成本。"""
        model = model or "deepseek-chat"
        pricing = self.PRICING.get(model, self.PRICING["deepseek-chat"])
        return Decimal(input_tokens) * pricing["input"] + Decimal(output_tokens) * pricing["output"]

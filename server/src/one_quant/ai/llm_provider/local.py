"""
LLM Provider — 本地开源模型 Provider
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


class LocalProvider(LLMProvider):
    """本地开源模型 Provider（预留接口）。

    支持 vLLM / Ollama 等本地推理引擎。
    """

    name = "local"
    supported_models = ["local-default"]

    def __init__(
        self, base_url: str = "http://localhost:11434", model: str = "local-default"
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._default_model = model

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> LLMResponse:
        """调用本地模型 API（OpenAI 兼容格式）。"""
        import httpx

        model = model or self._default_model
        start = time.time()

        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(
                f"{self._base_url}/v1/chat/completions",
                headers={"Content-Type": "application/json"},
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
        latency = (time.time() - start) * 1000

        logger.info(
            "本地模型调用完成: model=%s tokens_in=%d tokens_out=%d latency=%.0fms",
            model,
            tokens_in,
            tokens_out,
            latency,
        )

        return LLMResponse(
            content=content,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=Decimal("0"),
            model=model,
            provider=self.name,
            latency_ms=latency,
        )

    def count_tokens(self, text: str) -> int:
        """粗略估算 token 数。"""
        cn_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
        en_chars = len(text) - cn_chars
        return int(cn_chars / 1.5 + en_chars / 4)

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        """本地模型无费用。"""
        return Decimal("0")

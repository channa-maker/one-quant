"""B-7 多 LLM Provider 测试

测试场景：
1. Ollama provider 基本功能
2. Provider 级 failover（主 provider 失败 → 备 provider）
3. Token 计量正确性
4. Provider 配置热加载
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from one_quant.ai.llm_provider import (
    LLMProvider,
    LLMResponse,
    LLMRouter,
    OllamaProvider,
    TaskComplexity,
    TokenMeter,
)

# ──────────────────── Mock Provider ────────────────────


class MockProvider(LLMProvider):
    """模拟 LLM Provider，可控失败。"""

    def __init__(
        self,
        name: str,
        models: list[str] | None = None,
        should_fail: bool = False,
        response_text: str = "OK",
        tokens_in: int = 100,
        tokens_out: int = 50,
    ) -> None:
        self.name = name
        self.supported_models = models or ["mock-model"]
        self._should_fail = should_fail
        self._response_text = response_text
        self._tokens_in = tokens_in
        self._tokens_out = tokens_out
        self.call_count = 0
        self.last_messages: list[dict[str, str]] = []

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> LLMResponse:
        self.call_count += 1
        self.last_messages = messages
        if self._should_fail:
            raise ConnectionError(f"{self.name}: 连接失败")
        return LLMResponse(
            content=self._response_text,
            tokens_in=self._tokens_in,
            tokens_out=self._tokens_out,
            cost_usd=self.estimate_cost(self._tokens_in, self._tokens_out),
            model=model or self.supported_models[0],
            provider=self.name,
            latency_ms=100.0,
        )

    def count_tokens(self, text: str) -> int:
        return len(text) // 2

    def estimate_cost(self, input_tokens: int, output_tokens: int, model: str = "") -> Decimal:
        return Decimal(input_tokens) * Decimal("0.000001") + Decimal(output_tokens) * Decimal(
            "0.000002"
        )


# ──────────────────── 测试: Ollama Provider ────────────────────


class TestOllamaProvider:
    """测试 Ollama 本地 Provider。"""

    def test_ollama_provider_init(self):
        """Ollama provider 应正确初始化。"""
        provider = OllamaProvider(base_url="http://localhost:11434", model="qwen2.5:7b")
        assert provider.name == "ollama"
        assert "qwen2.5:7b" in provider.supported_models

    def test_ollama_cost_zero(self):
        """本地模型无费用。"""
        provider = OllamaProvider()
        cost = provider.estimate_cost(1000, 500)
        assert cost == Decimal("0")

    @pytest.mark.asyncio
    async def test_ollama_complete_mock(self):
        """Ollama provider 应能正常调用（mock）。"""
        provider = OllamaProvider(model="qwen2.5:7b")

        mock_response = {
            "choices": [{"message": {"content": "测试回复"}}],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
            },
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = AsyncMock(
                status_code=200,
                json=lambda: mock_response,
                raise_for_status=lambda: None,
            )
            resp = await provider.complete(
                messages=[{"role": "user", "content": "你好"}],
                model="qwen2.5:7b",
            )

        assert resp.content == "测试回复"
        assert resp.tokens_in == 100
        assert resp.tokens_out == 50
        assert resp.cost_usd == Decimal("0")
        assert resp.provider == "ollama"


# ──────────────────── 测试: Provider Failover ────────────────────


class TestProviderFailover:
    """测试 Provider 级故障转移。"""

    @pytest.mark.asyncio
    async def test_primary_provider_fail_fallback(self):
        """主 provider 失败时应切到备选。"""
        primary = MockProvider(name="primary", should_fail=True)
        secondary = MockProvider(name="secondary", response_text="备选回复")

        # 扩展路由表支持 local 优先
        router = LLMRouter(providers={"primary": primary, "secondary": secondary})
        router.ROUTE_TABLE = {
            TaskComplexity.LOW: [
                ("primary", "mock-model"),
                ("secondary", "mock-model"),
            ],
        }

        resp = await router.route(
            task_complexity=TaskComplexity.LOW,
            messages=[{"role": "user", "content": "测试"}],
        )

        assert resp.provider == "secondary"
        assert resp.content == "备选回复"
        assert primary.call_count == 1
        assert secondary.call_count == 1

    @pytest.mark.asyncio
    async def test_all_providers_fail_raises(self):
        """所有 provider 失败时应抛出聚合异常。"""
        p1 = MockProvider(name="p1", should_fail=True)
        p2 = MockProvider(name="p2", should_fail=True)

        router = LLMRouter(providers={"p1": p1, "p2": p2})
        router.ROUTE_TABLE = {
            TaskComplexity.LOW: [
                ("p1", "mock-model"),
                ("p2", "mock-model"),
            ],
        }

        with pytest.raises(RuntimeError, match="所有 Provider 均失败"):
            await router.route(
                task_complexity=TaskComplexity.LOW,
                messages=[{"role": "user", "content": "测试"}],
            )

    @pytest.mark.asyncio
    async def test_local_provider_first_strategy(self):
        """配置 local 优先时，应先尝试本地 provider。"""
        local = MockProvider(name="local", response_text="本地回复")
        cloud = MockProvider(name="cloud", response_text="云端回复")

        router = LLMRouter(providers={"local": local, "cloud": cloud})
        router.ROUTE_TABLE = {
            TaskComplexity.LOW: [
                ("local", "local-model"),
                ("cloud", "cloud-model"),
            ],
        }

        resp = await router.route(
            task_complexity=TaskComplexity.LOW,
            messages=[{"role": "user", "content": "测试"}],
        )

        assert resp.provider == "local"
        assert local.call_count == 1
        assert cloud.call_count == 0  # 云端未被调用


# ──────────────────── 测试: Token 计量 ────────────────────


class TestTokenMeterMultiProvider:
    """测试多 Provider 场景下的 Token 计量。"""

    def test_meter_tracks_multiple_providers(self):
        """计量器应能追踪多 provider 的用量。"""
        meter = TokenMeter(daily_budget_usd=Decimal("100"))
        today = "2025-01-01"

        meter.record("ollama", "qwen2.5:7b", 1000, 500, Decimal("0"), today=today)
        meter.record("deepseek", "deepseek-chat", 800, 400, Decimal("0.224"), today=today)
        meter.record("claude", "claude-sonnet-4-20250514", 500, 300, Decimal("6.0"), today=today)

        summary = meter.get_daily_summary(today=today)
        assert summary["total_calls"] == 3
        assert "ollama" in summary["by_provider"]
        assert "deepseek" in summary["by_provider"]
        assert "claude" in summary["by_provider"]
        assert summary["by_provider"]["ollama"]["cost_usd"] == "0"

    def test_meter_budget_check_across_providers(self):
        """跨 provider 的预算检查应正确。"""
        meter = TokenMeter(daily_budget_usd=Decimal("10"))
        today = "2025-01-01"

        meter.record("deepseek", "deepseek-chat", 1000, 500, Decimal("5"), today=today)
        assert meter.check_budget(today=today) is True

        meter.record("claude", "claude-sonnet", 1000, 500, Decimal("6"), today=today)
        assert meter.check_budget(today=today) is False  # 超预算

    def test_meter_ollama_zero_cost(self):
        """Ollama 调用应记录为零成本。"""
        meter = TokenMeter(daily_budget_usd=Decimal("50"))
        today = "2025-01-01"

        meter.record("ollama", "qwen2.5:7b", 2000, 1000, Decimal("0"), today=today)

        summary = meter.get_daily_summary(today=today)
        assert summary["total_cost_usd"] == "0"
        assert summary["remaining_usd"] == "50"


# ──────────────────── 测试: AGENT_PROVIDER 配置 ────────────────────


class TestAgentProviderConfig:
    """测试 AGENT_PROVIDER 扩展配置。"""

    def test_agent_provider_registry(self):
        """AGENT_PROVIDER 注册表应支持 ollama 类型。"""
        from one_quant.ai.llm_provider import AGENT_PROVIDER

        assert "ollama" in AGENT_PROVIDER
        assert AGENT_PROVIDER["ollama"] is OllamaProvider

    def test_create_provider_from_config(self):
        """应能从配置字典创建 provider 实例。"""
        from one_quant.ai.llm_provider import create_provider_from_config

        provider = create_provider_from_config(
            {
                "type": "ollama",
                "base_url": "http://localhost:11434",
                "model": "qwen2.5:7b",
            }
        )
        assert isinstance(provider, OllamaProvider)
        assert provider.name == "ollama"

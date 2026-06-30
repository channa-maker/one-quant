"""AI 智能体测试

覆盖模块: one_quant.ai.agents
目标: ≥80% 覆盖率
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from one_quant.ai.agents import (
    BaseAgent,
    BriefingAgent,
    DebateGroup,
    InterpreterAgent,
    MacroAgent,
    SentimentAgent,
    SentinelAgent,
    TriageAgent,
)
from one_quant.ai.llm_provider import LLMProvider, LLMResponse, TokenMeter

# ──────────────────── 辅助工厂 ────────────────────


def _make_provider(content: str = "测试回复") -> LLMProvider:
    provider = MagicMock(spec=LLMProvider)
    provider.complete = AsyncMock(
        return_value=LLMResponse(
            content=content,
            tokens_in=100,
            tokens_out=50,
            cost_usd=Decimal("0.01"),
            model="test",
            provider="test",
        )
    )
    return provider


def _make_meter(budget_ok: bool = True) -> TokenMeter:
    meter = MagicMock(spec=TokenMeter)
    meter.check_budget.return_value = budget_ok
    meter.record = MagicMock()
    return meter


# ──────────────────── BaseAgent 测试 ────────────────────


class TestBaseAgent:
    """智能体基类测试"""

    async def test_run_success(self):
        provider = _make_provider("市场看涨")
        meter = _make_meter()
        agent = BriefingAgent(provider=provider, meter=meter)
        resp = await agent.run("今日行情如何？")
        assert resp is not None
        assert resp.content == "市场看涨"
        provider.complete.assert_called_once()
        meter.record.assert_called_once()

    async def test_run_budget_exceeded(self):
        provider = _make_provider()
        meter = _make_meter(budget_ok=False)
        agent = BriefingAgent(provider=provider, meter=meter)
        resp = await agent.run("今日行情如何？")
        assert resp is None
        provider.complete.assert_not_called()

    async def test_run_passes_kwargs(self):
        provider = _make_provider()
        meter = _make_meter()
        agent = BriefingAgent(provider=provider, meter=meter)
        await agent.run("test", max_tokens=100, temperature=0.5)
        call_kwargs = provider.complete.call_args
        # 验证参数传递
        assert call_kwargs is not None


# ──────────────────── 各智能体测试 ────────────────────


class TestBriefingAgent:
    """简报官测试"""

    def test_attributes(self):
        agent = BriefingAgent(provider=_make_provider(), meter=_make_meter())
        assert agent.name == "briefing"
        assert agent.role_zh == "简报官"
        assert "简报" in agent.system_prompt

    async def test_run(self):
        agent = BriefingAgent(provider=_make_provider("今日市场综述"), meter=_make_meter())
        resp = await agent.run("总结今日行情")
        assert resp.content == "今日市场综述"


class TestSentinelAgent:
    """哨兵测试"""

    def test_attributes(self):
        agent = SentinelAgent(provider=_make_provider(), meter=_make_meter())
        assert agent.name == "sentinel"
        assert agent.role_zh == "哨兵"
        assert "异常" in agent.system_prompt


class TestTriageAgent:
    """分诊员测试"""

    def test_attributes(self):
        agent = TriageAgent(provider=_make_provider(), meter=_make_meter())
        assert agent.name == "triage"
        assert agent.role_zh == "分诊员"


class TestInterpreterAgent:
    """解读员测试"""

    def test_attributes(self):
        agent = InterpreterAgent(provider=_make_provider(), meter=_make_meter())
        assert agent.name == "interpreter"
        assert agent.role_zh == "解读员"


class TestSentimentAgent:
    """情绪分析师测试"""

    def test_attributes(self):
        agent = SentimentAgent(provider=_make_provider(), meter=_make_meter())
        assert agent.name == "sentiment"
        assert agent.role_zh == "情绪分析师"
        assert "情绪" in agent.system_prompt


class TestMacroAgent:
    """宏观分析师测试"""

    def test_attributes(self):
        agent = MacroAgent(provider=_make_provider(), meter=_make_meter())
        assert agent.name == "macro"
        assert agent.role_zh == "宏观分析师"
        assert "宏观" in agent.system_prompt


# ──────────────────── DebateGroup 测试 ────────────────────


class TestDebateGroup:
    """多空辩论组测试"""

    async def test_debate(self):
        bull = MagicMock(spec=BaseAgent)
        bull.run = AsyncMock(
            return_value=LLMResponse(
                content="看多理由：趋势向上",
                tokens_in=10,
                tokens_out=20,
                cost_usd=Decimal("0.01"),
                model="m",
                provider="p",
            )
        )
        bear = MagicMock(spec=BaseAgent)
        bear.run = AsyncMock(
            return_value=LLMResponse(
                content="看空理由：估值过高",
                tokens_in=10,
                tokens_out=20,
                cost_usd=Decimal("0.01"),
                model="m",
                provider="p",
            )
        )
        judge = MagicMock(spec=BaseAgent)
        judge.run = AsyncMock(
            return_value=LLMResponse(
                content="综合判断：谨慎看多",
                tokens_in=10,
                tokens_out=20,
                cost_usd=Decimal("0.01"),
                model="m",
                provider="p",
            )
        )

        group = DebateGroup(bull_agent=bull, bear_agent=bear, judge_agent=judge)
        result = await group.debate("BTC是否值得买入？")

        assert result["bull_argument"] == "看多理由：趋势向上"
        assert result["bear_argument"] == "看空理由：估值过高"
        assert result["judge_verdict"] == "综合判断：谨慎看多"
        assert bull.run.called
        assert bear.run.called
        assert judge.run.called

    async def test_debate_with_none_responses(self):
        """某一方无响应"""
        bull = MagicMock(spec=BaseAgent)
        bull.run = AsyncMock(return_value=None)
        bear = MagicMock(spec=BaseAgent)
        bear.run = AsyncMock(
            return_value=LLMResponse(
                content="看空",
                tokens_in=10,
                tokens_out=20,
                cost_usd=Decimal("0.01"),
                model="m",
                provider="p",
            )
        )
        judge = MagicMock(spec=BaseAgent)
        judge.run = AsyncMock(return_value=None)

        group = DebateGroup(bull_agent=bull, bear_agent=bear, judge_agent=judge)
        result = await group.debate("BTC")

        assert result["bull_argument"] == ""
        assert result["bear_argument"] == "看空"
        assert result["judge_verdict"] == ""

    async def test_debate_calls_order(self):
        """辩论顺序：先多空，后裁判"""
        call_order = []
        bull = MagicMock(spec=BaseAgent)
        bull.run = AsyncMock(
            side_effect=lambda *a, **kw: (
                call_order.append("bull")
                or LLMResponse(
                    content="bull",
                    tokens_in=10,
                    tokens_out=20,
                    cost_usd=Decimal("0.01"),
                    model="m",
                    provider="p",
                )
            )
        )
        bear = MagicMock(spec=BaseAgent)
        bear.run = AsyncMock(
            side_effect=lambda *a, **kw: (
                call_order.append("bear")
                or LLMResponse(
                    content="bear",
                    tokens_in=10,
                    tokens_out=20,
                    cost_usd=Decimal("0.01"),
                    model="m",
                    provider="p",
                )
            )
        )
        judge = MagicMock(spec=BaseAgent)
        judge.run = AsyncMock(
            side_effect=lambda *a, **kw: (
                call_order.append("judge")
                or LLMResponse(
                    content="judge",
                    tokens_in=10,
                    tokens_out=20,
                    cost_usd=Decimal("0.01"),
                    model="m",
                    provider="p",
                )
            )
        )

        group = DebateGroup(bull_agent=bull, bear_agent=bear, judge_agent=judge)
        await group.debate("test")

        assert call_order[0] == "bull"
        assert call_order[1] == "bear"
        assert call_order[2] == "judge"

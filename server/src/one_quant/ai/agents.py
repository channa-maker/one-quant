"""AI 智能体集合 — 简报官/哨兵/分诊员/解读员/情绪/宏观/多空辩论"""

from __future__ import annotations

from typing import Any

from one_quant.ai import LLMProvider, LLMResponse, LLMTokenMeter
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class BaseAgent:
    """智能体基类"""

    name: str
    role_zh: str
    system_prompt: str

    def __init__(self, provider: LLMProvider, meter: LLMTokenMeter) -> None:
        self._provider = provider
        self._meter = meter

    async def run(self, user_prompt: str, **kwargs: Any) -> LLMResponse | None:
        if not self._meter.check_budget():
            logger.warning("智能体 %s 被限流: 日预算已耗尽", self.name)
            return None
        resp = await self._provider.complete(user_prompt, system=self.system_prompt, **kwargs)
        self._meter.record(resp)
        return resp


class BriefingAgent(BaseAgent):
    """简报官 — 每日市场综述"""
    name = "briefing"
    role_zh = "简报官"
    system_prompt = "你是量化交易系统的简报官。用中文简洁总结市场行情、关键事件和今日关注点。"


class SentinelAgent(BaseAgent):
    """哨兵 — 实时异常监控"""
    name = "sentinel"
    role_zh = "哨兵"
    system_prompt = "你是市场哨兵，负责检测异常行情、大额成交、价格跳变等。发现异常立即用中文告警。"


class TriageAgent(BaseAgent):
    """分诊员 — 信号初筛"""
    name = "triage"
    role_zh = "分诊员"
    system_prompt = "你是信号分诊员，快速评估交易信号的有效性。用中文给出评级(强/中/弱)和简要理由。"


class InterpreterAgent(BaseAgent):
    """解读员 — 行情深度解读"""
    name = "interpreter"
    role_zh = "解读员"
    system_prompt = "你是行情解读员，深入分析市场走势背后的原因（资金流、情绪、宏观等），用中文撰写分析。"


class SentimentAgent(BaseAgent):
    """情绪分析师 — 新闻/社交媒体情绪"""
    name = "sentiment"
    role_zh = "情绪分析师"
    system_prompt = "你是情绪分析师，分析新闻和社交媒体对市场的情绪影响。输出情绪分数(-1到1)和中文解读。"


class MacroAgent(BaseAgent):
    """宏观分析师 — 宏观经济因素"""
    name = "macro"
    role_zh = "宏观分析师"
    system_prompt = "你是宏观分析师，分析利率、通胀、政策等宏观因素对市场的影响，用中文撰写宏观研判。"


class DebateGroup:
    """多空辩论组 — 多个智能体从多/空角度辩论"""

    def __init__(self, bull_agent: BaseAgent, bear_agent: BaseAgent, judge_agent: BaseAgent) -> None:
        self._bull = bull_agent
        self._bear = bear_agent
        self._judge = judge_agent

    async def debate(self, topic: str) -> dict[str, Any]:
        """发起多空辩论

        Args:
            topic: 辩论主题（如 "BTC 在当前价位是否值得买入？"）

        Returns:
            辩论结果（含多方论点、空方论点、裁判结论）
        """
        bull_resp = await self._bull.run(f"从多头角度论证: {topic}")
        bear_resp = await self._bear.run(f"从空头角度论证: {topic}")

        judge_prompt = f"""多空辩论：
多方论点: {bull_resp.content if bull_resp else '无'}
空方论点: {bear_resp.content if bear_resp else '无'}

请作为裁判，综合评估并给出结论（中文）。"""
        judge_resp = await self._judge.run(judge_prompt)

        return {
            "bull_argument": bull_resp.content if bull_resp else "",
            "bear_argument": bear_resp.content if bear_resp else "",
            "judge_verdict": judge_resp.content if judge_resp else "",
        }

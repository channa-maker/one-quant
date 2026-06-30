"""
ONE量化 - 多空辩论组智能体

多头/空头/风控/裁判 多智能体辩论，输出结构化决策。

设计原则：
- 全中文注释和输出
- AI 无否决权：辩论结果仅为建议，必过风控
- 四角色辩论确保多角度思考
- 所有异步方法完整类型标注
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from one_quant.agents.base import BaseAgent
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


# ──────────────────── 辩论角色定义 ────────────────────


class DebateRole:
    """辩论角色常量。"""

    BULL = "bull"  # 多头
    BEAR = "bear"  # 空头
    RISK = "risk"  # 风控
    JUDGE = "judge"  # 裁判


ROLE_ZH: dict[str, str] = {
    DebateRole.BULL: "🐂 多头",
    DebateRole.BEAR: "🐻 空头",
    DebateRole.RISK: "🛡️ 风控",
    DebateRole.JUDGE: "⚖️ 裁判",
}


# ──────────────────── 辩论结果数据类 ────────────────────


@dataclass
class DebateArgument:
    """单个辩论论点。"""

    role: str
    role_zh: str
    argument: str
    confidence: float = 0.0  # 论点信心 0-1
    key_points: list[str] = field(default_factory=list)


@dataclass
class DebateResult:
    """辩论结果。"""

    topic: str
    arguments: list[DebateArgument] = field(default_factory=list)
    verdict: str = ""  # 裁判结论
    verdict_zh: str = ""  # 中文裁判结论
    decision: str = "hold"  # buy/sell/hold
    confidence: float = 0.0  # 决策信心
    risk_warnings: list[str] = field(default_factory=list)
    timestamp_ns: int = 0

    def __post_init__(self) -> None:
        if self.timestamp_ns == 0:
            self.timestamp_ns = time.time_ns()

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "topic": self.topic,
            "arguments": [
                {
                    "role": a.role,
                    "role_zh": a.role_zh,
                    "argument": a.argument,
                    "confidence": a.confidence,
                    "key_points": a.key_points,
                }
                for a in self.arguments
            ],
            "verdict": self.verdict,
            "verdict_zh": self.verdict_zh,
            "decision": self.decision,
            "confidence": self.confidence,
            "risk_warnings": self.risk_warnings,
            "timestamp_ns": self.timestamp_ns,
        }


# ──────────────────── 辩论角色智能体 ────────────────────


class BullAgent(BaseAgent):
    """多头辩论智能体 — 寻找看涨理由。"""

    name = "bull"
    description = "多头辩论角色"

    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """从多头角度论证。

        Args:
            input_data: 包含 topic（辩题）、context（上下文数据）。

        Returns:
            多头论点。
        """
        topic = input_data.get("topic", "")
        context = input_data.get("context", {})

        # 基于数据生成多头论点
        key_points = self._find_bull_points(context)

        argument = f"【多头论证】{topic}\n\n核心观点: 当前具备看涨条件。\n\n论据:\n" + "\n".join(
            f"  {i + 1}. {p}" for i, p in enumerate(key_points)
        )

        return {
            "success": True,
            "agent": self.name,
            "role": DebateRole.BULL,
            "role_zh": ROLE_ZH[DebateRole.BULL],
            "argument": argument,
            "key_points": key_points,
            "confidence": min(len(key_points) * 0.2, 1.0),
        }

    @staticmethod
    def _find_bull_points(context: dict[str, Any]) -> list[str]:
        """从数据中寻找多头论据。

        Args:
            context: 上下文数据。

        Returns:
            多头论据列表。
        """
        points: list[str] = []

        # 技术面
        rsi = context.get("rsi", 50)
        if rsi < 30:
            points.append(f"RSI={rsi:.1f}，处于超卖区域，存在反弹需求")

        macd = context.get("macd_signal", "")
        if macd == "golden_cross":
            points.append("MACD 金叉，短期动能转多")

        # 资金面
        funding_rate = context.get("funding_rate", 0)
        if funding_rate < -0.01:
            points.append(f"资金费率 {funding_rate:.4f} 偏负，空头拥挤，存在轧空风险")

        # 情绪面
        sentiment = context.get("sentiment_score", 0)
        if sentiment < -0.3:
            points.append("市场情绪极度悲观，往往对应底部区域")

        # 基本面
        if context.get("positive_catalyst"):
            points.append(f"存在利好催化剂: {context['positive_catalyst']}")

        if not points:
            points.append("技术面未见明显看涨信号，需进一步观察")

        return points


class BearAgent(BaseAgent):
    """空头辩论智能体 — 寻找看跌理由。"""

    name = "bear"
    description = "空头辩论角色"

    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """从空头角度论证。

        Args:
            input_data: 包含 topic、context。

        Returns:
            空头论点。
        """
        topic = input_data.get("topic", "")
        context = input_data.get("context", {})

        key_points = self._find_bear_points(context)

        argument = f"【空头论证】{topic}\n\n核心观点: 当前存在看跌风险。\n\n论据:\n" + "\n".join(
            f"  {i + 1}. {p}" for i, p in enumerate(key_points)
        )

        return {
            "success": True,
            "agent": self.name,
            "role": DebateRole.BEAR,
            "role_zh": ROLE_ZH[DebateRole.BEAR],
            "argument": argument,
            "key_points": key_points,
            "confidence": min(len(key_points) * 0.2, 1.0),
        }

    @staticmethod
    def _find_bear_points(context: dict[str, Any]) -> list[str]:
        """从数据中寻找空头论据。

        Args:
            context: 上下文数据。

        Returns:
            空头论据列表。
        """
        points: list[str] = []

        rsi = context.get("rsi", 50)
        if rsi > 70:
            points.append(f"RSI={rsi:.1f}，处于超买区域，存在回调风险")

        macd = context.get("macd_signal", "")
        if macd == "death_cross":
            points.append("MACD 死叉，短期动能转空")

        funding_rate = context.get("funding_rate", 0)
        if funding_rate > 0.03:
            points.append(f"资金费率 {funding_rate:.4f} 偏高，多头杠杆过重，存在多杀多风险")

        sentiment = context.get("sentiment_score", 0)
        if sentiment > 0.5:
            points.append("市场情绪过于乐观，往往对应顶部区域")

        if context.get("negative_catalyst"):
            points.append(f"存在利空催化剂: {context['negative_catalyst']}")

        # 宏观风险
        macro_risk = context.get("macro_risk_level", "低")
        if macro_risk in ("高", "中"):
            points.append(f"宏观风险等级: {macro_risk}，外部环境不确定性增加")

        if not points:
            points.append("技术面未见明显看跌信号，需进一步观察")

        return points


class RiskAgent(BaseAgent):
    """风控辩论智能体 — 评估风险。"""

    name = "risk"
    description = "风控辩论角色"

    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """评估风险因素。

        Args:
            input_data: 包含 topic、context。

        Returns:
            风控评估。
        """
        topic = input_data.get("topic", "")
        context = input_data.get("context", {})

        warnings = self._assess_risks(context)

        argument = (
            f"【风控评估】{topic}\n\n"
            f"风险等级: {self._risk_level(warnings)}\n\n"
            f"风险点:\n" + "\n".join(f"  ⚠️ {w}" for w in warnings)
        )

        return {
            "success": True,
            "agent": self.name,
            "role": DebateRole.RISK,
            "role_zh": ROLE_ZH[DebateRole.RISK],
            "argument": argument,
            "key_points": warnings,
            "confidence": 1.0,  # 风控始终充分评估
        }

    @staticmethod
    def _assess_risks(context: dict[str, Any]) -> list[str]:
        """评估风险点。

        Args:
            context: 上下文数据。

        Returns:
            风险警告列表。
        """
        warnings: list[str] = []

        # 仓位风险
        position_size = context.get("position_size_pct", 0)
        if position_size > 20:
            warnings.append(f"仓位过重: {position_size:.1f}%，建议不超过 20%")

        # 杠杆风险
        leverage = context.get("leverage", 1)
        if leverage > 5:
            warnings.append(f"杠杆过高: {leverage}x，建议不超过 5x")

        # 波动率风险
        volatility = context.get("volatility", 0)
        if volatility > 0.05:
            warnings.append(f"波动率偏高: {volatility:.2%}，注意仓位管理")

        # 流动性风险
        volume_24h = context.get("volume_24h", 0)
        if volume_24h > 0 and position_size > 0:
            # 简化检查：仓位是否超过日成交量的一定比例
            position_value = context.get("position_value", 0)
            if position_value > volume_24h * 0.01:
                warnings.append("仓位可能影响市场流动性，建议分批建仓")

        # 相关性风险
        correlation_risk = context.get("correlated_positions", 0)
        if correlation_risk > 3:
            warnings.append(f"关联持仓数: {correlation_risk}，分散度不足")

        # 回撤风险
        current_dd = context.get("current_drawdown", 0)
        if current_dd > 0.1:
            warnings.append(f"当前回撤: {current_dd:.2%}，接近风控阈值")

        if not warnings:
            warnings.append("当前风险可控，未发现显著风险点")

        return warnings

    @staticmethod
    def _risk_level(warnings: list[str]) -> str:
        """判断风险等级。

        Args:
            warnings: 风险警告列表。

        Returns:
            风险等级描述。
        """
        if len(warnings) >= 3:
            return "🔴 高"
        elif len(warnings) >= 2:
            return "🟡 中"
        return "🟢 低"


class JudgeAgent(BaseAgent):
    """裁判智能体 — 综合评估并输出决策。"""

    name = "judge"
    description = "辩论裁判"

    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """综合评估并输出决策。

        Args:
            input_data: 包含 topic、bull_result、bear_result、risk_result。

        Returns:
            裁判结论和决策。
        """
        _topic = input_data.get("topic", "")  # noqa: F841
        bull = input_data.get("bull_result", {})
        bear = input_data.get("bear_result", {})
        risk = input_data.get("risk_result", {})

        bull_points = bull.get("key_points", [])
        bear_points = bear.get("key_points", [])
        risk_points = risk.get("key_points", [])
        bull_conf = bull.get("confidence", 0)
        bear_conf = bear.get("confidence", 0)

        # 裁判评分
        bull_score = len(bull_points) * bull_conf
        bear_score = len(bear_points) * bear_conf

        # 风控否决检查
        has_risk_veto = any(w in str(risk_points) for w in ["仓位过重", "杠杆过高", "接近风控阈值"])

        # 决策
        if has_risk_veto:
            decision = "hold"
            verdict = "风控提示存在显著风险，建议观望"
        elif bull_score > bear_score * 1.5:
            decision = "buy"
            verdict = (
                f"多方论据更充分 (多头{len(bull_points)}条 vs 空头{len(bear_points)}条)，看涨倾向"
            )
        elif bear_score > bull_score * 1.5:
            decision = "sell"
            verdict = (
                f"空方论据更充分 (空头{len(bear_points)}条 vs 多头{len(bull_points)}条)，看跌倾向"
            )
        else:
            decision = "hold"
            verdict = "多空力量均衡，建议观望等待明确信号"

        confidence = abs(bull_score - bear_score) / max(bull_score + bear_score, 1)

        return {
            "success": True,
            "agent": self.name,
            "role": DebateRole.JUDGE,
            "role_zh": ROLE_ZH[DebateRole.JUDGE],
            "verdict": verdict,
            "decision": decision,
            "confidence": round(confidence, 3),
            "bull_score": round(bull_score, 3),
            "bear_score": round(bear_score, 3),
            "risk_warnings": risk_points,
        }


# ──────────────────── 多空辩论组 ────────────────────


class DebateGroup:
    """多空辩论组 — 组织四个角色进行结构化辩论。

    流程：
    1. 多头论证 → 寻找看涨理由
    2. 空头论证 → 寻找看跌理由
    3. 风控评估 → 识别风险点
    4. 裁判总结 → 综合评估并输出决策

    注意：辩论结果仅为 AI 建议，不具有否决权，最终决策必须经过风控系统。
    """

    def __init__(
        self,
        bull: BullAgent | None = None,
        bear: BearAgent | None = None,
        risk: RiskAgent | None = None,
        judge: JudgeAgent | None = None,
    ) -> None:
        """初始化辩论组。

        Args:
            bull: 多头智能体，None 则使用默认。
            bear: 空头智能体，None 则使用默认。
            risk: 风控智能体，None 则使用默认。
            judge: 裁判智能体，None 则使用默认。
        """
        self._bull = bull or BullAgent()
        self._bear = bear or BearAgent()
        self._risk = risk or RiskAgent()
        self._judge = judge or JudgeAgent()

    async def debate(
        self,
        topic: str,
        context: dict[str, Any] | None = None,
    ) -> DebateResult:
        """发起多空辩论。

        Args:
            topic: 辩论主题（如 "BTC 在当前价位是否值得买入？"）。
            context: 上下文数据（技术指标、持仓信息等）。

        Returns:
            辩论结果。
        """
        context = context or {}
        input_data = {"topic": topic, "context": context}

        logger.info("多空辩论开始: %s", topic)

        # 第一轮：多头论证
        bull_result = await self._bull.safe_run(input_data)

        # 第二轮：空头论证
        bear_result = await self._bear.safe_run(input_data)

        # 第三轮：风控评估
        risk_result = await self._risk.safe_run(input_data)

        # 第四轮：裁判总结
        judge_input = {
            **input_data,
            "bull_result": bull_result,
            "bear_result": bear_result,
            "risk_result": risk_result,
        }
        judge_result = await self._judge.safe_run(judge_input)

        # 组装辩论结果
        arguments: list[DebateArgument] = []
        for result in [bull_result, bear_result, risk_result]:
            if result.get("success"):
                arguments.append(
                    DebateArgument(
                        role=result.get("role", ""),
                        role_zh=result.get("role_zh", ""),
                        argument=result.get("argument", ""),
                        confidence=result.get("confidence", 0),
                        key_points=result.get("key_points", []),
                    )
                )

        decision = judge_result.get("decision", "hold")
        verdict = judge_result.get("verdict", "无法得出结论")

        debate_result = DebateResult(
            topic=topic,
            arguments=arguments,
            verdict=verdict,
            verdict_zh=f"⚖️ 裁判结论: {verdict}",
            decision=decision,
            confidence=judge_result.get("confidence", 0),
            risk_warnings=judge_result.get("risk_warnings", []),
        )

        logger.info(
            "多空辩论完成: 决策=%s 信心=%.3f",
            decision,
            debate_result.confidence,
        )

        return debate_result

    async def debate_and_report(
        self,
        topic: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """辩论并生成中文报告。

        Args:
            topic: 辩论主题。
            context: 上下文数据。

        Returns:
            包含报告和结构化数据的字典。
        """
        result = await self.debate(topic, context)

        # 生成中文报告
        lines: list[str] = ["## 🎯 多空辩论报告\n"]
        lines.append(f"**辩题**: {topic}\n")

        # 各方论点
        for arg in result.arguments:
            lines.append(f"### {arg.role_zh}")
            lines.append(arg.argument)
            lines.append("")

        # 裁判结论
        lines.append("### ⚖️ 裁判结论")
        lines.append(result.verdict_zh)
        lines.append(f"**决策**: {result.decision.upper()}")
        lines.append(f"**信心**: {result.confidence:.1%}")

        # 风险提示
        if result.risk_warnings:
            lines.append("\n### ⚠️ 风险提示")
            for w in result.risk_warnings:
                lines.append(f"- {w}")

        # 免责声明
        lines.append("\n---")
        lines.append("*⚠️ 以上分析仅为 AI 建议，不具有否决权。最终交易决策必须经过风控系统审核。*")

        report = "\n".join(lines)

        return {
            "success": True,
            "report": report,
            "result": result.to_dict(),
            "decision": result.decision,
            "confidence": result.confidence,
        }

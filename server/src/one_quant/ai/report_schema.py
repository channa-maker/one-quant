"""
B-6 决策报告中文 schema

AI 研报 + 信号卡的结构化定义，包含：
- 核心结论 / 评分 / 趋势 / 买卖点位 / 风险警报 / 催化因素 / 操作检查清单

所有字段中文注释，Pydantic v2 校验。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# ──────────────────── 评分卡 ────────────────────


class ScoreCard(BaseModel, frozen=True):
    """多维度评分卡，各维度 0-10 分。

    Attributes:
        technical: 技术面评分。
        fundamental: 基本面评分。
        sentiment: 情绪面评分。
        risk_reward: 风险收益比评分。
        overall: 综合评分。
    """

    technical: Decimal = Field(description="技术面评分 0-10")
    fundamental: Decimal = Field(description="基本面评分 0-10")
    sentiment: Decimal = Field(description="情绪面评分 0-10")
    risk_reward: Decimal = Field(description="风险收益比评分 0-10")
    overall: Decimal = Field(description="综合评分 0-10")

    @field_validator("technical", "fundamental", "sentiment", "risk_reward", "overall")
    @classmethod
    def validate_score_range(cls, v: Decimal) -> Decimal:
        """校验分数在 0-10 范围内。"""
        if v < 0 or v > 10:
            raise ValueError(f"评分必须在 0-10 之间，当前值: {v}")
        return v


# ──────────────────── 趋势分析 ────────────────────


class TrendAnalysis(BaseModel, frozen=True):
    """趋势分析。

    Attributes:
        direction: 趋势方向（bullish/bearish/neutral）。
        timeframe: 分析周期（如 "1h", "4h", "1d"）。
        confidence: 置信度 0-1。
        description: 趋势描述（中文）。
    """

    direction: Literal["bullish", "bearish", "neutral"] = Field(description="趋势方向")
    timeframe: str = Field(description="分析周期")
    confidence: Decimal = Field(description="置信度 0-1")
    description: str = Field(description="趋势描述")

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: Decimal) -> Decimal:
        """校验置信度在 0-1 范围内。"""
        if v < 0 or v > 1:
            raise ValueError(f"置信度必须在 0-1 之间，当前值: {v}")
        return v


# ──────────────────── 买卖点位 ────────────────────


class BuySellPoint(BaseModel, frozen=True):
    """买卖点位。

    Attributes:
        price: 目标价格。
        point_type: 点位类型（buy/sell/stop_loss/take_profit）。
        reason: 点位理由（中文）。
        stop_loss: 止损价（可选）。
        take_profit: 止盈价（可选）。
    """

    price: Decimal = Field(description="目标价格")
    point_type: Literal["buy", "sell", "stop_loss", "take_profit"] = Field(description="点位类型")
    reason: str = Field(description="点位理由")
    stop_loss: Decimal | None = Field(default=None, description="止损价")
    take_profit: Decimal | None = Field(default=None, description="止盈价")


# ──────────────────── 风险警报 ────────────────────


class RiskAlert(BaseModel, frozen=True):
    """风险警报。

    Attributes:
        level: 风险等级（low/medium/high/critical）。
        description: 风险描述（中文）。
        mitigation: 应对措施（中文）。
    """

    level: Literal["low", "medium", "high", "critical"] = Field(description="风险等级")
    description: str = Field(description="风险描述")
    mitigation: str = Field(description="应对措施")


# ──────────────────── 催化因素 ────────────────────


class CatalystFactor(BaseModel, frozen=True):
    """催化因素。

    Attributes:
        type: 因素类型（positive/negative/neutral）。
        description: 因素描述（中文）。
        time_window: 时间窗口（如 "1-2周"）。
        impact: 影响程度（low/medium/high）。
    """

    type: Literal["positive", "negative", "neutral"] = Field(description="因素类型")
    description: str = Field(description="因素描述")
    time_window: str = Field(description="时间窗口")
    impact: Literal["low", "medium", "high"] = Field(description="影响程度")


# ──────────────────── 操作检查清单 ────────────────────


class ActionChecklist(BaseModel, frozen=True):
    """操作检查清单。

    Attributes:
        items: 待办事项列表，每项包含 action（操作描述）和 done（是否完成）。
    """

    items: list[dict[str, Any]] = Field(description="待办事项列表")

    @field_validator("items")
    @classmethod
    def validate_items(cls, v: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """校验每项包含必要字段。"""
        for item in v:
            if "action" not in item:
                raise ValueError("检查清单每项必须包含 'action' 字段")
            if "done" not in item:
                item["done"] = False
        return v


# ──────────────────── 信号卡 ────────────────────


class SignalCard(BaseModel, frozen=True):
    """交易信号卡 — 单个信号的结构化表示。

    Attributes:
        symbol: 标的符号。
        action: 操作建议（buy/sell/hold）。
        confidence: 信心度 0-1。
        entry_price: 建议入场价。
        stop_loss: 止损价（可选）。
        take_profit: 止盈价（可选）。
        reason: 信号理由（中文）。
        risk_level: 风险等级。
    """

    symbol: str = Field(description="标的符号")
    action: Literal["buy", "sell", "hold"] = Field(description="操作建议")
    confidence: Decimal = Field(description="信心度 0-1")
    entry_price: Decimal = Field(description="建议入场价")
    stop_loss: Decimal | None = Field(default=None, description="止损价")
    take_profit: Decimal | None = Field(default=None, description="止盈价")
    reason: str = Field(description="信号理由")
    risk_level: Literal["low", "medium", "high"] = Field(description="风险等级")

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: Decimal) -> Decimal:
        if v < 0 or v > 1:
            raise ValueError(f"信心度必须在 0-1 之间，当前值: {v}")
        return v


# ──────────────────── 完整决策报告 ────────────────────


class DecisionReport(BaseModel, frozen=True):
    """AI 决策报告 — 完整研报结构。

    包含核心结论、评分卡、趋势分析、买卖点位、风险警报、催化因素、操作清单。

    Attributes:
        title: 报告标题。
        symbol: 标的符号。
        market: 所属市场。
        generated_at: 生成时间。
        core_conclusion: 核心结论（中文，1-3 句话）。
        score_card: 多维度评分卡。
        trends: 趋势分析列表（多周期）。
        buy_sell_points: 买卖点位列表。
        risk_alerts: 风险警报列表。
        catalysts: 催化因素列表。
        checklist: 操作检查清单。
        metadata: 附加元数据。
    """

    title: str = Field(description="报告标题")
    symbol: str = Field(description="标的符号")
    market: str = Field(description="所属市场")
    generated_at: datetime = Field(description="生成时间")
    core_conclusion: str = Field(description="核心结论")

    score_card: ScoreCard = Field(description="多维度评分卡")
    trends: list[TrendAnalysis] = Field(description="趋势分析列表")
    buy_sell_points: list[BuySellPoint] = Field(description="买卖点位列表")
    risk_alerts: list[RiskAlert] = Field(description="风险警报列表")
    catalysts: list[CatalystFactor] = Field(description="催化因素列表")
    checklist: ActionChecklist = Field(description="操作检查清单")

    metadata: dict[str, Any] = Field(default_factory=dict, description="附加元数据")


# ──────────────────── 报告生成工具函数 ────────────────────


def generate_report_from_signal(signal_data: dict[str, Any]) -> DecisionReport:
    """从交易信号数据生成报告骨架。

    根据信号的基础信息，自动生成包含默认值的完整报告结构。
    后续可由 AI 填充详细分析内容。

    Args:
        signal_data: 信号数据字典，包含 symbol, side, strength, reason, metadata 等。

    Returns:
        DecisionReport 完整报告对象。
    """
    symbol = signal_data.get("symbol", "UNKNOWN")
    side = signal_data.get("side", "hold")
    strength = Decimal(str(signal_data.get("strength", 0.5)))
    reason = signal_data.get("reason", "")
    metadata = signal_data.get("metadata", {})

    entry_price = Decimal(str(metadata.get("entry_price", "0")))
    stop_loss = Decimal(str(metadata.get("stop_loss", "0"))) if metadata.get("stop_loss") else None
    take_profit = (
        Decimal(str(metadata.get("take_profit", "0"))) if metadata.get("take_profit") else None
    )

    # 根据信号强度映射评分
    score_value = strength * 10

    # 根据信号方向确定趋势
    direction_map = {"buy": "bullish", "sell": "bearish", "hold": "neutral"}
    direction = direction_map.get(side, "neutral")

    return DecisionReport(
        title=f"{symbol} 信号分析报告",
        symbol=symbol,
        market="SPOT",
        generated_at=datetime.now(),
        core_conclusion=reason or f"信号方向: {side}，强度: {strength}",
        score_card=ScoreCard(
            technical=score_value,
            fundamental=Decimal("5.0"),
            sentiment=Decimal("5.0"),
            risk_reward=score_value,
            overall=score_value,
        ),
        trends=[
            TrendAnalysis(
                direction=direction
                if direction in ("bullish", "bearish", "neutral")
                else "neutral",  # type: ignore[arg-type]
                timeframe="1h",
                confidence=strength,
                description=reason or f"{direction} 趋势",
            ),
        ],
        buy_sell_points=[
            BuySellPoint(
                price=entry_price,
                point_type=side if side in ("buy", "sell") else "buy",
                reason=reason,
                stop_loss=stop_loss,
                take_profit=take_profit,
            ),
        ]
        if entry_price > 0
        else [],
        risk_alerts=[
            RiskAlert(
                level="medium",
                description="自动生成报告，需人工复核",
                mitigation="请结合实际情况调整参数",
            ),
        ],
        catalysts=[],
        checklist=ActionChecklist(
            items=[
                {"action": "确认信号有效性", "done": False},
                {"action": "设置止损止盈", "done": False},
                {"action": "执行交易", "done": False},
            ]
        ),
        metadata={"strategy_name": signal_data.get("strategy_name", ""), "raw_signal": signal_data},
    )

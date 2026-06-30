"""PhaseGuardrail — 市场阶段感知护栏

在信号产出前根据市场阶段（盘前/日内/午休/收盘竞价/非交易等）对信号进行
置信度调整或抑制。仅调整置信/抑制信号，不替代四层风控。

核心规则：
- 非交易/盘前/unknown 阶段 → 强制保守（抑制或大幅降置信）
- 使用未收盘 is_partial_bar → 警告 + 降置信
- 核心数据块缺失 → 降级
- 加密按"资金费率结算时点/低流动性时段"套用同框架
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

from one_quant.ai.signal_scoring import SignalCard, classify_signal
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


# ──────────────────────────── 枚举与数据结构 ────────────────────────────


class MarketPhase(StrEnum):
    """市场阶段枚举"""

    PREMARKET = "premarket"
    INTRADAY = "intraday"
    LUNCH_BREAK = "lunch_break"
    CLOSING_AUCTION = "closing_auction"
    NON_TRADING = "non_trading"
    UNKNOWN = "unknown"


class GuardrailAction(StrEnum):
    """护栏动作"""

    PASS = "pass"  # 通过，不修改
    DEGRADE = "degrade"  # 降级，降低置信
    SUPPRESS = "suppress"  # 抑制，大幅降置信或直接过滤


@dataclass
class GuardrailResult:
    """护栏处理结果"""

    action: GuardrailAction
    adjusted_card: SignalCard
    warnings: list[str]
    reason: str


# ──────────────────────────── 降级系数配置 ────────────────────────────

# 阶段降级系数：score *= factor
_PHASE_DEGRADE_FACTOR: dict[str, float] = {
    MarketPhase.INTRADAY: 1.0,  # 正常交易不降级
    MarketPhase.LUNCH_BREAK: 0.85,  # 午休适度降级
    MarketPhase.CLOSING_AUCTION: 0.80,  # 收盘竞价降级
    MarketPhase.PREMARKET: 0.50,  # 盘前大幅降级
    MarketPhase.NON_TRADING: 0.40,  # 非交易严重降级
    MarketPhase.UNKNOWN: 0.45,  # unknown 严重降级
}

# 抑制阈值：adjusted_score < 此值 → SUPPRESS
_SUPPRESS_THRESHOLD: float = 45.0

# partial bar 降级系数
_PARTIAL_BAR_FACTOR: float = 0.75

# 数据块缺失降级系数（每缺一块）
_DATA_MISSING_FACTOR: float = 0.80

# 加密特殊场景降级系数
_CRYPTO_FUNDING_SETTLEMENT_FACTOR: float = 0.75
_CRYPTO_LOW_LIQUIDITY_FACTOR: float = 0.80


# ──────────────────────────── PhaseGuardrail ────────────────────────────


class PhaseGuardrail:
    """市场阶段感知护栏

    在信号产出前调用，根据市场阶段对信号置信度进行调整或抑制。
    不替代四层风控，仅做置信度层面的护栏。

    用法：
        guardrail = PhaseGuardrail()
        result = guardrail.apply(signal_card, market_context)
        if result.action == GuardrailAction.SUPPRESS:
            # 信号被抑制，不推送
            ...
        elif result.action == GuardrailAction.DEGRADE:
            # 信号降级，使用 result.adjusted_card
            ...
    """

    def apply(self, card: SignalCard, context: dict[str, Any]) -> GuardrailResult:
        """应用护栏规则

        Args:
            card: 原始信号卡
            context: 市场上下文，包含：
                - phase: 市场阶段
                  (premarket/intraday/lunch_break/
                  closing_auction/non_trading/unknown)
                - is_trading_day: 是否交易日
                - is_market_open_now: 当前是否开盘
                - is_partial_bar: 是否使用未收盘K线
                - minutes_to_open: 距开盘分钟数
                - minutes_to_close: 距收盘分钟数
                - effective_bar_date: K线生效日期
                - has_quote: 行情数据是否齐全
                - has_bars: K线数据是否齐全
                - has_technical: 技术指标是否齐全
                - is_crypto: 是否加密市场
                - funding_rate_settlement: 是否资金费率结算时点
                - low_liquidity: 是否低流动性时段

        Returns:
            GuardrailResult 包含动作、调整后信号卡、警告列表和理由
        """
        warnings: list[str] = []
        factors: list[float] = []  # 累积降级因子
        reasons: list[str] = []

        phase = context.get("phase", "unknown")
        is_partial_bar = context.get("is_partial_bar", False)
        has_quote = context.get("has_quote", True)
        has_bars = context.get("has_bars", True)
        has_technical = context.get("has_technical", True)
        is_crypto = context.get("is_crypto", False)
        funding_rate_settlement = context.get("funding_rate_settlement", False)
        low_liquidity = context.get("low_liquidity", False)

        # ① 阶段降级
        phase_factor = _PHASE_DEGRADE_FACTOR.get(phase, 0.45)
        if phase_factor < 1.0:
            factors.append(phase_factor)
            reasons.append(f"市场阶段 {phase} 降级 (×{phase_factor:.2f})")

            if phase in (MarketPhase.PREMARKET, MarketPhase.NON_TRADING, MarketPhase.UNKNOWN):
                warnings.append(f"⚠️ 市场阶段 [{phase}]，信号强制保守处理")

        # ② Partial bar 降级
        if is_partial_bar:
            factors.append(_PARTIAL_BAR_FACTOR)
            warnings.append("⚠️ 使用未收盘K线（partial bar），置信度下调")
            reasons.append(f"未收盘K线降级 (×{_PARTIAL_BAR_FACTOR:.2f})")

        # ③ 核心数据块缺失降级
        missing_blocks: list[str] = []
        if not has_quote:
            missing_blocks.append("quote")
        if not has_bars:
            missing_blocks.append("bars")
        if not has_technical:
            missing_blocks.append("technical")

        if missing_blocks:
            # 每缺一块乘一次降级系数
            data_factor = _DATA_MISSING_FACTOR ** len(missing_blocks)
            factors.append(data_factor)
            warnings.append(f"⚠️ 核心数据块缺失: {', '.join(missing_blocks)}")
            reasons.append(f"数据缺失降级 {missing_blocks} (×{data_factor:.2f})")

        # ④ 加密特殊场景
        if is_crypto and funding_rate_settlement:
            factors.append(_CRYPTO_FUNDING_SETTLEMENT_FACTOR)
            warnings.append("⚠️ 资金费率结算时点，信号降级")
            reasons.append(f"资金费率结算降级 (×{_CRYPTO_FUNDING_SETTLEMENT_FACTOR:.2f})")

        if is_crypto and low_liquidity:
            factors.append(_CRYPTO_LOW_LIQUIDITY_FACTOR)
            warnings.append("⚠️ 低流动性时段，信号降级")
            reasons.append(f"低流动性降级 (×{_CRYPTO_LOW_LIQUIDITY_FACTOR:.2f})")

        # ⑤ 计算最终降级因子（取所有因子的乘积）
        combined_factor = 1.0
        for f in factors:
            combined_factor *= f

        # ⑥ 应用降级
        adjusted_score = max(0.0, min(card.score, card.score * combined_factor))

        # ⑦ 判定动作
        if adjusted_score < _SUPPRESS_THRESHOLD:
            action = GuardrailAction.SUPPRESS
        elif combined_factor < 1.0:
            action = GuardrailAction.DEGRADE
        else:
            action = GuardrailAction.PASS

        # ⑧ 重新计算等级
        new_level = classify_signal(adjusted_score)

        # ⑨ 调整置信区间
        ci_half_width = (card.confidence_interval[1] - card.confidence_interval[0]) / 2
        # 降级后不确定性增大
        new_ci_half = ci_half_width / combined_factor if combined_factor < 1.0 else ci_half_width
        new_ci_half = min(new_ci_half, 25.0)  # 上限
        new_confidence_interval = (
            max(0.0, adjusted_score - new_ci_half),
            min(100.0, adjusted_score + new_ci_half),
        )

        # ⑩ 构建调整后的信号卡（不修改方向/止损/风险回报比 — 这些由四层风控管理）
        adjusted_card = replace(
            card,
            score=round(adjusted_score, 2),
            confidence_interval=(
                round(new_confidence_interval[0], 2),
                round(new_confidence_interval[1], 2),
            ),
            level=new_level,
            risk_note=self._merge_risk_note(card.risk_note, warnings),
            historical_win_rate=adjusted_score / 100.0,
        )

        # ⑪ 生成理由
        if not reasons:
            reason = "市场阶段正常，信号通过"
        else:
            reason = "护栏调整: " + "; ".join(reasons)

        logger.info(
            "PhaseGuardrail: %s %s → %s (score: %.1f → %.1f, factor: %.2f)",
            card.symbol,
            action.value,
            card.direction,
            card.score,
            adjusted_score,
            combined_factor,
        )

        return GuardrailResult(
            action=action,
            adjusted_card=adjusted_card,
            warnings=warnings,
            reason=reason,
        )

    @staticmethod
    def _merge_risk_note(original: str, warnings: list[str]) -> str:
        """合并风险提示"""
        parts = [original] if original else []
        # 只取护栏相关警告（去重）
        seen = set()
        for w in warnings:
            w_clean = w.replace("⚠️ ", "")
            if w_clean not in seen:
                seen.add(w_clean)
                parts.append(w_clean)
        return "；".join(parts)

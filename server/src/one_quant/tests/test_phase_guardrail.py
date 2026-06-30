"""PhaseGuardrail 市场阶段感知护栏 — 单测

测试场景：
1. 非交易/盘前/unknown 阶段 → 强制保守（抑制或大幅降置信）
2. 用了未收盘 is_partial_bar → 警告 + 降置信
3. 核心数据块缺失 → 降级
4. 正常交易时段不降级
5. 加密市场资金费率结算时点/低流动性时段套用同框架
6. 不影响四层风控路径
"""

from __future__ import annotations

from decimal import Decimal

from one_quant.ai.phase_guardrail import (
    GuardrailAction,
    PhaseGuardrail,
)
from one_quant.ai.signal_scoring import SignalCard

# ──────────────────────────── Fixtures ────────────────────────────


def _make_signal_card(
    score: float = 80.0,
    level: str = "A",
    direction: str = "long",
) -> SignalCard:
    """构造测试用信号卡"""
    return SignalCard(
        signal_id="sig_TEST_1234567890",
        symbol="BTCUSDT",
        direction=direction,
        score=score,
        confidence_interval=(score - 10, score + 10),
        level=level,
        time_horizon="日内",
        risk_note="测试风险提示",
        suggested_stop=Decimal("0"),
        risk_reward_ratio=2.5,
        reason="测试理由",
        evidence_details={"order_flow": 0.3, "smc": 0.2},
        historical_win_rate=0.75,
        timestamp_ns=1_700_000_000_000_000_000,
    )


def _make_context(
    phase: str = "intraday",
    is_trading_day: bool = True,
    is_market_open_now: bool = True,
    is_partial_bar: bool = False,
    minutes_to_open: float = 0.0,
    minutes_to_close: float = 120.0,
    effective_bar_date: str = "2026-06-30",
    has_quote: bool = True,
    has_bars: bool = True,
    has_technical: bool = True,
    is_crypto: bool = False,
    funding_rate_settlement: bool = False,
    low_liquidity: bool = False,
) -> dict:
    """构造市场上下文"""
    return {
        "phase": phase,
        "is_trading_day": is_trading_day,
        "is_market_open_now": is_market_open_now,
        "is_partial_bar": is_partial_bar,
        "minutes_to_open": minutes_to_open,
        "minutes_to_close": minutes_to_close,
        "effective_bar_date": effective_bar_date,
        "has_quote": has_quote,
        "has_bars": has_bars,
        "has_technical": has_technical,
        "is_crypto": is_crypto,
        "funding_rate_settlement": funding_rate_settlement,
        "low_liquidity": low_liquidity,
    }


# ──────────────────────────── 正常交易时段不降级 ────────────────────────────


class TestNormalTrading:
    """正常交易时段（intraday, 数据齐全, 非 partial bar）→ 不降级"""

    def test_intraday_no_degrade(self):
        """日内正常交易 → 信号不变"""
        guardrail = PhaseGuardrail()
        card = _make_signal_card(score=80.0, level="A")
        ctx = _make_context()

        result = guardrail.apply(card, ctx)

        assert result.action == GuardrailAction.PASS
        assert result.adjusted_card.score == 80.0
        assert result.adjusted_card.level == "A"
        assert not result.warnings

    def test_intraday_high_score_preserved(self):
        """日内高分信号 → 完全保留"""
        guardrail = PhaseGuardrail()
        card = _make_signal_card(score=92.0, level="S")
        ctx = _make_context()

        result = guardrail.apply(card, ctx)

        assert result.action == GuardrailAction.PASS
        assert result.adjusted_card.score == 92.0
        assert result.adjusted_card.level == "S"


# ──────────────────────────── 盘前场景 ────────────────────────────


class TestPremarket:
    """盘前阶段 → 强制保守（降置信或抑制）"""

    def test_premarket_suppress_signal(self):
        """盘前信号 → 抑制"""
        guardrail = PhaseGuardrail()
        card = _make_signal_card(score=80.0, level="A")
        ctx = _make_context(
            phase="premarket",
            is_market_open_now=False,
            minutes_to_open=30.0,
        )

        result = guardrail.apply(card, ctx)

        assert result.action == GuardrailAction.SUPPRESS
        assert result.adjusted_card.score < card.score

    def test_premarket_with_partial_bar_suppress(self):
        """盘前 + 部分K线 → 更严厉的抑制"""
        guardrail = PhaseGuardrail()
        card = _make_signal_card(score=80.0, level="A")
        ctx = _make_context(
            phase="premarket",
            is_market_open_now=False,
            is_partial_bar=True,
            minutes_to_open=30.0,
        )

        result = guardrail.apply(card, ctx)

        assert result.action == GuardrailAction.SUPPRESS
        assert result.adjusted_card.score < 50  # 大幅降置信


# ──────────────────────────── 非交易时段 ────────────────────────────


class TestNonTrading:
    """非交易日/非交易时段 → 强制保守"""

    def test_non_trading_day_suppress(self):
        """非交易日 → 抑制"""
        guardrail = PhaseGuardrail()
        card = _make_signal_card(score=80.0, level="A")
        ctx = _make_context(
            phase="non_trading",
            is_trading_day=False,
            is_market_open_now=False,
        )

        result = guardrail.apply(card, ctx)

        assert result.action == GuardrailAction.SUPPRESS
        assert result.adjusted_card.score < card.score

    def test_unknown_phase_degrade(self):
        """unknown 阶段 → 降级"""
        guardrail = PhaseGuardrail()
        card = _make_signal_card(score=80.0, level="A")
        ctx = _make_context(
            phase="unknown",
            is_market_open_now=False,
        )

        result = guardrail.apply(card, ctx)

        assert result.action in (GuardrailAction.DEGRADE, GuardrailAction.SUPPRESS)
        assert result.adjusted_card.score < card.score


# ──────────────────────────── 午休/收盘竞价 ────────────────────────────


class TestLunchBreakAndClosing:
    """午休和收盘竞价 → 适度降级"""

    def test_lunch_break_degrade(self):
        """午休时段 → 适度降级"""
        guardrail = PhaseGuardrail()
        card = _make_signal_card(score=80.0, level="A")
        ctx = _make_context(
            phase="lunch_break",
            is_market_open_now=True,
        )

        result = guardrail.apply(card, ctx)

        assert result.action == GuardrailAction.DEGRADE
        assert result.adjusted_card.score < card.score
        assert result.adjusted_card.score > 50  # 不会过度打压

    def test_closing_auction_degrade(self):
        """收盘竞价 → 适度降级"""
        guardrail = PhaseGuardrail()
        card = _make_signal_card(score=80.0, level="A")
        ctx = _make_context(
            phase="closing_auction",
            is_market_open_now=True,
            minutes_to_close=5.0,
        )

        result = guardrail.apply(card, ctx)

        assert result.action == GuardrailAction.DEGRADE
        assert result.adjusted_card.score < card.score


# ──────────────────────────── Partial Bar ────────────────────────────


class TestPartialBar:
    """使用未收盘 K 线 → 警告 + 降置信"""

    def test_partial_bar_degrade_and_warn(self):
        """部分K线 → 降级 + 警告"""
        guardrail = PhaseGuardrail()
        card = _make_signal_card(score=80.0, level="A")
        ctx = _make_context(
            phase="intraday",
            is_partial_bar=True,
        )

        result = guardrail.apply(card, ctx)

        assert result.action == GuardrailAction.DEGRADE
        assert result.adjusted_card.score < card.score
        assert any("partial" in w.lower() or "未收盘" in w or "部分" in w for w in result.warnings)


# ──────────────────────────── 核心数据块缺失 ────────────────────────────


class TestMissingData:
    """核心数据块缺失 → 降级"""

    def test_missing_quote_degrade(self):
        """缺少行情数据 → 降级"""
        guardrail = PhaseGuardrail()
        card = _make_signal_card(score=80.0, level="A")
        ctx = _make_context(has_quote=False)

        result = guardrail.apply(card, ctx)

        assert result.action == GuardrailAction.DEGRADE
        assert result.adjusted_card.score < card.score

    def test_missing_bars_degrade(self):
        """缺少K线数据 → 降级"""
        guardrail = PhaseGuardrail()
        card = _make_signal_card(score=80.0, level="A")
        ctx = _make_context(has_bars=False)

        result = guardrail.apply(card, ctx)

        assert result.action == GuardrailAction.DEGRADE
        assert result.adjusted_card.score < card.score

    def test_missing_technical_degrade(self):
        """缺少技术指标 → 降级"""
        guardrail = PhaseGuardrail()
        card = _make_signal_card(score=80.0, level="A")
        ctx = _make_context(has_technical=False)

        result = guardrail.apply(card, ctx)

        assert result.action == GuardrailAction.DEGRADE
        assert result.adjusted_card.score < card.score

    def test_all_data_missing_severe_degrade(self):
        """所有核心数据缺失 → 严重降级"""
        guardrail = PhaseGuardrail()
        card = _make_signal_card(score=80.0, level="A")
        ctx = _make_context(has_quote=False, has_bars=False, has_technical=False)

        result = guardrail.apply(card, ctx)

        assert result.action == GuardrailAction.SUPPRESS
        assert result.adjusted_card.score < 50  # 0.80^3 * 80 ≈ 41，严重降级


# ──────────────────────────── 加密市场特殊场景 ────────────────────────────


class TestCryptoSpecialCases:
    """加密市场资金费率结算/低流动性 → 套用同框架"""

    def test_funding_rate_settlement_degrade(self):
        """资金费率结算时点 → 降级"""
        guardrail = PhaseGuardrail()
        card = _make_signal_card(score=80.0, level="A")
        ctx = _make_context(
            phase="intraday",
            is_crypto=True,
            funding_rate_settlement=True,
        )

        result = guardrail.apply(card, ctx)

        assert result.action == GuardrailAction.DEGRADE
        assert result.adjusted_card.score < card.score

    def test_low_liquidity_degrade(self):
        """低流动性时段 → 降级"""
        guardrail = PhaseGuardrail()
        card = _make_signal_card(score=80.0, level="A")
        ctx = _make_context(
            phase="intraday",
            is_crypto=True,
            low_liquidity=True,
        )

        result = guardrail.apply(card, ctx)

        assert result.action == GuardrailAction.DEGRADE
        assert result.adjusted_card.score < card.score


# ──────────────────────────── 组合场景 ────────────────────────────


class TestCombinedScenarios:
    """多因素叠加 → 取最严策略"""

    def test_premarket_plus_missing_data_plus_partial_bar(self):
        """盘前 + 数据缺失 + 部分K线 → 严重抑制"""
        guardrail = PhaseGuardrail()
        card = _make_signal_card(score=90.0, level="S")
        ctx = _make_context(
            phase="premarket",
            is_market_open_now=False,
            is_partial_bar=True,
            has_technical=False,
            minutes_to_open=15.0,
        )

        result = guardrail.apply(card, ctx)

        assert result.action == GuardrailAction.SUPPRESS
        assert result.adjusted_card.score < 40
        assert len(result.warnings) >= 2  # 多条警告

    def test_normal_with_minor_data_gap(self):
        """正常交易 + 仅技术指标缺失 → 轻度降级"""
        guardrail = PhaseGuardrail()
        card = _make_signal_card(score=80.0, level="A")
        ctx = _make_context(has_technical=False)

        result = guardrail.apply(card, ctx)

        assert result.action == GuardrailAction.DEGRADE
        # 轻度降级，分数仍在合理范围
        assert 60 < result.adjusted_card.score < 80


# ──────────────────────────── 四层风控路径不受影响 ────────────────────────────


class TestRiskControlPathUnaffected:
    """PhaseGuardrail 不替代四层风控"""

    def test_guardrail_does_not_touch_stop_loss(self):
        """护栏不修改止损价"""
        guardrail = PhaseGuardrail()
        card = _make_signal_card(score=80.0, level="A")
        ctx = _make_context(phase="premarket", is_market_open_now=False)

        result = guardrail.apply(card, ctx)

        # 止损价由四层风控设定，护栏不应修改
        assert result.adjusted_card.suggested_stop == card.suggested_stop

    def test_guardrail_does_not_change_direction(self):
        """护栏不改变信号方向"""
        guardrail = PhaseGuardrail()
        card = _make_signal_card(score=80.0, level="A", direction="long")
        ctx = _make_context(phase="premarket", is_market_open_now=False)

        result = guardrail.apply(card, ctx)

        assert result.adjusted_card.direction == "long"

    def test_guardrail_does_not_change_risk_reward(self):
        """护栏不修改风险回报比"""
        guardrail = PhaseGuardrail()
        card = _make_signal_card(score=80.0, level="A")
        original_rr = card.risk_reward_ratio
        ctx = _make_context(phase="lunch_break")

        result = guardrail.apply(card, ctx)

        assert result.adjusted_card.risk_reward_ratio == original_rr


# ──────────────────────────── GuardrailResult 结构 ────────────────────────────


class TestGuardrailResult:
    """GuardrailResult 数据结构"""

    def test_result_has_action(self):
        """结果包含动作"""
        guardrail = PhaseGuardrail()
        card = _make_signal_card()
        ctx = _make_context()

        result = guardrail.apply(card, ctx)

        assert isinstance(result.action, GuardrailAction)

    def test_result_has_adjusted_card(self):
        """结果包含调整后的信号卡"""
        guardrail = PhaseGuardrail()
        card = _make_signal_card()
        ctx = _make_context()

        result = guardrail.apply(card, ctx)

        assert isinstance(result.adjusted_card, SignalCard)

    def test_result_has_warnings_list(self):
        """结果包含警告列表"""
        guardrail = PhaseGuardrail()
        card = _make_signal_card()
        ctx = _make_context()

        result = guardrail.apply(card, ctx)

        assert isinstance(result.warnings, list)

    def test_result_has_reason(self):
        """结果包含中文理由"""
        guardrail = PhaseGuardrail()
        card = _make_signal_card()
        ctx = _make_context()

        result = guardrail.apply(card, ctx)

        assert isinstance(result.reason, str)
        assert len(result.reason) > 0


# ──────────────────────────── 分数边界 ────────────────────────────


class TestScoreBoundaries:
    """分数边界测试"""

    def test_degraded_score_never_negative(self):
        """降级后分数不低于 0"""
        guardrail = PhaseGuardrail()
        card = _make_signal_card(score=5.0, level="C")
        ctx = _make_context(
            phase="non_trading",
            is_trading_day=False,
            is_market_open_now=False,
        )

        result = guardrail.apply(card, ctx)

        assert result.adjusted_card.score >= 0.0

    def test_degraded_score_never_exceeds_original(self):
        """降级后分数不高于原始分数"""
        guardrail = PhaseGuardrail()
        card = _make_signal_card(score=50.0, level="B")
        ctx = _make_context(
            phase="premarket",
            is_market_open_now=False,
        )

        result = guardrail.apply(card, ctx)

        assert result.adjusted_card.score <= card.score

    def test_level_recalculated_after_score_change(self):
        """分数变化后等级重新计算"""
        guardrail = PhaseGuardrail()
        card = _make_signal_card(score=85.0, level="S")
        ctx = _make_context(
            phase="premarket",
            is_market_open_now=False,
        )

        result = guardrail.apply(card, ctx)

        # 分数大幅下降后，等级应该不再是 S
        if result.adjusted_card.score < 70:
            assert result.adjusted_card.level != "S"

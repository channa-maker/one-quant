"""B-6 决策报告中文 schema 测试

测试场景：
1. AI 研报结构完整性
2. 信号卡结构完整性
3. 各字段类型/范围校验
4. 报告序列化/反序列化
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from one_quant.ai.report_schema import (
    ActionChecklist,
    BuySellPoint,
    CatalystFactor,
    DecisionReport,
    RiskAlert,
    ScoreCard,
    SignalCard,
    TrendAnalysis,
    generate_report_from_signal,
)

# ──────────────────── 测试: ScoreCard 评分卡 ────────────────────


class TestScoreCard:
    """测试评分卡结构。"""

    def test_score_card_basic(self):
        """评分卡应包含各维度分数和综合分。"""
        score = ScoreCard(
            technical=Decimal("8.5"),
            fundamental=Decimal("7.0"),
            sentiment=Decimal("6.5"),
            risk_reward=Decimal("8.0"),
            overall=Decimal("7.5"),
        )
        assert score.technical == Decimal("8.5")
        assert score.overall == Decimal("7.5")

    def test_score_card_range_validation(self):
        """分数应在 0-10 范围内。"""
        with pytest.raises(ValueError):
            ScoreCard(
                technical=Decimal("11"),  # 超出范围
                fundamental=Decimal("7.0"),
                sentiment=Decimal("6.5"),
                risk_reward=Decimal("8.0"),
                overall=Decimal("7.5"),
            )

    def test_score_card_negative_validation(self):
        """分数不应为负。"""
        with pytest.raises(ValueError):
            ScoreCard(
                technical=Decimal("-1"),
                fundamental=Decimal("7.0"),
                sentiment=Decimal("6.5"),
                risk_reward=Decimal("8.0"),
                overall=Decimal("7.5"),
            )


# ──────────────────── 测试: TrendAnalysis 趋势分析 ────────────────────


class TestTrendAnalysis:
    """测试趋势分析结构。"""

    def test_trend_analysis(self):
        """趋势分析应包含方向、周期、置信度。"""
        trend = TrendAnalysis(
            direction="bullish",
            timeframe="4h",
            confidence=Decimal("0.85"),
            description="4小时级别上升趋势，均线多头排列",
        )
        assert trend.direction == "bullish"
        assert trend.confidence == Decimal("0.85")

    def test_trend_direction_validation(self):
        """方向只允许 bullish/bearish/neutral。"""
        with pytest.raises(ValueError):
            TrendAnalysis(
                direction="invalid",
                timeframe="1h",
                confidence=Decimal("0.5"),
                description="测试",
            )


# ──────────────────── 测试: BuySellPoint 买卖点位 ────────────────────


class TestBuySellPoint:
    """测试买卖点位结构。"""

    def test_buy_sell_point(self):
        """买卖点位应包含价格、类型、理由。"""
        point = BuySellPoint(
            price=Decimal("50000"),
            point_type="buy",
            reason="支撑位回踩确认",
            stop_loss=Decimal("49000"),
            take_profit=Decimal("53000"),
        )
        assert point.price == Decimal("50000")
        assert point.point_type == "buy"
        assert point.stop_loss == Decimal("49000")

    def test_point_type_validation(self):
        """类型只允许 buy/sell/stop_loss/take_profit。"""
        with pytest.raises(ValueError):
            BuySellPoint(
                price=Decimal("50000"),
                point_type="hold",  # 无效类型
                reason="测试",
            )


# ──────────────────── 测试: RiskAlert 风险警报 ────────────────────


class TestRiskAlert:
    """测试风险警报结构。"""

    def test_risk_alert(self):
        """风险警报应包含等级、描述、应对措施。"""
        alert = RiskAlert(
            level="high",
            description="RSI 超买 + 成交量萎缩",
            mitigation="减仓至50%，设置止损",
        )
        assert alert.level == "high"

    def test_risk_level_validation(self):
        """等级只允许 low/medium/high/critical。"""
        with pytest.raises(ValueError):
            RiskAlert(
                level="extreme",  # 无效等级
                description="测试",
                mitigation="测试",
            )


# ──────────────────── 测试: CatalystFactor 催化因素 ────────────────────


class TestCatalystFactor:
    """测试催化因素结构。"""

    def test_catalyst_factor(self):
        """催化因素应包含类型、描述、时间窗口、影响评估。"""
        factor = CatalystFactor(
            type="positive",
            description="ETH ETF 获批预期增强",
            time_window="1-2周",
            impact="high",
        )
        assert factor.type == "positive"
        assert factor.impact == "high"


# ──────────────────── 测试: ActionChecklist 操作检查清单 ────────────────────


class TestActionChecklist:
    """测试操作检查清单。"""

    def test_checklist(self):
        """清单应包含待办事项及完成状态。"""
        checklist = ActionChecklist(
            items=[
                {"action": "确认仓位比例", "done": False},
                {"action": "设置止损单", "done": True},
                {"action": "通知客户", "done": False},
            ]
        )
        assert len(checklist.items) == 3
        assert checklist.items[1]["done"] is True


# ──────────────────── 测试: SignalCard 信号卡 ────────────────────


class TestSignalCard:
    """测试信号卡结构完整性。"""

    def test_signal_card_basic(self):
        """信号卡应包含核心字段。"""
        card = SignalCard(
            symbol="BTCUSDT",
            action="buy",
            confidence=Decimal("0.82"),
            entry_price=Decimal("50000"),
            stop_loss=Decimal("49000"),
            take_profit=Decimal("53000"),
            reason="突破关键阻力位，量价配合",
            risk_level="medium",
        )
        assert card.symbol == "BTCUSDT"
        assert card.action == "buy"
        assert card.confidence == Decimal("0.82")

    def test_signal_card_action_validation(self):
        """动作只允许 buy/sell/hold。"""
        with pytest.raises(ValueError):
            SignalCard(
                symbol="BTCUSDT",
                action="short",  # 无效动作
                confidence=Decimal("0.8"),
                entry_price=Decimal("50000"),
                reason="测试",
                risk_level="low",
            )


# ──────────────────── 测试: DecisionReport 完整研报 ────────────────────


class TestDecisionReport:
    """测试完整决策报告结构。"""

    def _make_full_report(self) -> DecisionReport:
        """构造完整报告。"""
        return DecisionReport(
            title="BTCUSDT 技术分析报告",
            symbol="BTCUSDT",
            market="SPOT",
            generated_at=datetime(2025, 1, 1, 12, 0, 0),
            core_conclusion="短期看涨，建议分批建仓",
            score_card=ScoreCard(
                technical=Decimal("8.5"),
                fundamental=Decimal("7.0"),
                sentiment=Decimal("6.5"),
                risk_reward=Decimal("8.0"),
                overall=Decimal("7.5"),
            ),
            trends=[
                TrendAnalysis(
                    direction="bullish",
                    timeframe="4h",
                    confidence=Decimal("0.85"),
                    description="4小时级别上升趋势",
                ),
                TrendAnalysis(
                    direction="neutral",
                    timeframe="1d",
                    confidence=Decimal("0.6"),
                    description="日线级别震荡整理",
                ),
            ],
            buy_sell_points=[
                BuySellPoint(
                    price=Decimal("50000"),
                    point_type="buy",
                    reason="支撑位回踩",
                    stop_loss=Decimal("49000"),
                    take_profit=Decimal("53000"),
                ),
            ],
            risk_alerts=[
                RiskAlert(
                    level="medium",
                    description="RSI 接近超买区",
                    mitigation="控制仓位不超过30%",
                ),
            ],
            catalysts=[
                CatalystFactor(
                    type="positive",
                    description="ETF 资金持续流入",
                    time_window="1-2周",
                    impact="high",
                ),
            ],
            checklist=ActionChecklist(
                items=[
                    {"action": "确认账户余额充足", "done": False},
                    {"action": "设置止损单 49000", "done": False},
                ]
            ),
        )

    def test_full_report_structure(self):
        """完整报告应包含所有必要字段。"""
        report = self._make_full_report()
        assert report.title == "BTCUSDT 技术分析报告"
        assert report.core_conclusion == "短期看涨，建议分批建仓"
        assert report.score_card.overall == Decimal("7.5")
        assert len(report.trends) == 2
        assert len(report.buy_sell_points) == 1
        assert len(report.risk_alerts) == 1
        assert len(report.catalysts) == 1
        assert len(report.checklist.items) == 2

    def test_report_serialization(self):
        """报告应可序列化为字典并反序列化。"""
        report = self._make_full_report()
        data = report.model_dump()
        assert isinstance(data, dict)
        assert data["symbol"] == "BTCUSDT"
        assert data["score_card"]["overall"] == Decimal("7.5")

        # 反序列化
        restored = DecisionReport.model_validate(data)
        assert restored.symbol == report.symbol
        assert restored.core_conclusion == report.core_conclusion

    def test_report_json_roundtrip(self):
        """报告应支持 JSON 往返序列化。"""
        report = self._make_full_report()
        json_str = report.model_dump_json()
        restored = DecisionReport.model_validate_json(json_str)
        assert restored.symbol == report.symbol
        assert restored.score_card.technical == report.score_card.technical


# ──────────────────── 测试: 从信号生成报告 ────────────────────


class TestGenerateReport:
    """测试从交易信号生成报告。"""

    def test_generate_from_signal(self):
        """应能从基础信号数据生成报告骨架。"""
        signal_data = {
            "symbol": "ETHUSDT",
            "side": "buy",
            "strength": 0.75,
            "strategy_name": "SMC_Strategy",
            "reason": "突破 order block",
            "metadata": {
                "entry_price": "3800",
                "stop_loss": "3700",
                "take_profit": "4100",
            },
        }
        report = generate_report_from_signal(signal_data)
        assert report.symbol == "ETHUSDT"
        assert report.core_conclusion != ""
        assert report.score_card is not None
        assert len(report.buy_sell_points) >= 1

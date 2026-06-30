"""
Agents 包覆盖率测试 — analyzer / macro / triager / debate / sentiment
"""

import pytest

from one_quant.agents.analyzer import AnalyzerAgent
from one_quant.agents.debate import (
    ROLE_ZH,
    BearAgent,
    BullAgent,
    DebateArgument,
    DebateGroup,
    DebateResult,
    DebateRole,
    JudgeAgent,
    RiskAgent,
)
from one_quant.agents.macro_agent import MACRO_EVENT_TYPES, MacroAgent
from one_quant.agents.sentiment import SentimentAgent
from one_quant.agents.triager import LEVEL_DESC_ZH, AlertLevel, TriagerAgent

# ════════════════════════════════════════════════════════════════
# AnalyzerAgent
# ════════════════════════════════════════════════════════════════


class TestAnalyzerAgent:
    """AnalyzerAgent 测试。"""

    @pytest.fixture
    def agent(self):
        return AnalyzerAgent()

    @pytest.mark.asyncio
    async def test_empty_input(self, agent):
        result = await agent.safe_run({})
        assert result["success"] is True
        assert "无回测数据" in result["report"]
        assert result["evaluation"] == {}

    @pytest.mark.asyncio
    async def test_excellent_strategy(self, agent):
        """优秀策略。"""
        result = await agent.safe_run(
            {
                "backtest_result": {
                    "strategy_name": "Alpha趋势",
                    "total_return": 0.8,
                    "annual_return": 0.6,
                    "sharpe_ratio": 2.5,
                    "max_drawdown": 0.08,
                    "volatility": 0.12,
                    "calmar_ratio": 4.0,
                    "total_trades": 200,
                    "win_rate": 0.65,
                    "profit_factor": 2.5,
                    "avg_win": 500,
                    "avg_loss": -200,
                }
            }
        )
        assert result["success"] is True
        assert "Alpha趋势" in result["report"]
        assert result["evaluation"]["overall"] is not None
        assert result["evaluation"]["grade"] == "A"

    @pytest.mark.asyncio
    async def test_poor_strategy(self, agent):
        """较差策略。"""
        result = await agent.safe_run(
            {
                "backtest_result": {
                    "strategy_name": "BadStrat",
                    "total_return": -0.3,
                    "annual_return": -0.25,
                    "sharpe_ratio": 0.1,
                    "max_drawdown": 0.45,
                    "volatility": 0.35,
                    "calmar_ratio": 0.2,
                    "total_trades": 30,
                    "win_rate": 0.25,
                    "profit_factor": 0.6,
                    "avg_win": 100,
                    "avg_loss": -300,
                }
            }
        )
        assert result["success"] is True
        assert result["evaluation"]["grade"] == "D"

    @pytest.mark.asyncio
    async def test_good_strategy(self, agent):
        """良好策略。"""
        result = await agent.safe_run(
            {
                "backtest_result": {
                    "strategy_name": "OK策略",
                    "total_return": 0.3,
                    "annual_return": 0.2,
                    "sharpe_ratio": 1.5,
                    "max_drawdown": 0.15,
                    "volatility": 0.18,
                    "calmar_ratio": 2.0,
                    "total_trades": 120,
                    "win_rate": 0.50,
                    "profit_factor": 1.8,
                    "avg_win": 300,
                    "avg_loss": -180,
                }
            }
        )
        assert result["success"] is True
        assert result["evaluation"]["grade"] in ("A", "B")

    @pytest.mark.asyncio
    async def test_medium_strategy(self, agent):
        """一般策略。"""
        result = await agent.safe_run(
            {
                "backtest_result": {
                    "strategy_name": "Meh",
                    "total_return": 0.05,
                    "annual_return": 0.03,
                    "sharpe_ratio": 0.7,
                    "max_drawdown": 0.25,
                    "volatility": 0.22,
                    "calmar_ratio": 0.8,
                    "total_trades": 80,
                    "win_rate": 0.40,
                    "profit_factor": 1.2,
                    "avg_win": 200,
                    "avg_loss": -180,
                }
            }
        )
        assert result["success"] is True
        assert result["evaluation"]["grade"] in ("B", "C", "D")

    def test_analyze_returns_excellent(self, agent):
        result = agent._analyze_returns(
            {
                "total_return": 0.8,
                "annual_return": 0.6,
                "sharpe_ratio": 2.5,
            }
        )
        assert result["rating"] == "优秀"
        assert "📈" in result["section"]

    def test_analyze_returns_good(self, agent):
        result = agent._analyze_returns(
            {
                "total_return": 0.3,
                "annual_return": 0.2,
                "sharpe_ratio": 1.5,
            }
        )
        assert result["rating"] == "良好"

    def test_analyze_returns_poor(self, agent):
        result = agent._analyze_returns(
            {
                "total_return": 0.01,
                "annual_return": 0.01,
                "sharpe_ratio": 0.3,
            }
        )
        assert result["rating"] == "较差"

    def test_analyze_risk_excellent(self, agent):
        result = agent._analyze_risk(
            {
                "max_drawdown": 0.05,
                "volatility": 0.10,
                "calmar_ratio": 5.0,
            }
        )
        assert result["rating"] == "优秀"

    def test_analyze_risk_good(self, agent):
        result = agent._analyze_risk(
            {
                "max_drawdown": 0.15,
                "volatility": 0.20,
                "calmar_ratio": 1.5,
            }
        )
        assert result["rating"] == "良好"

    def test_analyze_risk_poor(self, agent):
        result = agent._analyze_risk(
            {
                "max_drawdown": 0.40,
                "volatility": 0.30,
                "calmar_ratio": 0.5,
            }
        )
        assert result["rating"] == "较差"

    def test_analyze_trades_excellent(self, agent):
        result = agent._analyze_trades(
            {
                "total_trades": 200,
                "win_rate": 0.65,
                "profit_factor": 2.5,
                "avg_win": 500,
                "avg_loss": -200,
            }
        )
        assert result["rating"] == "优秀"

    def test_analyze_trades_poor(self, agent):
        result = agent._analyze_trades(
            {
                "total_trades": 20,
                "win_rate": 0.25,
                "profit_factor": 0.6,
                "avg_win": 100,
                "avg_loss": -300,
            }
        )
        assert result["rating"] == "较差"

    def test_overall_evaluation_all_excellent(self, agent):
        result = agent._overall_evaluation({"returns": "优秀", "risk": "优秀", "trades": "优秀"})
        assert result["grade"] == "A"

    def test_overall_evaluation_all_poor(self, agent):
        result = agent._overall_evaluation({"returns": "较差", "risk": "较差", "trades": "较差"})
        assert result["grade"] == "D"

    def test_overall_evaluation_mixed(self, agent):
        result = agent._overall_evaluation({"returns": "良好", "risk": "一般", "trades": "良好"})
        assert result["grade"] in ("A", "B", "C")

    def test_overall_evaluation_empty(self, agent):
        result = agent._overall_evaluation({})
        assert result["grade"] == "C"

    def test_generate_suggestions_high_dd(self, agent):
        suggestions = agent._generate_suggestions(
            {"max_drawdown": 0.35, "win_rate": 0.50, "sharpe_ratio": 1.5, "total_trades": 100},
            {},
        )
        assert "降低最大回撤" in suggestions

    def test_generate_suggestions_low_winrate(self, agent):
        suggestions = agent._generate_suggestions(
            {"max_drawdown": 0.10, "win_rate": 0.30, "sharpe_ratio": 1.5, "total_trades": 100},
            {},
        )
        assert "提高胜率" in suggestions

    def test_generate_suggestions_low_sharpe(self, agent):
        suggestions = agent._generate_suggestions(
            {"max_drawdown": 0.10, "win_rate": 0.50, "sharpe_ratio": 0.3, "total_trades": 100},
            {},
        )
        assert "提升夏普比率" in suggestions

    def test_generate_suggestions_few_trades(self, agent):
        suggestions = agent._generate_suggestions(
            {"max_drawdown": 0.10, "win_rate": 0.50, "sharpe_ratio": 1.5, "total_trades": 20},
            {},
        )
        assert "增加样本量" in suggestions

    def test_generate_suggestions_all_good(self, agent):
        suggestions = agent._generate_suggestions(
            {"max_drawdown": 0.05, "win_rate": 0.60, "sharpe_ratio": 2.5, "total_trades": 200},
            {},
        )
        assert "影子运行" in suggestions

    def test_describe_sharpe(self):
        assert "极佳" in AnalyzerAgent._describe_sharpe(2.5)
        assert "良好" in AnalyzerAgent._describe_sharpe(1.5)
        assert "一般" in AnalyzerAgent._describe_sharpe(0.7)
        assert "较差" in AnalyzerAgent._describe_sharpe(0.2)

    def test_describe_return(self):
        assert "亮眼" in AnalyzerAgent._describe_return(0.6)
        assert "尚可" in AnalyzerAgent._describe_return(0.2)
        assert "略有盈利" in AnalyzerAgent._describe_return(0.05)
        assert "亏损" in AnalyzerAgent._describe_return(-0.1)

    def test_describe_drawdown(self):
        assert "优秀" in AnalyzerAgent._describe_drawdown(0.05)
        assert "可接受" in AnalyzerAgent._describe_drawdown(0.15)
        assert "偏高" in AnalyzerAgent._describe_drawdown(0.25)
        assert "严重偏高" in AnalyzerAgent._describe_drawdown(0.40)

    def test_describe_trades(self):
        result = AnalyzerAgent._describe_trades(0.60, 2.0, 200)
        assert "不错" in result
        assert "健康" in result

    def test_describe_trades_poor(self):
        result = AnalyzerAgent._describe_trades(0.30, 0.8, 20)
        assert "偏低" in result
        assert "有待改善" in result
        assert "样本偏少" in result


# ════════════════════════════════════════════════════════════════
# MacroAgent
# ════════════════════════════════════════════════════════════════


class TestMacroAgent:
    """MacroAgent 测试。"""

    @pytest.fixture
    def agent(self):
        return MacroAgent()

    @pytest.mark.asyncio
    async def test_empty_input(self, agent):
        result = await agent.safe_run({})
        assert result["success"] is True
        assert result["impact_score"] == 0.0
        assert result["risk_level"] == "低"
        assert "无重大宏观事件" in result["report"]

    @pytest.mark.asyncio
    async def test_with_events(self, agent):
        result = await agent.safe_run(
            {
                "events": [
                    {"type": "fed_rate", "description": "美联储降息25bp", "impact": "positive"},
                    {"type": "cpi", "description": "CPI低于预期", "impact": "positive"},
                ],
                "indicators": {},
                "market_state": {},
            }
        )
        assert result["success"] is True
        assert result["event_count"] == 2
        assert len(result["key_events"]) == 2
        assert result["impact_score"] > 0

    @pytest.mark.asyncio
    async def test_negative_events(self, agent):
        result = await agent.safe_run(
            {
                "events": [
                    {"type": "geopolitical", "description": "地缘冲突升级", "impact": "negative"},
                    {"type": "trade_war", "description": "贸易战", "impact": "negative"},
                ],
            }
        )
        assert result["impact_score"] < 0
        assert result["risk_level"] in ("中", "高")

    @pytest.mark.asyncio
    async def test_with_indicators(self, agent):
        result = await agent.safe_run(
            {
                "events": [],
                "indicators": {
                    "cpi_yoy": 4.5,
                    "fed_rate": 5.5,
                    "unemployment": 3.0,
                    "vix": 35.0,
                    "dollar_index": 110.0,
                },
            }
        )
        assert result["success"] is True
        assert "报告" in result["report"] or "🌍" in result["report"]

    @pytest.mark.asyncio
    async def test_mixed_events_and_indicators(self, agent):
        result = await agent.safe_run(
            {
                "events": [
                    {"type": "fed_rate", "description": "维持利率不变", "impact": "neutral"},
                ],
                "indicators": {
                    "cpi_yoy": 2.0,
                    "vix": 12.0,
                },
                "market_state": {"trend": "bullish"},
            }
        )
        assert result["success"] is True

    def test_analyze_events(self, agent):
        events = [
            {"type": "fed_rate", "description": "降息", "impact": "positive"},
            {"type": "unknown_type", "description": "未知事件", "impact": "neutral"},
        ]
        analyses = agent._analyze_events(events)
        assert len(analyses) == 2
        assert analyses[0]["type_zh"] == "美联储利率决议"
        assert analyses[0]["severity"] == "高"
        assert analyses[1]["type_zh"] == "unknown_type"

    def test_interpret_indicators(self, agent):
        indicators = {
            "cpi_yoy": 4.5,
            "fed_rate": 5.5,
            "unemployment": 3.0,
            "vix": 12.0,
            "dollar_index": 90.0,
            "not_a_real_metric": 42,
        }
        insights = agent._interpret_indicators(indicators)
        # not_a_real_metric should be skipped
        assert len(insights) == 5

    def test_interpret_single_indicator_high(self, agent):
        result = agent._interpret_single_indicator("cpi_yoy", 4.5)
        assert result is not None
        assert result["direction"] == "偏高"
        assert result["signal"] == "bearish"

    def test_interpret_single_indicator_low(self, agent):
        result = agent._interpret_single_indicator("cpi_yoy", 1.0)
        assert result["direction"] == "偏低"
        assert result["signal"] == "bullish"

    def test_interpret_single_indicator_normal(self, agent):
        result = agent._interpret_single_indicator("cpi_yoy", 2.5)
        assert result["direction"] == "正常"
        assert result["signal"] == "neutral"

    def test_interpret_single_indicator_unknown(self, agent):
        result = agent._interpret_single_indicator("unknown_metric", 42)
        assert result is None

    def test_interpret_single_indicator_non_numeric(self, agent):
        result = agent._interpret_indicators({"cpi_yoy": "high"})
        assert len(result) == 0

    def test_assess_event_severity(self):
        assert MacroAgent._assess_event_severity("fed_rate", "positive") == "高"
        assert MacroAgent._assess_event_severity("nfp", "negative") == "中"
        assert MacroAgent._assess_event_severity("pmi", "neutral") == "低"

    def test_predict_market_impact(self):
        assert "利好" in MacroAgent._predict_market_impact("fed_rate", "positive")
        assert "利空" in MacroAgent._predict_market_impact("fed_rate", "negative")
        assert "不确定" in MacroAgent._predict_market_impact("fed_rate", "neutral")

    def test_calculate_impact_positive(self, agent):
        events = [{"severity": "高", "impact_direction": "positive"}]
        indicators = [{"signal": "bullish"}]
        score = agent._calculate_impact(events, indicators)
        assert score > 0

    def test_calculate_impact_negative(self, agent):
        events = [{"severity": "高", "impact_direction": "negative"}]
        indicators = [{"signal": "bearish"}]
        score = agent._calculate_impact(events, indicators)
        assert score < 0

    def test_calculate_impact_neutral(self, agent):
        score = agent._calculate_impact([], [])
        assert score == 0.0

    def test_assess_risk_level(self):
        assert MacroAgent._assess_risk_level(0.6) == "高"
        assert MacroAgent._assess_risk_level(-0.6) == "高"
        assert MacroAgent._assess_risk_level(0.3) == "中"
        assert MacroAgent._assess_risk_level(0.1) == "低"

    def test_generate_report_bullish(self, agent):
        report = agent._generate_report(
            [
                {
                    "severity": "高",
                    "type_zh": "美联储利率决议",
                    "description": "降息",
                    "market_impact": "利好",
                }
            ],
            [
                {
                    "name_zh": "CPI",
                    "value": 1.0,
                    "direction": "偏低",
                    "meaning": "通胀温和",
                    "signal": "bullish",
                }
            ],
            0.5,
            {},
        )
        assert "偏乐观" in report
        assert "🟢" in report

    def test_generate_report_bearish(self, agent):
        report = agent._generate_report(
            [
                {
                    "severity": "高",
                    "type_zh": "地缘政治事件",
                    "description": "冲突",
                    "market_impact": "利空",
                }
            ],
            [],
            -0.5,
            {},
        )
        assert "偏悲观" in report
        assert "🔴" in report

    def test_generate_report_neutral(self, agent):
        report = agent._generate_report([], [], 0.0, {})
        assert "中性" in report
        assert "🟡" in report

    def test_macro_event_types_dict(self):
        assert "fed_rate" in MACRO_EVENT_TYPES
        assert "cpi" in MACRO_EVENT_TYPES
        assert len(MACRO_EVENT_TYPES) >= 10


# ════════════════════════════════════════════════════════════════
# TriagerAgent
# ════════════════════════════════════════════════════════════════


class TestTriagerAgent:
    """TriagerAgent 测试。"""

    @pytest.fixture
    def agent(self):
        return TriagerAgent()

    @pytest.mark.asyncio
    async def test_empty_alerts(self, agent):
        result = await agent.safe_run({})
        assert result["success"] is True
        assert result["triaged_alerts"] == []
        assert "无告警" in result["broadcast"]
        assert result["stats"] == {"P0": 0, "P1": 0, "P2": 0, "P3": 0}

    @pytest.mark.asyncio
    async def test_p0_alert(self, agent):
        result = await agent.safe_run(
            {
                "alerts": [
                    {"message": "系统故障，行情断线", "type": "connection_lost"},
                ]
            }
        )
        assert result["success"] is True
        assert result["has_p0"] is True
        assert result["stats"]["P0"] >= 1
        assert len(result["action_items"]) > 0

    @pytest.mark.asyncio
    async def test_mixed_alerts(self, agent):
        result = await agent.safe_run(
            {
                "alerts": [
                    {"message": "系统故障", "type": "system_error"},
                    {"message": "暴跌10%", "type": "price_drop"},
                    {"message": "延迟升高", "type": "high_latency"},
                    {"message": "日常波动提示", "type": "info"},
                ]
            }
        )
        assert result["success"] is True
        total = sum(result["stats"].values())
        assert total == 4
        # P0 should be first after sorting
        assert result["triaged_alerts"][0]["level"] == "P0"

    @pytest.mark.asyncio
    async def test_p1_alerts(self, agent):
        result = await agent.safe_run(
            {
                "alerts": [
                    {"message": "大额亏损预警", "type": "position_loss"},
                    {"message": "流动性枯竭", "type": "liquidity"},
                ]
            }
        )
        assert result["stats"]["P1"] >= 1
        assert "🟠 高" in result["broadcast"]

    @pytest.mark.asyncio
    async def test_with_existing_level(self, agent):
        """已有等级的告警。"""
        result = await agent.safe_run(
            {
                "alerts": [
                    {"message": "普通波动", "type": "info", "level": "P3"},
                ]
            }
        )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_action_items_for_p0(self, agent):
        result = await agent.safe_run(
            {
                "alerts": [
                    {"message": "强平风险告警", "type": "liquidation_risk"},
                    {"message": "行情断线", "type": "connection_lost"},
                ]
            }
        )
        assert any("强平" in a for a in result["action_items"])
        assert any("P0" in a or "紧急" in a or "检查行情" in a for a in result["action_items"])

    @pytest.mark.asyncio
    async def test_action_items_for_p1(self, agent):
        result = await agent.safe_run(
            {
                "alerts": [
                    {"message": "大额亏损预警", "type": "position_loss"},
                    {"message": "价格异常波动", "type": "price_spike"},
                ]
            }
        )
        assert any("P1" in a for a in result["action_items"])

    @pytest.mark.asyncio
    async def test_no_action_items_low_alerts(self, agent):
        result = await agent.safe_run(
            {
                "alerts": [
                    {"message": "日常波动提示", "type": "info"},
                ]
            }
        )
        assert any("无需立即行动" in a for a in result["action_items"])

    def test_triage_single(self, agent):
        alert = {"message": "系统故障告警", "type": "system_error"}
        triaged = agent._triage_single(alert)
        assert triaged["level"] == "P0"
        assert "level_desc" in triaged
        assert "category" in triaged
        assert "triaged_at" in triaged

    def test_match_keyword_level_p0(self, agent):
        assert agent._match_keyword_level("系统故障告警") == AlertLevel.P0

    def test_match_keyword_level_p1(self, agent):
        assert agent._match_keyword_level("闪崩预警") == AlertLevel.P1

    def test_match_keyword_level_p2(self, agent):
        assert agent._match_keyword_level("延迟升高") == AlertLevel.P2

    def test_match_keyword_level_p3(self, agent):
        assert agent._match_keyword_level("日常波动提示") == AlertLevel.P3

    def test_match_keyword_level_none(self, agent):
        assert agent._match_keyword_level("今天天气不错") is None

    def test_match_keyword_level_multiple(self, agent):
        """多关键词取最高级。"""
        level = agent._match_keyword_level("系统故障导致闪崩")
        assert level == AlertLevel.P0

    def test_pick_severity(self):
        assert TriagerAgent._pick_severity("P2", AlertLevel.P0) == "P0"
        assert TriagerAgent._pick_severity("P0", AlertLevel.P2) == "P0"
        assert TriagerAgent._pick_severity("", AlertLevel.P3) == "P3"
        assert TriagerAgent._pick_severity("P1", None) == "P1"
        assert TriagerAgent._pick_severity("", None) == AlertLevel.P3

    def test_categorize_by_type(self):
        assert TriagerAgent._categorize("price_spike", "") == "价格异常"
        assert TriagerAgent._categorize("position_loss", "") == "持仓风险"
        assert TriagerAgent._categorize("high_latency", "") == "系统延迟"
        assert TriagerAgent._categorize("connection_lost", "") == "连接故障"
        assert TriagerAgent._categorize("system_error", "") == "系统故障"
        assert TriagerAgent._categorize("liquidation_risk", "") == "强平风险"
        assert TriagerAgent._categorize("strategy_conflict", "") == "策略冲突"

    def test_categorize_by_keyword(self):
        assert TriagerAgent._categorize("unknown", "价格突然暴跌") == "价格异常"
        assert TriagerAgent._categorize("unknown", "成交量放大") == "成交量异常"
        assert TriagerAgent._categorize("unknown", "持仓亏损严重") == "持仓风险"
        assert TriagerAgent._categorize("unknown", "连接超时断线") == "系统异常"
        assert TriagerAgent._categorize("unknown", "今天天气好") == "其他"

    def test_generate_broadcast(self, agent):
        triaged = [
            {"level": "P0", "category": "系统故障", "message": "断线", "symbol": ""},
            {"level": "P3", "category": "其他", "message": "提示", "symbol": "BTC"},
        ]
        stats = {"P0": 1, "P1": 0, "P2": 0, "P3": 1}
        broadcast = agent._generate_broadcast(triaged, stats)
        assert "共 2 条" in broadcast
        assert "🔴 紧急" in broadcast

    def test_generate_broadcast_empty(self, agent):
        assert "无告警" in agent._generate_broadcast([], {})

    def test_alert_level_enum(self):
        assert AlertLevel.P0 == "P0"
        assert AlertLevel.P3 == "P3"

    def test_level_desc_zh(self):
        assert "紧急" in LEVEL_DESC_ZH[AlertLevel.P0]
        assert "低" in LEVEL_DESC_ZH[AlertLevel.P3]


# ════════════════════════════════════════════════════════════════
# Debate Agents (Bull / Bear / Risk / Judge / DebateGroup)
# ════════════════════════════════════════════════════════════════


class TestBullAgent:
    @pytest.fixture
    def agent(self):
        return BullAgent()

    @pytest.mark.asyncio
    async def test_bull_no_signals(self, agent):
        result = await agent.safe_run({"topic": "BTC", "context": {}})
        assert result["success"] is True
        assert result["role"] == DebateRole.BULL
        assert "未见明显看涨信号" in result["key_points"][0]

    @pytest.mark.asyncio
    async def test_bull_with_signals(self, agent):
        result = await agent.safe_run(
            {
                "topic": "BTC",
                "context": {
                    "rsi": 25,
                    "macd_signal": "golden_cross",
                    "funding_rate": -0.02,
                    "sentiment_score": -0.5,
                    "positive_catalyst": "ETF通过",
                },
            }
        )
        assert result["success"] is True
        assert len(result["key_points"]) >= 4
        assert result["confidence"] > 0

    def test_find_bull_points_rsi(self, agent):
        points = agent._find_bull_points({"rsi": 20})
        assert any("超卖" in p for p in points)

    def test_find_bull_points_macd(self, agent):
        points = agent._find_bull_points({"macd_signal": "golden_cross"})
        assert any("金叉" in p for p in points)

    def test_find_bull_points_funding(self, agent):
        points = agent._find_bull_points({"funding_rate": -0.02})
        assert any("轧空" in p for p in points)

    def test_find_bull_points_sentiment(self, agent):
        points = agent._find_bull_points({"sentiment_score": -0.5})
        assert any("悲观" in p for p in points)

    def test_find_bull_points_catalyst(self, agent):
        points = agent._find_bull_points({"positive_catalyst": "ETF通过"})
        assert any("ETF通过" in p for p in points)


class TestBearAgent:
    @pytest.fixture
    def agent(self):
        return BearAgent()

    @pytest.mark.asyncio
    async def test_bear_no_signals(self, agent):
        result = await agent.safe_run({"topic": "BTC", "context": {}})
        assert result["success"] is True
        assert result["role"] == DebateRole.BEAR
        assert "未见明显看跌信号" in result["key_points"][0]

    @pytest.mark.asyncio
    async def test_bear_with_signals(self, agent):
        result = await agent.safe_run(
            {
                "topic": "BTC",
                "context": {
                    "rsi": 80,
                    "macd_signal": "death_cross",
                    "funding_rate": 0.05,
                    "sentiment_score": 0.8,
                    "negative_catalyst": "监管打击",
                    "macro_risk_level": "高",
                },
            }
        )
        assert result["success"] is True
        assert len(result["key_points"]) >= 5

    def test_find_bear_points_rsi(self, agent):
        points = agent._find_bear_points({"rsi": 80})
        assert any("超买" in p for p in points)

    def test_find_bear_points_macd(self, agent):
        points = agent._find_bear_points({"macd_signal": "death_cross"})
        assert any("死叉" in p for p in points)

    def test_find_bear_points_funding(self, agent):
        points = agent._find_bear_points({"funding_rate": 0.05})
        assert any("多杀多" in p for p in points)

    def test_find_bear_points_sentiment(self, agent):
        points = agent._find_bear_points({"sentiment_score": 0.8})
        assert any("乐观" in p for p in points)

    def test_find_bear_points_catalyst(self, agent):
        points = agent._find_bear_points({"negative_catalyst": "监管打击"})
        assert any("监管打击" in p for p in points)

    def test_find_bear_points_macro_risk(self, agent):
        points = agent._find_bear_points({"macro_risk_level": "高"})
        assert any("宏观风险" in p for p in points)


class TestRiskAgent:
    @pytest.fixture
    def agent(self):
        return RiskAgent()

    @pytest.mark.asyncio
    async def test_risk_no_issues(self, agent):
        result = await agent.safe_run({"topic": "BTC", "context": {}})
        assert result["success"] is True
        assert result["role"] == DebateRole.RISK
        assert any("可控" in w for w in result["key_points"])

    @pytest.mark.asyncio
    async def test_risk_multiple_issues(self, agent):
        result = await agent.safe_run(
            {
                "topic": "BTC",
                "context": {
                    "position_size_pct": 30,
                    "leverage": 10,
                    "volatility": 0.08,
                    "correlated_positions": 5,
                    "current_drawdown": 0.15,
                },
            }
        )
        assert result["success"] is True
        assert len(result["key_points"]) >= 4
        assert result["confidence"] == 1.0

    def test_assess_risks_position(self, agent):
        warnings = agent._assess_risks({"position_size_pct": 30})
        assert any("仓位过重" in w for w in warnings)

    def test_assess_risks_leverage(self, agent):
        warnings = agent._assess_risks({"leverage": 10})
        assert any("杠杆过高" in w for w in warnings)

    def test_assess_risks_volatility(self, agent):
        warnings = agent._assess_risks({"volatility": 0.08})
        assert any("波动率" in w for w in warnings)

    def test_assess_risks_correlation(self, agent):
        warnings = agent._assess_risks({"correlated_positions": 5})
        assert any("关联持仓" in w for w in warnings)

    def test_assess_risks_drawdown(self, agent):
        warnings = agent._assess_risks({"current_drawdown": 0.15})
        assert any("回撤" in w for w in warnings)

    def test_risk_level(self):
        assert "高" in RiskAgent._risk_level(["a", "b", "c"])
        assert "中" in RiskAgent._risk_level(["a", "b"])
        assert "低" in RiskAgent._risk_level(["a"])


class TestJudgeAgent:
    @pytest.fixture
    def agent(self):
        return JudgeAgent()

    @pytest.mark.asyncio
    async def test_judge_bull_wins(self, agent):
        result = await agent.safe_run(
            {
                "topic": "BTC",
                "bull_result": {"key_points": ["p1", "p2", "p3", "p4"], "confidence": 0.8},
                "bear_result": {"key_points": ["p1"], "confidence": 0.3},
                "risk_result": {"key_points": ["当前风险可控"]},
            }
        )
        assert result["decision"] == "buy"

    @pytest.mark.asyncio
    async def test_judge_bear_wins(self, agent):
        result = await agent.safe_run(
            {
                "topic": "BTC",
                "bull_result": {"key_points": ["p1"], "confidence": 0.3},
                "bear_result": {"key_points": ["p1", "p2", "p3", "p4"], "confidence": 0.8},
                "risk_result": {"key_points": ["当前风险可控"]},
            }
        )
        assert result["decision"] == "sell"

    @pytest.mark.asyncio
    async def test_judge_hold_balanced(self, agent):
        result = await agent.safe_run(
            {
                "topic": "BTC",
                "bull_result": {"key_points": ["p1"], "confidence": 0.5},
                "bear_result": {"key_points": ["p1"], "confidence": 0.5},
                "risk_result": {"key_points": ["当前风险可控"]},
            }
        )
        assert result["decision"] == "hold"

    @pytest.mark.asyncio
    async def test_judge_risk_veto(self, agent):
        result = await agent.safe_run(
            {
                "topic": "BTC",
                "bull_result": {"key_points": ["p1", "p2", "p3"], "confidence": 0.9},
                "bear_result": {"key_points": ["p1"], "confidence": 0.3},
                "risk_result": {"key_points": ["仓位过重，建议不超过20%", "杠杆过高"]},
            }
        )
        assert result["decision"] == "hold"


class TestDebateGroup:
    @pytest.mark.asyncio
    async def test_debate_basic(self):
        group = DebateGroup()
        result = await group.debate("BTC 在当前价位是否值得买入？", {"rsi": 25})
        assert isinstance(result, DebateResult)
        assert result.topic == "BTC 在当前价位是否值得买入？"
        assert result.decision in ("buy", "sell", "hold")
        assert len(result.arguments) >= 3
        assert result.timestamp_ns > 0

    @pytest.mark.asyncio
    async def test_debate_and_report(self):
        group = DebateGroup()
        result = await group.debate_and_report("ETH 趋势研判", {"rsi": 80})
        assert result["success"] is True
        assert "多空辩论报告" in result["report"]
        assert "decision" in result

    @pytest.mark.asyncio
    async def test_debate_empty_context(self):
        group = DebateGroup()
        result = await group.debate("测试")
        assert result.decision in ("buy", "sell", "hold")

    def test_debate_result_to_dict(self):
        result = DebateResult(
            topic="test",
            arguments=[
                DebateArgument(
                    role="bull",
                    role_zh="🐂 多头",
                    argument="看涨",
                    confidence=0.8,
                    key_points=["p1"],
                )
            ],
            verdict="看涨",
            verdict_zh="⚖️ 看涨",
            decision="buy",
            confidence=0.7,
            risk_warnings=["风险1"],
        )
        d = result.to_dict()
        assert d["topic"] == "test"
        assert d["decision"] == "buy"
        assert len(d["arguments"]) == 1
        assert d["arguments"][0]["role"] == "bull"

    def test_debate_roles(self):
        assert DebateRole.BULL == "bull"
        assert DebateRole.BEAR == "bear"
        assert DebateRole.RISK == "risk"
        assert DebateRole.JUDGE == "judge"

    def test_role_zh(self):
        assert "多头" in ROLE_ZH[DebateRole.BULL]
        assert "空头" in ROLE_ZH[DebateRole.BEAR]
        assert "风控" in ROLE_ZH[DebateRole.RISK]
        assert "裁判" in ROLE_ZH[DebateRole.JUDGE]


# ════════════════════════════════════════════════════════════════
# SentimentAgent (补充覆盖率)
# ════════════════════════════════════════════════════════════════


class TestSentimentAgentCoverage:
    """SentimentAgent 补充测试。"""

    @pytest.fixture
    def agent(self):
        return SentimentAgent()

    @pytest.mark.asyncio
    async def test_positive_multiple_texts(self, agent):
        result = await agent.safe_run(
            {
                "texts": ["利好消息，突破新高", "看涨信号强烈", "牛市来临"],
                "symbol": "BTC",
            }
        )
        assert result["success"] is True
        assert result["sentiment_score"] > 0
        assert result["action"] == "buy"
        assert result["sample_count"] == 3

    @pytest.mark.asyncio
    async def test_negative_multiple_texts(self, agent):
        result = await agent.safe_run(
            {
                "texts": ["利空消息，暴跌崩盘", "卖出信号", "熊市来临"],
                "symbol": "BTC",
            }
        )
        assert result["sentiment_score"] < 0
        assert result["action"] == "sell"

    @pytest.mark.asyncio
    async def test_neutral_texts(self, agent):
        result = await agent.safe_run(
            {
                "texts": ["今天天气不错", "市场平稳运行"],
                "symbol": "BTC",
            }
        )
        assert result["sentiment_score"] == 0.0
        assert result["action"] == "hold"

    @pytest.mark.asyncio
    async def test_low_confidence(self, agent):
        """样本不足时拒绝给结论。"""
        result = await agent.safe_run(
            {
                "texts": ["单条消息"],
                "symbol": "BTC",
            }
        )
        # 1 sample / 10 = 0.1 < 0.3
        assert result["confidence"] < 0.3
        assert result.get("action") == "hold" or "拒绝" in result.get("interpretation", "")

    @pytest.mark.asyncio
    async def test_high_confidence(self, agent):
        """足够多样本。"""
        texts = ["利好"] * 15
        result = await agent.safe_run({"texts": texts, "symbol": "BTC"})
        assert result["confidence"] == 1.0

    def test_analyze_single_positive(self, agent):
        result = agent._analyze_single("利好消息，突破新高")
        assert result["score"] > 0
        assert result["interpretation"] == "偏积极"

    def test_analyze_single_negative(self, agent):
        result = agent._analyze_single("利空暴跌崩盘")
        assert result["score"] < 0
        assert result["interpretation"] == "偏消极"

    def test_analyze_single_neutral(self, agent):
        result = agent._analyze_single("今天天气不错")
        assert result["score"] == 0.0
        assert result["interpretation"] == "中性"

    def test_generate_interpretation_strongly_positive(self, agent):
        assert "明显偏积极" in agent._generate_interpretation(0.6, 10)

    def test_generate_interpretation_slightly_positive(self, agent):
        assert "略偏积极" in agent._generate_interpretation(0.3, 10)

    def test_generate_interpretation_strongly_negative(self, agent):
        assert "明显偏消极" in agent._generate_interpretation(-0.6, 10)

    def test_generate_interpretation_slightly_negative(self, agent):
        assert "略偏消极" in agent._generate_interpretation(-0.3, 10)

    def test_generate_interpretation_neutral(self, agent):
        assert "中性" in agent._generate_interpretation(0.0, 10)

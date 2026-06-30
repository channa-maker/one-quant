"""
ONE量化 - AI 智能体框架测试

验证智能体注册、Provider 路由、token 计量。
"""

import pytest

from one_quant.agents.base import BaseAgent
from one_quant.agents.briefer import BrieferAgent
from one_quant.agents.watcher import WatcherAgent
from one_quant.agents.sentiment import SentimentAgent


class TestAgentRegistry:
    """智能体注册测试"""

    def test_all_agents_have_names(self):
        """所有智能体都有名称。"""
        agents = [BrieferAgent(), WatcherAgent(), SentimentAgent()]
        for agent in agents:
            assert isinstance(agent.name, str)
            assert len(agent.name) > 0

    def test_all_agents_have_descriptions(self):
        """所有智能体都有描述。"""
        agents = [BrieferAgent(), WatcherAgent(), SentimentAgent()]
        for agent in agents:
            assert isinstance(agent.description, str)
            assert len(agent.description) > 0


class TestAgentLifecycle:
    """智能体生命周期测试"""

    @pytest.mark.asyncio
    async def test_safe_run_catches_exceptions(self):
        """safe_run 捕获异常。"""
        class FailingAgent(BaseAgent):
            name = "failing"
            description = "总是失败"

            async def run(self, input_data):
                raise ValueError("故意失败")

        agent = FailingAgent()
        result = await agent.safe_run({})
        assert result["success"] is False
        assert "故意失败" in result["error"]

    @pytest.mark.asyncio
    async def test_stats_tracking(self):
        """统计跟踪。"""
        agent = BrieferAgent()
        assert agent.stats["run_count"] == 0

        await agent.safe_run({})
        assert agent.stats["run_count"] == 1

        await agent.safe_run({})
        assert agent.stats["run_count"] == 2


class TestBrieferAgent:
    """简报官测试"""

    @pytest.mark.asyncio
    async def test_report_structure(self):
        """研报结构完整性。"""
        agent = BrieferAgent()
        result = await agent.safe_run({
            "market_data": {"BTC/USDT": {"change_24h": 3.0}},
            "positions": [{"symbol": "BTC/USDT", "unrealized_pnl": 100}],
            "signals": [],
            "ai_analysis": {},
        })
        assert "📊" in result["report"]
        assert "💼" in result["report"]
        assert "📡" in result["report"]
        assert "🤖" in result["report"]
        assert "📝" in result["report"]


class TestWatcherAgent:
    """哨兵测试"""

    @pytest.mark.asyncio
    async def test_latency_alert(self):
        """高延迟告警。"""
        agent = WatcherAgent()
        result = await agent.safe_run({
            "tickers": {},
            "positions": [],
            "system_metrics": {"market_latency_ms": 5000},
        })
        assert result["alert_count"] >= 1
        assert any(a["type"] == "high_latency" for a in result["alerts"])


class TestSentimentAgent:
    """情绪分析测试"""

    @pytest.mark.asyncio
    async def test_mixed_sentiment(self):
        """混合情绪。"""
        agent = SentimentAgent()
        result = await agent.safe_run({
            "texts": ["利好消息", "利空消息"],
            "symbol": "BTC/USDT",
        })
        assert result["success"] is True
        assert -1 <= result["sentiment_score"] <= 1

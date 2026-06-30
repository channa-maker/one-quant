"""
ONE量化 - AI 智能体测试

验证简报官、哨兵、情绪分析智能体。
"""

import pytest

from one_quant.agents.briefer import BrieferAgent
from one_quant.agents.sentiment import SentimentAgent
from one_quant.agents.watcher import WatcherAgent


@pytest.mark.asyncio
async def test_briefer_empty_input():
    """简报官处理空输入。"""
    agent = BrieferAgent()
    result = await agent.safe_run({})
    assert result["success"] is True
    assert "report" in result


@pytest.mark.asyncio
async def test_briefer_with_data():
    """简报官生成研报。"""
    agent = BrieferAgent()
    result = await agent.safe_run(
        {
            "market_data": {
                "BTC/USDT": {"change_24h": 5.2},
                "ETH/USDT": {"change_24h": -2.1},
            },
            "positions": [
                {"symbol": "BTC/USDT", "unrealized_pnl": 500},
            ],
            "signals": [
                {
                    "symbol": "BTC/USDT",
                    "side": "buy",
                    "strength": 0.8,
                    "strategy_name": "ema_cross",
                    "reason": "EMA 金叉",
                },
            ],
        }
    )
    assert result["success"] is True
    assert "📊" in result["report"]
    assert "💼" in result["report"]


@pytest.mark.asyncio
async def test_watcher_no_alerts():
    """哨兵无异常时不告警。"""
    agent = WatcherAgent()
    result = await agent.safe_run(
        {
            "tickers": {"BTC/USDT": {"change_pct": 1.0}},
            "positions": [],
            "system_metrics": {},
        }
    )
    assert result["success"] is True
    assert result["alert_count"] == 0
    assert "正常" in result["broadcast"]


@pytest.mark.asyncio
async def test_watcher_price_spike():
    """哨兵检测价格突变。"""
    agent = WatcherAgent()
    result = await agent.safe_run(
        {
            "tickers": {"BTC/USDT": {"change_pct": 10.0}},
            "positions": [],
            "system_metrics": {},
        }
    )
    assert result["alert_count"] >= 1
    assert any(a["type"] == "price_spike" for a in result["alerts"])


@pytest.mark.asyncio
async def test_watcher_position_loss():
    """哨兵检测持仓亏损。"""
    agent = WatcherAgent()
    result = await agent.safe_run(
        {
            "tickers": {},
            "positions": [{"symbol": "BTC/USDT", "pnl_pct": -15.0}],
            "system_metrics": {},
        }
    )
    assert result["alert_count"] >= 1
    assert any(a["type"] == "position_loss" for a in result["alerts"])


@pytest.mark.asyncio
async def test_sentiment_positive():
    """情绪分析偏积极。"""
    agent = SentimentAgent()
    result = await agent.safe_run(
        {
            "texts": ["利好消息，比特币上涨突破新高"],
            "symbol": "BTC/USDT",
        }
    )
    assert result["success"] is True
    assert result["sentiment_score"] >= 0


@pytest.mark.asyncio
async def test_sentiment_negative():
    """情绪分析偏消极。"""
    agent = SentimentAgent()
    result = await agent.safe_run(
        {
            "texts": ["利空消息，比特币暴跌崩盘"],
            "symbol": "BTC/USDT",
        }
    )
    assert result["success"] is True
    assert result["sentiment_score"] <= 0


@pytest.mark.asyncio
async def test_sentiment_empty():
    """情绪分析无文本。"""
    agent = SentimentAgent()
    result = await agent.safe_run({"texts": [], "symbol": "BTC/USDT"})
    assert result["success"] is True
    assert result["sentiment_score"] == 0.0


@pytest.mark.asyncio
async def test_agent_stats():
    """智能体统计。"""
    agent = BrieferAgent()
    await agent.safe_run({})
    assert agent.stats["run_count"] == 1

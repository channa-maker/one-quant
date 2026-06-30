"""
ONE量化 - AI 智能体包

提供 LLM 智能体框架和内置智能体。
"""

from one_quant.agents.analyzer import AnalyzerAgent
from one_quant.agents.base import BaseAgent
from one_quant.agents.briefer import BrieferAgent
from one_quant.agents.debate import (
    BearAgent,
    BullAgent,
    DebateGroup,
    DebateResult,
    JudgeAgent,
    RiskAgent,
)
from one_quant.agents.macro_agent import MacroAgent
from one_quant.agents.sentiment import SentimentAgent
from one_quant.agents.triager import TriagerAgent
from one_quant.agents.watcher import WatcherAgent

__all__ = [
    # 基类
    "BaseAgent",
    # 内置智能体
    "BrieferAgent",
    "SentimentAgent",
    "WatcherAgent",
    "TriagerAgent",
    "AnalyzerAgent",
    "MacroAgent",
    # 多空辩论组
    "BullAgent",
    "BearAgent",
    "RiskAgent",
    "JudgeAgent",
    "DebateGroup",
    "DebateResult",
]

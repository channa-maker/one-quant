"""自进化平台 — 策略全生命周期闭环 + 冠军挑战者 + 自动再训练

核心原则：
- 进化产物仍是 Signal，必过风控
- 硬阈值 AI 改不动
- 进化全审计（依据什么数据、对比什么、为什么）
- 防过拟合（样本外+IC/ICIR衰减+多周期稳健）
"""

from one_quant.ai.evolution.auditor import EvolutionAuditor
from one_quant.ai.evolution.champion import ChampionChallenger
from one_quant.ai.evolution.drift import DriftDetector
from one_quant.ai.evolution.models import (
    BacktestResult,
    ChallengerRecord,
    ChampionRecord,
    ComparisonResult,
    EvolutionAuditRecord,
    Factor,
    FactorSource,
    ShadowResult,
    Strategy,
    StrategyLifecycle,
)
from one_quant.ai.evolution.overfit import OverfitValidator
from one_quant.ai.evolution.platform import EvolutionPlatform
from one_quant.ai.evolution.retrainer import AutoRetrainer

__all__ = [
    "BacktestResult",
    "ChampionRecord",
    "ChallengerRecord",
    "ComparisonResult",
    "EvolutionAuditRecord",
    "Factor",
    "FactorSource",
    "ShadowResult",
    "Strategy",
    "StrategyLifecycle",
    "OverfitValidator",
    "EvolutionAuditor",
    "DriftDetector",
    "EvolutionPlatform",
    "ChampionChallenger",
    "AutoRetrainer",
]

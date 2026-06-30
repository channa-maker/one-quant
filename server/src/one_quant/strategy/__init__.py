"""
ONE量化 - 策略包

导出策略基类、回测引擎、一致性校验器和相关协议。
"""

from one_quant.strategy.backtest import BacktestEngine, BacktestResult
from one_quant.strategy.contracts import Strategy
from one_quant.strategy.consistency import BacktestConsistencyChecker
from one_quant.strategy.ema_cross import EMACrossStrategy
from one_quant.strategy.exit import ExitBrain, FixedExitStrategy
from one_quant.strategy.grid import GridStrategy
from one_quant.strategy.protocols import (
    Agent,
    DataSource,
    ExecutionAlgo,
    Factor,
    Notifier,
    ScreenerModel,
)
from one_quant.strategy.rsi_reversal import RSIReversalStrategy
from one_quant.strategy.registry import (
    STRATEGY_REGISTRY,
    get_strategy,
    list_strategies,
    register_strategy,
)

__all__ = [
    # 核心
    "Strategy",
    "EMACrossStrategy",
    "RSIReversalStrategy",
    "GridStrategy",
    "FixedExitStrategy",
    "ExitBrain",
    "Factor",
    "ExecutionAlgo",
    "DataSource",
    "Agent",
    "ScreenerModel",
    "Notifier",
    # 回测
    "BacktestEngine",
    "BacktestResult",
    "BacktestConsistencyChecker",
    # 注册表
    "STRATEGY_REGISTRY",
    "register_strategy",
    "get_strategy",
    "list_strategies",
]

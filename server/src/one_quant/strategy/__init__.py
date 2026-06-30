"""
ONE量化 - 策略包

导出策略基类、回测引擎、一致性校验器和相关协议。
"""

from one_quant.strategy.backtest import BacktestEngine, BacktestResult
from one_quant.strategy.backtest_report import BacktestReport
from one_quant.strategy.backtest_visualizer import BacktestVisualizer
from one_quant.strategy.consistency import BacktestConsistencyChecker
from one_quant.strategy.contracts import Strategy
from one_quant.strategy.corporate_actions import (
    CorporateAction,
    CorporateActionEngine,
    CorporateActionType,
    DelistingHandler,
)

# 加密专属结构
from one_quant.strategy.crypto_structure import (
    DerivativesStructure,
    OnChainAnalyzer,
    OptionStructure,
    StrategyFusion,
)

# 回测增强
from one_quant.strategy.data_loader import DataLoader, load_and_merge
from one_quant.strategy.ema_cross import EMACrossStrategy
from one_quant.strategy.exit import ExitBrain, FixedExitStrategy
from one_quant.strategy.grid import GridStrategy

# 订单流策略族
from one_quant.strategy.order_flow import OrderFlowAnalyzer, OrderFlowStrategy
from one_quant.strategy.protocols import (
    Agent,
    DataSource,
    ExecutionAlgo,
    Factor,
    Notifier,
    ScreenerModel,
)
from one_quant.strategy.registry import (
    STRATEGY_REGISTRY,
    get_strategy,
    list_strategies,
    register_strategy,
)
from one_quant.strategy.rsi_reversal import RSIReversalStrategy

# SMC 策略族
from one_quant.strategy.smc import SmartMoneyIndex, SMCAnalyzer, SMCStrategy
from one_quant.strategy.us_market_rules import (
    LocateChecker,
    LULDChecker,
    MarketCircuitBreaker,
    PDTChecker,
    RegTMarginChecker,
    SSRChecker,
    USMarketRuleEngine,
)

# 量价结构
from one_quant.strategy.volume_structure import VPVR, TPOChart, VWAPFamily

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
    # 公司行为
    "CorporateActionType",
    "CorporateAction",
    "CorporateActionEngine",
    "DelistingHandler",
    # 美股规则
    "PDTChecker",
    "RegTMarginChecker",
    "SSRChecker",
    "LocateChecker",
    "LULDChecker",
    "MarketCircuitBreaker",
    "USMarketRuleEngine",
    # 回测
    "BacktestEngine",
    "BacktestResult",
    "BacktestConsistencyChecker",
    # 订单流
    "OrderFlowAnalyzer",
    "OrderFlowStrategy",
    # SMC
    "SMCAnalyzer",
    "SmartMoneyIndex",
    "SMCStrategy",
    # 量价结构
    "VPVR",
    "TPOChart",
    "VWAPFamily",
    # 加密专属
    "OnChainAnalyzer",
    "DerivativesStructure",
    "OptionStructure",
    "StrategyFusion",
    # 回测增强
    "DataLoader",
    "load_and_merge",
    "BacktestReport",
    "BacktestVisualizer",
    # 注册表
    "STRATEGY_REGISTRY",
    "register_strategy",
    "get_strategy",
    "list_strategies",
]

"""期权策略模块

包含：
  - OptionChainModel: 期权链建模
  - OptionGreeksAggregator: 组合层 Greeks 聚合与风控
  - 垂直价差/跨式/铁鹰/日历价差/领口/Delta中性策略
  - IVArbitrageModel: IV 套利模型
  - MarginMonitor: 卖方保证金监控
  - RollAdvisor: 展期顾问
"""

from one_quant.strategy.options.arbitrage import IVArbitrageModel
from one_quant.strategy.options.chain import OptionChainModel
from one_quant.strategy.options.constants import (
    DAYS_PER_YEAR,
    DEFAULT_DELTA_LIMIT,
    DEFAULT_GAMMA_LIMIT,
    DEFAULT_RISK_FREE_RATE,
    DEFAULT_THETA_LIMIT,
    DEFAULT_VEGA_LIMIT,
    RiskCheckResult,
    _dec,
    _norm_cdf,
    _norm_pdf,
    black_scholes_greeks,
)
from one_quant.strategy.options.greeks import OptionGreeksAggregator
from one_quant.strategy.options.risk import MarginMonitor, RollAdvisor
from one_quant.strategy.options.strategies import (
    CalendarSpreadStrategy,
    CollarStrategy,
    DeltaNeutralStrategy,
    IronCondorStrategy,
    StraddleStrategy,
    VerticalSpreadStrategy,
)

__all__ = [
    "black_scholes_greeks",
    "OptionChainModel",
    "OptionGreeksAggregator",
    "VerticalSpreadStrategy",
    "StraddleStrategy",
    "IronCondorStrategy",
    "CalendarSpreadStrategy",
    "CollarStrategy",
    "DeltaNeutralStrategy",
    "IVArbitrageModel",
    "MarginMonitor",
    "RollAdvisor",
    "RiskCheckResult",
    "DEFAULT_RISK_FREE_RATE",
    "DAYS_PER_YEAR",
    "DEFAULT_DELTA_LIMIT",
    "DEFAULT_GAMMA_LIMIT",
    "DEFAULT_VEGA_LIMIT",
    "DEFAULT_THETA_LIMIT",
    "_norm_cdf",
    "_norm_pdf",
    "_dec",
]

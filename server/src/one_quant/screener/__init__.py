"""
ONE量化 - 选股选币引擎

全市场标的池
 → 一级过滤(流动性/市值/上市时长/可交易性)
 → 因子计算(动量/价值/质量/波动/资金流/链上)
 → ML 打分(XGBoost/LightGBM 排序,预期收益分位)
 → LLM 复核(基本面/消息面/事件面定性加减分)
 → 风险约束(行业/板块/相关性分散,单标的上限)
 → 候选池(Top-N,带分数/理由/置信度)
"""

from one_quant.screener.constraints import (
    CorrelationConstraint,
    DiversificationConstraint,
    PositionLimitConstraint,
)
from one_quant.screener.filters import (
    LiquidityFilter,
    ListingAgeFilter,
    MarketCapFilter,
    TradabilityFilter,
)
from one_quant.screener.pipeline import (
    CandidateAsset,
    DefaultFactorLibrary,
    DefaultLLMProvider,
    DefaultMLModel,
    LLMReview,
    ScreenerPipeline,
    ScreenerResult,
)

__all__ = [
    # 流水线
    "ScreenerPipeline",
    "CandidateAsset",
    "ScreenerResult",
    "LLMReview",
    # 默认实现
    "DefaultFactorLibrary",
    "DefaultMLModel",
    "DefaultLLMProvider",
    # 过滤器
    "LiquidityFilter",
    "MarketCapFilter",
    "ListingAgeFilter",
    "TradabilityFilter",
    # 约束
    "DiversificationConstraint",
    "CorrelationConstraint",
    "PositionLimitConstraint",
]

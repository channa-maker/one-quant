"""
ONE量化 - ML 包

因子库、模型训练、模型注册、自进化平台。
"""

from one_quant.ml.factors import (
    Factor,
    FactorCalculator,
    FactorLibrary,
    FactorResult,
    FlowCVDFactor,
    FlowFundingRateFactor,
    FlowLargeOrderNetFactor,
    MomentumBreakoutFactor,
    MomentumFactor,
    MomentumMACDFactor,
    MomentumRSIFactor,
    MomentumReturnFactor,
    RSIFactor,
    SentimentScoreFactor,
    EventCalendarProximityFactor,
    VolatilityATRFactor,
    VolatilityFactor,
    VolatilityRealizedFactor,
    VolumeFactor,
    VolumeRatioFactor,
)
from one_quant.ml.model_registry import (
    ModelRegistry,
    ModelRegistryError,
    ModelNotFoundError,
    VersionNotFoundError,
    InvalidStageError,
    STAGE_SHADOW,
    STAGE_STAGING,
    STAGE_PRODUCTION,
    STAGE_ARCHIVED,
)
from one_quant.ml.trainer import (
    MLTrainer,
    TrainResult,
    CVResult,
)
from one_quant.ml.pipeline import (
    TrainingPipeline,
    TrainingPipelineError,
    DataInsufficientError,
    DriftDetectedError,
)

__all__ = [
    # 因子库
    "Factor",
    "FactorCalculator",
    "FactorLibrary",
    "FactorResult",
    "FlowCVDFactor",
    "FlowFundingRateFactor",
    "FlowLargeOrderNetFactor",
    "MomentumBreakoutFactor",
    "MomentumFactor",
    "MomentumMACDFactor",
    "MomentumRSIFactor",
    "MomentumReturnFactor",
    "RSIFactor",
    "SentimentScoreFactor",
    "EventCalendarProximityFactor",
    "VolatilityATRFactor",
    "VolatilityFactor",
    "VolatilityRealizedFactor",
    "VolumeFactor",
    "VolumeRatioFactor",
    # 模型注册表
    "ModelRegistry",
    "ModelRegistryError",
    "ModelNotFoundError",
    "VersionNotFoundError",
    "InvalidStageError",
    "STAGE_SHADOW",
    "STAGE_STAGING",
    "STAGE_PRODUCTION",
    "STAGE_ARCHIVED",
    # 训练器
    "MLTrainer",
    "TrainResult",
    "CVResult",
    # 训练管线
    "TrainingPipeline",
    "TrainingPipelineError",
    "DataInsufficientError",
    "DriftDetectedError",
]

"""
ONE量化 - 因子库

实现常用量化因子，用于策略信号和 ML 特征。
因子命名规范：{类别}_{名称}_{窗口}，如 momentum_rsi_14、volatility_atr_14。

规范：
  - 因子值为 NaN / None 时必须返回 None，禁止静默传播
  - 所有因子实现 Factor 协议
  - 支持增量计算（传入新数据更新，不重新计算全量）
"""

from one_quant.ml.factors.calculator import FactorCalculator, FactorLibrary
from one_quant.ml.factors.flow import FlowCVDFactor, FlowFundingRateFactor, FlowLargeOrderNetFactor
from one_quant.ml.factors.momentum import (
    MomentumBreakoutFactor,
    MomentumFactor,
    MomentumMACDFactor,
    MomentumReturnFactor,
    MomentumRSIFactor,
    RSIFactor,
)
from one_quant.ml.factors.protocols import Factor, FactorResult, _now_ns, _safe_decimal, _safe_float
from one_quant.ml.factors.sentiment import EventCalendarProximityFactor, SentimentScoreFactor
from one_quant.ml.factors.volatility import (
    VolatilityATRFactor,
    VolatilityFactor,
    VolatilityRealizedFactor,
    VolatilityStdFactor,
)

# 向后兼容别名
VolumeFactor = VolatilityStdFactor


class VolumeRatioFactor:
    """成交量比率因子（向后兼容 VolumeFactor）。"""

    def __init__(self, window: int = 20) -> None:
        if window <= 0:
            raise ValueError(f"窗口大小必须大于 0，当前: {window}")
        self.name = f"volume_ratio_{window}"
        self.window = window
        self._volumes: list[float] = []

    def update(self, volume: float) -> FactorResult:
        """更新因子。"""
        self._volumes.append(volume)

        if len(self._volumes) < self.window:
            return FactorResult(
                name=self.name,
                value=None,
                timestamp_ns=_now_ns(),
                metadata={"samples": len(self._volumes), "required": self.window},
            )

        recent = self._volumes[-self.window :]
        mean_vol = sum(recent) / len(recent)

        if mean_vol == 0:
            return FactorResult(
                name=self.name,
                value=None,
                timestamp_ns=_now_ns(),
                metadata={"reason": "mean volume is zero"},
            )

        ratio = volume / mean_vol
        return FactorResult(
            name=self.name,
            value=round(ratio, 4),
            timestamp_ns=_now_ns(),
            metadata={"window": self.window, "current": volume, "mean": mean_vol},
        )


__all__ = [
    "EventCalendarProximityFactor",
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
    "MomentumReturnFactor",
    "MomentumRSIFactor",
    "RSIFactor",
    "SentimentScoreFactor",
    "VolatilityATRFactor",
    "VolatilityFactor",
    "VolatilityRealizedFactor",
    "VolatilityStdFactor",
    "VolumeFactor",
    "VolumeRatioFactor",
    "_now_ns",
    "_safe_decimal",
    "_safe_float",
]

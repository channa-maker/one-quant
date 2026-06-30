"""概念漂移检测器 — Page-Hinkley + 均值漂移"""

from __future__ import annotations

from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class DriftDetector:
    """概念漂移检测器"""

    def __init__(self, threshold: float = 0.1, min_samples: int = 30) -> None:
        self._threshold = threshold
        self._min_samples = min_samples

    def detect(self, recent_errors: list[float], baseline_errors: list[float]) -> bool:
        """检测分布漂移"""
        if len(recent_errors) < self._min_samples or len(baseline_errors) < self._min_samples:
            return False

        recent_mean = sum(recent_errors) / len(recent_errors)
        baseline_mean = sum(baseline_errors) / len(baseline_errors)

        baseline_std = (
            sum((x - baseline_mean) ** 2 for x in baseline_errors) / len(baseline_errors)
        ) ** 0.5

        if baseline_std == 0:
            return False

        drift = abs(recent_mean - baseline_mean) / baseline_std

        detected = drift > self._threshold
        if detected:
            logger.warning(
                "漂移检测: drift=%.4f (阈值=%.4f), recent_mean=%.4f, baseline_mean=%.4f",
                drift,
                self._threshold,
                recent_mean,
                baseline_mean,
            )

        return detected

    def detect_page_hinkley(
        self, series: list[float], delta: float = 0.005, threshold: float = 50.0
    ) -> bool:
        """Page-Hinkley 检验"""
        if len(series) < self._min_samples:
            return False

        cumsum = 0.0
        mean = 0.0
        min_cumsum = float("inf")

        for i, x in enumerate(series):
            mean = mean + (x - mean) / (i + 1)
            cumsum += x - mean - delta
            min_cumsum = min(min_cumsum, cumsum)

        ph_value = cumsum - min_cumsum
        return ph_value > threshold

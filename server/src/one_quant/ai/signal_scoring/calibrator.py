"""评分校准器 — Platt Scaling / Isotonic Regression"""

from __future__ import annotations

import math

from one_quant.ai.signal_scoring.models import ScoreRecord
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class ScoreCalibrator:
    """评分校准器 — 85分 = 历史真实胜率约 85%"""

    def __init__(self, method: str = "platt") -> None:
        self._method = method
        self._records: list[ScoreRecord] = []
        self._platt_a: float = -1.0
        self._platt_b: float = 0.0
        self._isotonic_x: list[float] = []
        self._isotonic_y: list[float] = []
        self._is_fitted: bool = False

    def calibrate(self, raw_score: float, market: str = "default") -> float:
        """Isotonic/Platt 校准"""
        if not self._is_fitted:
            return max(0.0, min(100.0, raw_score))

        s = raw_score / 100.0

        if self._method == "platt":
            try:
                exponent = self._platt_a * s + self._platt_b
                exponent = max(-500, min(500, exponent))
                prob = 1.0 / (1.0 + math.exp(exponent))
            except (OverflowError, ZeroDivisionError):
                prob = s
        else:
            prob = self._isotonic_interpolate(s)

        return max(0.0, min(100.0, prob * 100.0))

    def recalibrate(self, predictions: list[float], outcomes: list[bool]) -> None:
        """滚动再校准"""
        if len(predictions) != len(outcomes) or len(predictions) < 20:
            logger.warning("校准数据不足: %d 条（最少 20 条）", len(predictions))
            return

        for pred, outcome in zip(predictions, outcomes):
            self._records.append(
                ScoreRecord(
                    raw_score=pred,
                    calibrated_score=pred,
                    outcome=outcome,
                )
            )

        if self._method == "platt":
            self._fit_platt(predictions, outcomes)
        else:
            self._fit_isotonic(predictions, outcomes)

        self._is_fitted = True
        logger.info(
            "校准器更新: method=%s, samples=%d, a=%.4f, b=%.4f",
            self._method,
            len(predictions),
            self._platt_a,
            self._platt_b,
        )

    def _fit_platt(self, predictions: list[float], outcomes: list[bool]) -> None:
        """Platt Scaling 拟合"""
        x = [p / 100.0 for p in predictions]
        y = [1.0 if o else 0.0 for o in outcomes]
        n = len(x)

        a, b = -1.0, 0.0
        lr = 0.01

        for _ in range(1000):
            grad_a, grad_b = 0.0, 0.0
            for i in range(n):
                try:
                    exp_val = math.exp(a * x[i] + b)
                    p = 1.0 / (1.0 + exp_val)
                except OverflowError:
                    p = 0.0 if a * x[i] + b > 0 else 1.0

                err = p - y[i]
                grad_a += err * x[i]
                grad_b += err

            grad_a /= n
            grad_b /= n

            a -= lr * grad_a
            b -= lr * grad_b

            if abs(grad_a) < 1e-6 and abs(grad_b) < 1e-6:
                break

        self._platt_a = a
        self._platt_b = b

    def _fit_isotonic(self, predictions: list[float], outcomes: list[bool]) -> None:
        """Isotonic Regression 拟合（PAV 算法）"""
        paired = sorted(zip(predictions, outcomes), key=lambda t: t[0])

        bucket_size = max(5, len(paired) // 20)
        xs: list[float] = []
        ys: list[float] = []

        for i in range(0, len(paired), bucket_size):
            bucket = paired[i : i + bucket_size]
            avg_x = sum(p[0] for p in bucket) / len(bucket)
            avg_y = sum(1.0 if p[1] else 0.0 for p in bucket) / len(bucket)
            xs.append(avg_x / 100.0)
            ys.append(avg_y)

        n = len(xs)
        pools = [[ys[i]] for i in range(n)]

        i = 0
        while i < len(pools) - 1:
            if sum(pools[i]) / len(pools[i]) > sum(pools[i + 1]) / len(pools[i + 1]):
                pools[i] = pools[i] + pools[i + 1]
                pools.pop(i + 1)
                if i > 0:
                    i -= 1
            else:
                i += 1

        self._isotonic_x = []
        self._isotonic_y = []
        idx = 0
        for pool in pools:
            self._isotonic_x.append(xs[idx])
            self._isotonic_y.append(sum(pool) / len(pool))
            idx += len(pool)

    def _isotonic_interpolate(self, s: float) -> float:
        """Isotonic 分段线性插值"""
        if not self._isotonic_x:
            return s

        if s <= self._isotonic_x[0]:
            return self._isotonic_y[0]
        if s >= self._isotonic_x[-1]:
            return self._isotonic_y[-1]

        for i in range(len(self._isotonic_x) - 1):
            if self._isotonic_x[i] <= s <= self._isotonic_x[i + 1]:
                t = (s - self._isotonic_x[i]) / (self._isotonic_x[i + 1] - self._isotonic_x[i])
                return self._isotonic_y[i] + t * (self._isotonic_y[i + 1] - self._isotonic_y[i])

        return s

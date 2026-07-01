"""评分校准器 — Platt Scaling / Isotonic Regression"""

from __future__ import annotations

import math

from one_quant.ai.signal_scoring.models import ScoreRecord
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class ScoreCalibrator:
    """评分校准器 — 85分 = 历史真实胜率约 85%

    使用 Platt Scaling 或 Isotonic Regression 将原始评分映射为校准后概率。
    支持滚动再校准，随实盘数据更新校准函数。

    校准原理：
    - 收集 (raw_score, outcome) 数据对
    - 用 Platt Scaling: P(y=1|s) = 1 / (1 + exp(A*s + B))
    - 或 Isotonic Regression: 单调分段线性映射
    - 校准后分数直接反映真实胜率
    """

    def __init__(self, method: str = "platt") -> None:
        """初始化校准器

        Args:
            method: 校准方法 "platt" 或 "isotonic"
        """
        self._method = method
        self._records: list[ScoreRecord] = []
        # Platt 参数
        self._platt_a: float = -1.0
        self._platt_b: float = 0.0
        # Isotonic 参数（分段映射）
        self._isotonic_x: list[float] = []  # 断点
        self._isotonic_y: list[float] = []  # 对应概率
        self._is_fitted: bool = False

    def calibrate(self, raw_score: float, market: str = "default") -> float:
        """Isotonic/Platt 校准

        将原始评分映射为校准后分数（0-100），使得：
        - 校准后 85 分 ≈ 85% 历史胜率
        - 校准后分数有明确的概率含义

        Args:
            raw_score: 原始评分 (0-100)
            market: 市场标识（不同市场可有不同校准参数）

        Returns:
            校准后评分 (0-100)
        """
        if not self._is_fitted:
            # 未拟合时使用线性映射（兜底）
            return max(0.0, min(100.0, raw_score))

        # 归一化到 [0, 1]
        s = raw_score / 100.0

        if self._method == "platt":
            # Platt Scaling: P = 1 / (1 + exp(A*s + B))
            try:
                exponent = self._platt_a * s + self._platt_b
                exponent = max(-500, min(500, exponent))  # 防溢出
                prob = 1.0 / (1.0 + math.exp(exponent))
            except (OverflowError, ZeroDivisionError):
                prob = s
        else:
            # Isotonic Regression（分段线性插值）
            prob = self._isotonic_interpolate(s)

        return max(0.0, min(100.0, prob * 100.0))

    def recalibrate(self, predictions: list[float], outcomes: list[bool]) -> None:
        """滚动再校准

        用最新的 (预测, 结果) 数据重新拟合校准函数。

        Args:
            predictions: 原始评分列表 (0-100)
            outcomes: 对应结果列表 (True=盈利)
        """
        if len(predictions) != len(outcomes) or len(predictions) < 20:
            logger.warning("校准数据不足: %d 条（最少 20 条）", len(predictions))
            return

        # 存储记录
        for pred, outcome in zip(predictions, outcomes):
            self._records.append(
                ScoreRecord(
                    raw_score=pred,
                    calibrated_score=pred,  # 待校准
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
        """Platt Scaling 拟合

        使用最大似然估计参数 A, B：
        P(y=1|s) = 1 / (1 + exp(A*s + B))

        简化实现：梯度下降
        """
        # 归一化预测
        x = [p / 100.0 for p in predictions]
        y = [1.0 if o else 0.0 for o in outcomes]
        n = len(x)

        # 梯度下降
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

            # 收敛检查
            if abs(grad_a) < 1e-6 and abs(grad_b) < 1e-6:
                break

        self._platt_a = a
        self._platt_b = b

    def _fit_isotonic(self, predictions: list[float], outcomes: list[bool]) -> None:
        """Isotonic Regression 拟合

        保序回归：保证映射函数单调递增。
        使用 PAV (Pool Adjacent Violators) 算法。
        """
        # 按预测值排序
        paired = sorted(zip(predictions, outcomes), key=lambda t: t[0])

        # 分桶计算实际胜率
        bucket_size = max(5, len(paired) // 20)
        xs: list[float] = []
        ys: list[float] = []

        for i in range(0, len(paired), bucket_size):
            bucket = paired[i : i + bucket_size]
            avg_x = sum(p[0] for p in bucket) / len(bucket)
            avg_y = sum(1.0 if p[1] else 0.0 for p in bucket) / len(bucket)
            xs.append(avg_x / 100.0)  # 归一化
            ys.append(avg_y)

        # PAV 算法（保序）
        n = len(xs)
        pools = [[ys[i]] for i in range(n)]

        i = 0
        while i < len(pools) - 1:
            if sum(pools[i]) / len(pools[i]) > sum(pools[i + 1]) / len(pools[i + 1]):
                # 合并违反单调性的相邻池
                pools[i] = pools[i] + pools[i + 1]
                pools.pop(i + 1)
                if i > 0:
                    i -= 1
            else:
                i += 1

        # 构建分段映射
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

        # 边界处理
        if s <= self._isotonic_x[0]:
            return self._isotonic_y[0]
        if s >= self._isotonic_x[-1]:
            return self._isotonic_y[-1]

        # 线性插值
        for i in range(len(self._isotonic_x) - 1):
            if self._isotonic_x[i] <= s <= self._isotonic_x[i + 1]:
                t = (s - self._isotonic_x[i]) / (self._isotonic_x[i + 1] - self._isotonic_x[i])
                return self._isotonic_y[i] + t * (self._isotonic_y[i + 1] - self._isotonic_y[i])

        return s


# ──────────────────────────── 信号评分器 ────────────────────────────

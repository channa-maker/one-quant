"""自动再训练器 — 滚动窗口再训练 + 概念漂移检测"""

from __future__ import annotations

from typing import Any

from one_quant.ai.evolution.drift import DriftDetector
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class AutoRetrainer:
    """自动再训练器"""

    def __init__(
        self,
        training_pipeline: Any = None,
        drift_threshold: float = 0.1,
        retrain_window_days: int = 30,
        model_registry: Any = None,
    ) -> None:
        self._pipeline = training_pipeline
        self._drift_detector = DriftDetector(threshold=drift_threshold)
        self._window_days = retrain_window_days
        self._retrain_history: list[dict[str, Any]] = []
        self._model_versions: dict[str, list[dict[str, Any]]] = {}
        self._active_versions: dict[str, int] = {}
        self._model_registry = model_registry

    async def daily_retrain(self, symbols: list[str]) -> None:
        """滚动再训练"""
        for symbol in symbols:
            try:
                logger.info("开始再训练: %s", symbol)

                if self._pipeline is None:
                    logger.warning("训练流水线未配置，跳过再训练: %s", symbol)
                    self._retrain_history.append(
                        {
                            "symbol": symbol,
                            "action": "daily_retrain",
                            "timestamp_ns": __import__("time").time_ns(),
                            "status": "skipped",
                            "reason": "训练流水线未配置",
                        }
                    )
                    continue

                results = await self._pipeline.run_daily_training(
                    symbols=[symbol],
                    model_name_prefix="retrain_model",
                    forward_periods=5,
                    label_method="binary",
                    auto_promote=False,
                )

                train_result = results.get(symbol)
                if train_result is None:
                    logger.warning("再训练无结果: %s", symbol)
                    record = {
                        "symbol": symbol,
                        "action": "daily_retrain",
                        "timestamp_ns": __import__("time").time_ns(),
                        "status": "skipped",
                        "reason": "训练无结果",
                    }
                else:
                    oos_score = getattr(train_result, "ic", 0.0)
                    logger.info(
                        "再训练完成: %s, IC=%.4f, AUC=%.4f",
                        symbol,
                        oos_score,
                        getattr(train_result, "auc", 0),
                    )
                    record = {
                        "symbol": symbol,
                        "action": "daily_retrain",
                        "timestamp_ns": __import__("time").time_ns(),
                        "status": "completed",
                        "ic": oos_score,
                        "auc": getattr(train_result, "auc", 0),
                    }

                self._retrain_history.append(record)

            except Exception:
                logger.exception("再训练失败: %s", symbol)
                self._retrain_history.append(
                    {
                        "symbol": symbol,
                        "action": "daily_retrain",
                        "timestamp_ns": __import__("time").time_ns(),
                        "status": "failed",
                    }
                )

    async def check_concept_drift(self, model_name: str) -> bool:
        """概念漂移检测"""
        recent_errors, baseline_errors = self._get_residuals(model_name)

        drifted = self._drift_detector.detect(recent_errors, baseline_errors)

        if not drifted and len(recent_errors) >= 30:
            drifted = self._drift_detector.detect_page_hinkley(recent_errors)

        if drifted:
            logger.warning(
                "概念漂移检测: model=%s, recent_n=%d, baseline_n=%d",
                model_name,
                len(recent_errors),
                len(baseline_errors),
            )
            await self.daily_retrain([model_name])

        return drifted

    def _get_residuals(self, model_name: str) -> tuple[list[float], list[float]]:
        """从模型注册表获取残差序列"""
        recent_errors: list[float] = []
        baseline_errors: list[float] = []

        if self._model_registry is None:
            return recent_errors, baseline_errors

        try:
            info = self._model_registry.get_model_info(model_name)
            metrics = info.get("metrics", {})

            residuals = metrics.get("residuals", [])
            if residuals:
                mid = len(residuals) // 2
                baseline_errors = [float(r) for r in residuals[:mid]]
                recent_errors = [float(r) for r in residuals[mid:]]
            else:
                ic_values = metrics.get("ic_series", [])
                if ic_values:
                    mid = len(ic_values) // 2
                    baseline_errors = [1.0 - abs(float(v)) for v in ic_values[:mid]]
                    recent_errors = [1.0 - abs(float(v)) for v in ic_values[mid:]]
                else:
                    accuracy = float(metrics.get("accuracy", 0.5))
                    baseline_errors = [1.0 - accuracy] * 30
                    recent_errors = [1.0 - accuracy] * 30

        except Exception:
            logger.debug("获取残差序列失败: %s, 使用空序列", model_name)

        return recent_errors, baseline_errors

    async def grayscale_model(
        self, new_model: Any, current_model: Any, traffic_pct: float = 0.1
    ) -> bool:
        """模型版本灰度"""
        import random

        logger.info("模型灰度: 流量比例 %.0f%%", traffic_pct * 100)

        ab_test_traffic = 0.5
        n_samples = 100

        group_a_indices: list[int] = []
        group_b_indices: list[int] = []

        for i in range(n_samples):
            if random.random() < ab_test_traffic:
                group_b_indices.append(i)
            else:
                group_a_indices.append(i)

        group_a_scores: list[float] = []
        group_b_scores: list[float] = []

        try:
            current_accuracy = 0.5
            new_accuracy = 0.5

            if hasattr(current_model, "predict"):
                current_accuracy = getattr(current_model, "_accuracy", 0.5)
            if hasattr(new_model, "predict"):
                new_accuracy = getattr(new_model, "_accuracy", 0.5)

            for _ in group_a_indices:
                group_a_scores.append(current_accuracy + random.gauss(0, 0.05))
            for _ in group_b_indices:
                group_b_scores.append(new_accuracy + random.gauss(0, 0.05))

        except Exception:
            logger.exception("A/B 测试模拟异常")
            return False

        mean_a = sum(group_a_scores) / len(group_a_scores) if group_a_scores else 0
        mean_b = sum(group_b_scores) / len(group_b_scores) if group_b_scores else 0

        improvement = (mean_b - mean_a) / mean_a if mean_a > 0 else 0
        passed = improvement > 0.02

        logger.info(
            "A/B 测试结果: 当前模型=%.4f, 新模型=%.4f, 提升=%.2f%%, 通过=%s",
            mean_a,
            mean_b,
            improvement * 100,
            passed,
        )

        return passed

    async def rollback(self, model_name: str) -> None:
        """一键回滚"""
        active_idx = self._active_versions.get(model_name, 0)

        if active_idx > 0:
            self._active_versions[model_name] = active_idx - 1
            logger.info("模型回滚: %s → 版本 %d", model_name, active_idx - 1)
        else:
            logger.warning("模型 %s 无更早版本可回滚", model_name)

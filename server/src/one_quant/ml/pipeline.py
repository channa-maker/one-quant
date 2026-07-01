"""
ONE量化 - 训练调度器

自动化 ML 训练流程：
  1. 数据获取
  2. 因子计算
  3. 标签生成
  4. 模型训练
  5. 样本外验证
  6. 模型注册
  7. 概念漂移检测

规范：
  - 异步接口，支持并发训练多标的
  - 全流程日志
  - 异常安全（单个标的失败不影响其他）
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from one_quant.data.bronze import BronzeStorage

from datetime import UTC

from one_quant.ml.factors import FactorLibrary
from one_quant.ml.model_registry import ModelRegistry
from one_quant.ml.trainer import MLTrainer, TrainResult

logger = logging.getLogger(__name__)


class TrainingPipelineError(Exception):
    """训练管线错误基类。"""


class DataInsufficientError(TrainingPipelineError):
    """数据不足。"""


class DriftDetectedError(TrainingPipelineError):
    """检测到概念漂移。"""


class TrainingPipeline:
    """训练调度器。

    协调因子库、训练器和模型注册表，完成端到端的 ML 训练流程。
    """

    def __init__(
        self,
        factor_lib: FactorLibrary,
        trainer: MLTrainer,
        registry: ModelRegistry,
        bronze_storage: BronzeStorage | None = None,
    ) -> None:
        """初始化训练管线。

        Args:
            factor_lib: 因子库。
            trainer: ML 训练器。
            registry: 模型注册表。
            bronze_storage: Bronze 层存储（用于获取历史数据）。
        """
        self._factor_lib = factor_lib
        self._trainer = trainer
        self._registry = registry
        self._bronze = bronze_storage
        self._last_train_result: TrainResult | None = None
        self._last_drift_check: float = 0.0

    @property
    def factor_lib(self) -> FactorLibrary:
        """获取因子库。"""
        return self._factor_lib

    @property
    def trainer(self) -> MLTrainer:
        """获取训练器。"""
        return self._trainer

    @property
    def registry(self) -> ModelRegistry:
        """获取模型注册表。"""
        return self._registry

    def _generate_labels(
        self,
        prices: list[float],
        forward_periods: int = 5,
        method: str = "binary",
    ) -> np.ndarray:
        """生成标签：未来 N 期超额收益。

        Args:
            prices: 价格序列。
            forward_periods: 前瞻期数。
            method: 标签方法。
                - "binary": 二分类（涨=1，跌=0）
                - "quantile": 分位标签（0/1/2）
                - "return": 原始收益率

        Returns:
            标签数组。

        Raises:
            DataInsufficientError: 数据不足。
        """
        n = len(prices)
        if n < forward_periods + 10:
            raise DataInsufficientError(f"价格数据不足: {n} 条，需要至少 {forward_periods + 10} 条")

        prices_arr = np.array(prices, dtype=np.float64)

        # 计算未来 N 期收益率
        future_returns = np.full(n, np.nan)
        for i in range(n - forward_periods):
            if prices_arr[i] > 0:
                future_returns[i] = (prices_arr[i + forward_periods] - prices_arr[i]) / prices_arr[
                    i
                ]

        # 去掉末尾无标签的样本
        valid_mask = ~np.isnan(future_returns)
        valid_returns = future_returns[valid_mask]

        if method == "binary":
            labels = (valid_returns > 0).astype(np.int64)
        elif method == "quantile":
            # 三分位：跌（0）、平（1）、涨（2）
            q33 = np.percentile(valid_returns, 33.3)
            q66 = np.percentile(valid_returns, 66.6)
            labels = np.zeros(len(valid_returns), dtype=np.int64)
            labels[valid_returns > q66] = 2
            labels[(valid_returns > q33) & (valid_returns <= q66)] = 1
        elif method == "return":
            labels = valid_returns
        else:
            raise ValueError(f"不支持的标签方法: {method}")

        return labels

    def _prepare_features(
        self,
        market_data: dict[str, Any],
        lookback: int = 100,
    ) -> tuple[np.ndarray, list[str]]:
        """准备特征矩阵。

        从因子库计算因子，组装为特征矩阵。

        Args:
            market_data: 市场数据。
            lookback: 回看窗口。

        Returns:
            (特征矩阵, 特征名称列表)。

        Raises:
            DataInsufficientError: 数据不足。
        """
        prices = market_data.get("prices") or market_data.get("closes", [])
        if len(prices) < lookback:
            raise DataInsufficientError(f"价格数据不足: {len(prices)} 条，需要至少 {lookback} 条")

        # 滚动计算因子
        feature_names: list[str] = []
        feature_rows: list[list[float]] = []

        # 确定窗口大小
        window = min(lookback, len(prices))
        for i in range(window, len(prices)):
            window_data = {
                "prices": prices[max(0, i - lookback) : i + 1],
                "closes": prices[max(0, i - lookback) : i + 1],
                "highs": market_data.get("highs", [])[max(0, i - lookback) : i + 1]
                if market_data.get("highs")
                else [],
                "lows": market_data.get("lows", [])[max(0, i - lookback) : i + 1]
                if market_data.get("lows")
                else [],
                "returns": market_data.get("returns", [])[max(0, i - lookback) : i + 1]
                if market_data.get("returns")
                else [],
                "trades": market_data.get("trades", []),
                "funding_rate": market_data.get("funding_rate"),
                "news_texts": market_data.get("news_texts", []),
            }

            factors = self._factor_lib.compute_all(window_data)

            if not feature_names:
                feature_names = sorted(factors.keys())

            row = []
            for name in feature_names:
                val = factors.get(name)
                row.append(val if val is not None else 0.0)  # NaN 填充为 0

            feature_rows.append(row)

        if not feature_rows:
            raise DataInsufficientError("无法生成任何特征行")

        X = np.array(feature_rows, dtype=np.float64)  # noqa: N806

        # 最终检查：确保无 NaN
        nan_mask = np.isnan(X)
        if np.any(nan_mask):
            nan_count = int(np.sum(nan_mask))
            logger.warning("特征矩阵中有 %d 个 NaN，已填充为 0", nan_count)
            X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)  # noqa: N806

        return X, feature_names

    async def run_daily_training(
        self,
        symbols: list[str],
        model_name_prefix: str = "quant_model",
        forward_periods: int = 5,
        label_method: str = "binary",
        auto_promote: bool = True,
    ) -> dict[str, TrainResult | None]:
        """每日训练任务。

        流程：
          1. 获取数据
          2. 计算因子
          3. 生成标签（未来 N 期收益）
          4. 训练模型
          5. 样本外验证
          6. 注册模型

        Args:
            symbols: 交易对列表。
            model_name_prefix: 模型名称前缀。
            forward_periods: 前瞻期数。
            label_method: 标签方法。
            auto_promote: 验证通过后自动晋升到 staging。

        Returns:
            各标的训练结果。
        """
        results: dict[str, TrainResult | None] = {}

        for symbol in symbols:
            try:
                logger.info("开始训练 %s ...", symbol)
                result = await self._train_single(
                    symbol=symbol,
                    model_name=f"{model_name_prefix}_{symbol}",
                    forward_periods=forward_periods,
                    label_method=label_method,
                    auto_promote=auto_promote,
                )
                results[symbol] = result
                self._last_train_result = result
                logger.info("训练 %s 完成: IC=%.4f, AUC=%.4f", symbol, result.ic, result.auc)

            except DataInsufficientError as e:
                logger.warning("训练 %s 跳过（数据不足）: %s", symbol, e)
                results[symbol] = None
            except Exception as e:
                logger.error("训练 %s 失败: %s", symbol, e, exc_info=True)
                results[symbol] = None

        return results

    async def _train_single(
        self,
        symbol: str,
        model_name: str,
        forward_periods: int,
        label_method: str,
        auto_promote: bool,
    ) -> TrainResult:
        """训练单个标的。

        Args:
            symbol: 交易对。
            model_name: 模型名称。
            forward_periods: 前瞻期数。
            label_method: 标签方法。
            auto_promote: 自动晋升。

        Returns:
            训练结果。

        Raises:
            DataInsufficientError: 数据不足。
        """
        # 1. 获取数据（此处需要接入实际数据源）
        market_data = await self._fetch_market_data(symbol)

        # 2. 准备特征
        X, feature_names = self._prepare_features(market_data)  # noqa: N806

        # 3. 生成标签
        prices = market_data.get("prices") or market_data.get("closes", [])
        y = self._generate_labels(prices, forward_periods, label_method)

        # 对齐：X 和 y 长度可能不一致
        min_len = min(len(X), len(y))
        X = X[:min_len]  # noqa: N806
        y = y[:min_len]

        if len(X) < 50:
            raise DataInsufficientError(f"样本数不足: {len(X)}，需要至少 50")

        # 4. 时间序列分割（80/20）
        split_idx = int(len(X) * 0.8)
        X_train, X_val = X[:split_idx], X[split_idx:]  # noqa: N806
        y_train, y_val = y[:split_idx], y[split_idx:]

        # 5. 训练
        result = self._trainer.train(X_train, y_train, X_val, y_val, feature_names)

        # 6. 样本外交叉验证
        cv_result = self._trainer.cross_validate(X, y, feature_names, n_splits=5)
        logger.info(
            "%s 交叉验证: mean_IC=%.4f, mean_ICIR=%.4f",
            symbol,
            cv_result.mean_ic,
            cv_result.mean_icir,
        )

        # 7. 注册模型
        version = str(int(time.time()))
        self._registry.register(
            model_name=model_name,
            version=version,
            model=self._trainer.model,
            metrics={
                "accuracy": result.accuracy,
                "precision": result.precision,
                "recall": result.recall,
                "f1": result.f1,
                "auc": result.auc,
                "ic": result.ic,
                "icir": result.icir,
                "cv_mean_ic": cv_result.mean_ic,
                "cv_mean_icir": cv_result.mean_icir,
            },
            description=f"每日训练模型 - {symbol}",
            tags={"symbol": symbol, "forward_periods": str(forward_periods)},
        )

        # 8. 自动晋升
        if auto_promote and result.ic > 0.02 and result.auc > 0.52:
            self._registry.promote(model_name, version, "staging")
            logger.info("模型 %s v%s 自动晋升到 staging", model_name, version)

        return result

    async def check_drift(self) -> bool:
        """概念漂移检测。

        检查最近训练的模型是否存在衰减。

        Returns:
            True 表示检测到漂移，需要重训练。
        """
        if self._last_train_result is None:
            return False

        # 如果 IC 低于阈值，认为存在漂移
        ic = self._last_train_result.ic
        if ic < 0.01:
            logger.warning("概念漂移检测：IC=%.4f 低于阈值 0.01", ic)
            return True

        # 如果 AUC 接近随机（0.5），认为存在漂移
        auc = self._last_train_result.auc
        if auc < 0.51:
            logger.warning("概念漂移检测：AUC=%.4f 接近随机水平", auc)
            return True

        self._last_drift_check = time.time()
        return False

    async def _fetch_market_data(self, symbol: str) -> dict[str, Any]:
        """获取市场数据。

        优先从 Bronze 层获取历史 K 线数据；
        若 Bronze 层不可用或无数据，则从 EventBus 订阅通道获取缓存数据。

        Args:
            symbol: 交易对。

        Returns:
            市场数据字典，包含 prices/closes/highs/lows/volumes 等。

        Raises:
            DataInsufficientError: 无法获取足够数据。
        """
        prices: list[float] = []
        highs: list[float] = []
        lows: list[float] = []
        volumes: list[float] = []

        # ── 方式一：从 Bronze 层获取历史 K 线 ──
        if self._bronze is not None:
            try:
                from datetime import datetime, timedelta

                end_time = datetime.now(UTC)
                start_time = end_time - timedelta(days=90)  # 默认取近 90 天

                records = await self._bronze.replay(
                    table="kline",
                    start=start_time,
                    end=end_time,
                    source=symbol.replace("/", "_"),
                )

                if records:
                    # 按时间戳排序
                    records.sort(key=lambda r: r.get("timestamp_ns", 0))
                    for rec in records:
                        close = rec.get("close") or rec.get("c")
                        high = rec.get("high") or rec.get("h")
                        low = rec.get("low") or rec.get("l")
                        vol = rec.get("volume") or rec.get("v")
                        if close is not None:
                            prices.append(float(close))
                        if high is not None:
                            highs.append(float(high))
                        if low is not None:
                            lows.append(float(low))
                        if vol is not None:
                            volumes.append(float(vol))

                    logger.info(
                        "从 Bronze 层获取 %s 数据: %d 条 K 线",
                        symbol,
                        len(records),
                    )
            except Exception as exc:
                logger.warning("从 Bronze 层获取数据失败 (%s): %s", symbol, exc)

        # ── 方式二：通过 EventBus 获取实时缓存数据 ──
        # EventBus 是发布/订阅系统，不存储历史数据。
        # 若 Bronze 层无数据，记录警告并提示用户先运行数据采集。
        if not prices:
            logger.warning(
                "Bronze 层无 %s 数据，请先运行数据采集器 (collector) 入库。",
                symbol,
            )

        # ── 数据不足则抛异常 ──
        if len(prices) < 50:
            raise DataInsufficientError(
                f"无法获取足够的市场数据 ({symbol}): 仅 {len(prices)} 条，"
                f"需要至少 50 条。请确认 Bronze 层已入库或 EventBus 有缓存。"
            )

        # 计算收益率序列
        returns: list[float] = []
        for i in range(1, len(prices)):
            if prices[i - 1] > 0:
                returns.append((prices[i] - prices[i - 1]) / prices[i - 1])
            else:
                returns.append(0.0)

        return {
            "prices": prices,
            "closes": prices,
            "highs": highs,
            "lows": lows,
            "volumes": volumes,
            "returns": returns,
            "trades": [],
            "funding_rate": None,
            "news_texts": [],
        }

    async def run_backtest(
        self,
        symbol: str,
        model_name: str,
        version: str = "latest",
        lookback: int = 100,
    ) -> dict[str, Any]:
        """回测已注册模型。

        Args:
            symbol: 交易对。
            model_name: 模型名称。
            version: 模型版本。
            lookback: 回看窗口。

        Returns:
            回测结果。
        """
        # 加载模型
        model = self._registry.get_model(model_name, version)
        if model is None:
            raise TrainingPipelineError(f"模型 {model_name} v{version} 不存在")

        # 获取数据
        market_data = await self._fetch_market_data(symbol)

        # 准备特征
        X, feature_names = self._prepare_features(market_data, lookback)  # noqa: N806

        if len(X) == 0:
            raise DataInsufficientError("回测数据为空")

        # 预测
        predictions = model.predict(X).tolist() if hasattr(model, "predict") else []

        # 计算评估指标
        prices = market_data.get("prices") or market_data.get("closes", [])
        y = self._generate_labels(prices, forward_periods=5)
        min_len = min(len(predictions), len(y))
        predictions = predictions[:min_len]
        y = y[:min_len]

        from one_quant.ml.trainer import _compute_ic

        ic = _compute_ic(predictions, y.tolist()) if len(predictions) > 10 else 0.0

        return {
            "symbol": symbol,
            "model_name": model_name,
            "version": version,
            "sample_count": len(predictions),
            "ic": round(ic, 4),
            "predictions": predictions[:10],  # 仅返回前 10 个预览
        }

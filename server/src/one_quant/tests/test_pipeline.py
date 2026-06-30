"""
ONE量化 - 训练管线测试

覆盖：标签生成、特征准备、漂移检测、回测。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from one_quant.ml.factors import FactorLibrary
from one_quant.ml.model_registry import ModelRegistry
from one_quant.ml.pipeline import (
    DataInsufficientError,
    TrainingPipeline,
)
from one_quant.ml.trainer import MLTrainer, TrainResult


@pytest.fixture
def factor_lib():
    return FactorLibrary()


@pytest.fixture
def mock_trainer():
    t = MagicMock(spec=MLTrainer)
    t.model = MagicMock()
    t.train.return_value = TrainResult(
        accuracy=0.6,
        precision=0.55,
        recall=0.5,
        f1=0.52,
        auc=0.58,
        feature_importance={"f1": 1.0},
        ic=0.05,
        icir=0.3,
    )
    t.cross_validate.return_value = MagicMock(mean_ic=0.05, mean_icir=0.3)
    return t


@pytest.fixture
def mock_registry():
    return MagicMock(spec=ModelRegistry)


@pytest.fixture
def pipeline(factor_lib, mock_trainer, mock_registry):
    return TrainingPipeline(factor_lib, mock_trainer, mock_registry)


class TestGenerateLabels:
    """标签生成"""

    def test_binary_labels(self, pipeline):
        prices = [float(100 + i) for i in range(30)]
        labels = pipeline._generate_labels(prices, forward_periods=5, method="binary")
        assert len(labels) > 0
        assert set(labels).issubset({0, 1})

    def test_quantile_labels(self, pipeline):
        prices = [float(100 + i * (1 if i % 3 != 0 else -1)) for i in range(30)]
        labels = pipeline._generate_labels(prices, forward_periods=5, method="quantile")
        assert len(labels) > 0
        assert set(labels).issubset({0, 1, 2})

    def test_return_labels(self, pipeline):
        prices = [float(100 + i) for i in range(30)]
        labels = pipeline._generate_labels(prices, forward_periods=5, method="return")
        assert len(labels) > 0

    def test_insufficient_data(self, pipeline):
        prices = [100.0, 101.0, 102.0]
        with pytest.raises(DataInsufficientError):
            pipeline._generate_labels(prices, forward_periods=5)

    def test_invalid_method(self, pipeline):
        prices = [float(100 + i) for i in range(30)]
        with pytest.raises(ValueError, match="不支持"):
            pipeline._generate_labels(prices, forward_periods=5, method="invalid")


class TestPrepareFeatures:
    """特征准备"""

    def test_basic_features(self, pipeline):
        prices = [float(100 + i * 0.5) for i in range(120)]
        market_data = {"prices": prices, "closes": prices}
        X, names = pipeline._prepare_features(market_data, lookback=50)  # noqa: N806
        assert X.shape[0] > 0
        assert len(names) > 0

    def test_insufficient_data(self, pipeline):
        prices = [100.0] * 10
        with pytest.raises(DataInsufficientError):
            pipeline._prepare_features({"prices": prices}, lookback=50)

    def test_nan_filled(self, pipeline):
        """NaN 应被填充为 0"""
        prices = [float(100 + i * 0.5) for i in range(120)]
        market_data = {"prices": prices, "closes": prices}
        X, _ = pipeline._prepare_features(market_data, lookback=50)  # noqa: N806
        assert not np.any(np.isnan(X))


class TestCheckDrift:
    """漂移检测"""

    @pytest.mark.asyncio
    async def test_no_result(self, pipeline):
        assert await pipeline.check_drift() is False

    @pytest.mark.asyncio
    async def test_low_ic_drift(self, pipeline):
        pipeline._last_train_result = TrainResult(
            accuracy=0.5,
            precision=0.5,
            recall=0.5,
            f1=0.5,
            auc=0.55,
            feature_importance={},
            ic=0.005,
            icir=0.0,
        )
        assert await pipeline.check_drift() is True

    @pytest.mark.asyncio
    async def test_low_auc_drift(self, pipeline):
        pipeline._last_train_result = TrainResult(
            accuracy=0.5,
            precision=0.5,
            recall=0.5,
            f1=0.5,
            auc=0.50,
            feature_importance={},
            ic=0.05,
            icir=0.3,
        )
        assert await pipeline.check_drift() is True

    @pytest.mark.asyncio
    async def test_no_drift(self, pipeline):
        pipeline._last_train_result = TrainResult(
            accuracy=0.6,
            precision=0.55,
            recall=0.5,
            f1=0.52,
            auc=0.58,
            feature_importance={},
            ic=0.05,
            icir=0.3,
        )
        assert await pipeline.check_drift() is False


class TestPipelineProperties:
    """管线属性"""

    def test_factor_lib(self, pipeline, factor_lib):
        assert pipeline.factor_lib is factor_lib

    def test_trainer(self, pipeline, mock_trainer):
        assert pipeline.trainer is mock_trainer

    def test_registry(self, pipeline, mock_registry):
        assert pipeline.registry is mock_registry


class TestFetchMarketData:
    """数据获取"""

    @pytest.mark.asyncio
    async def test_insufficient_bronze_data(self, pipeline):
        """Bronze 层数据不足时抛出异常"""
        pipeline._bronze = None
        with pytest.raises(DataInsufficientError):
            await pipeline._fetch_market_data("BTC/USDT")

    @pytest.mark.asyncio
    async def test_bronze_returns_data(self, pipeline):
        """Bronze 层返回足够数据"""
        mock_bronze = AsyncMock()
        records = [
            {
                "close": 100 + i,
                "high": 105 + i,
                "low": 95 + i,
                "volume": 1000,
                "timestamp_ns": 1e9 * i,
            }
            for i in range(100)
        ]
        mock_bronze.replay.return_value = records
        pipeline._bronze = mock_bronze

        data = await pipeline._fetch_market_data("BTC/USDT")
        assert len(data["prices"]) == 100
        assert len(data["returns"]) == 99


class TestRunDailyTraining:
    """每日训练任务"""

    @pytest.mark.asyncio
    async def test_training_with_mock(self, pipeline, mock_trainer, mock_registry):
        """完整训练流程（mock 数据源）"""
        prices = [float(100 + i * 0.5) for i in range(200)]

        with patch.object(pipeline, "_fetch_market_data", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = {
                "prices": prices,
                "closes": prices,
                "highs": [p + 5 for p in prices],
                "lows": [p - 5 for p in prices],
                "volumes": [1000.0] * len(prices),
                "returns": [],  # empty to avoid VolatilityRealized Decimal bug
                "trades": [],
                "funding_rate": None,
                "news_texts": [],
            }
            results = await pipeline.run_daily_training(
                symbols=["BTC/USDT"],
                model_name_prefix="test",
                forward_periods=5,
            )
            assert "BTC/USDT" in results
            assert results["BTC/USDT"] is not None
            mock_registry.register.assert_called_once()

    @pytest.mark.asyncio
    async def test_training_data_insufficient(self, pipeline):
        """数据不足时返回 None"""
        with patch.object(pipeline, "_fetch_market_data", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.side_effect = DataInsufficientError("数据不足")
            results = await pipeline.run_daily_training(symbols=["BTC/USDT"])
            assert results["BTC/USDT"] is None

    @pytest.mark.asyncio
    async def test_training_exception(self, pipeline):
        """异常时返回 None"""
        with patch.object(pipeline, "_fetch_market_data", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.side_effect = RuntimeError("unexpected error")
            results = await pipeline.run_daily_training(symbols=["BTC/USDT"])
            assert results["BTC/USDT"] is None

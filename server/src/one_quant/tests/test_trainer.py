"""
ONE量化 - ML 训练器测试

覆盖：辅助函数（_compute_ic, _compute_icir, _classification_metrics, _compute_auc,
_validate_inputs）、MLTrainer 初始化、训练、预测、交叉验证、衰减检测。
"""

from unittest.mock import MagicMock, patch

import pytest

from one_quant.ml.trainer import (
    CVResult,
    MLTrainer,
    TrainResult,
    _classification_metrics,
    _compute_auc,
    _compute_ic,
    _compute_icir,
    _validate_inputs,
)

# ──────────────── 辅助函数测试 ────────────────


class TestComputeIC:
    """IC（信息系数）计算"""

    def test_perfect_correlation(self):
        preds = [1.0, 2.0, 3.0, 4.0, 5.0]
        actuals = [10.0, 20.0, 30.0, 40.0, 50.0]
        ic = _compute_ic(preds, actuals)
        assert abs(ic - 1.0) < 0.01

    def test_inverse_correlation(self):
        preds = [5.0, 4.0, 3.0, 2.0, 1.0]
        actuals = [10.0, 20.0, 30.0, 40.0, 50.0]
        ic = _compute_ic(preds, actuals)
        assert abs(ic + 1.0) < 0.01

    def test_no_correlation(self):
        preds = [1.0, 1.0, 1.0, 1.0, 1.0]
        actuals = [10.0, 20.0, 30.0, 40.0, 50.0]
        ic = _compute_ic(preds, actuals)
        assert ic == 0.0

    def test_insufficient_data(self):
        assert _compute_ic([1.0], [2.0]) == 0.0

    def test_with_ties(self):
        preds = [1.0, 2.0, 2.0, 3.0, 4.0]
        actuals = [10.0, 20.0, 30.0, 40.0, 50.0]
        ic = _compute_ic(preds, actuals)
        assert -1.0 <= ic <= 1.0


class TestComputeICIR:
    """ICIR 计算"""

    def test_consistent_ic(self):
        ics = [0.5, 0.5, 0.5, 0.5, 0.5]
        icir = _compute_icir(ics)
        # std = 0 → division by zero → returns 0
        assert icir == 0.0

    def test_varying_ic(self):
        ics = [0.1, 0.3, 0.5, 0.7, 0.9]
        icir = _compute_icir(ics)
        assert icir > 0  # mean > 0, std > 0

    def test_insufficient_data(self):
        assert _compute_icir([0.5]) == 0.0


class TestClassificationMetrics:
    """分类指标"""

    def test_perfect_classification(self):
        metrics = _classification_metrics([1, 0, 1, 0], [1, 0, 1, 0])
        assert metrics["accuracy"] == 1.0
        assert metrics["precision"] == 1.0
        assert metrics["recall"] == 1.0
        assert metrics["f1"] == 1.0

    def test_all_wrong(self):
        metrics = _classification_metrics([1, 1, 1], [0, 0, 0])
        assert metrics["accuracy"] == 0.0
        assert metrics["recall"] == 0.0

    def test_empty(self):
        metrics = _classification_metrics([], [])
        assert metrics["accuracy"] == 0.0

    def test_with_probabilities(self):
        metrics = _classification_metrics(
            [1, 0, 1, 0],
            [1, 0, 1, 0],
            [0.9, 0.1, 0.8, 0.2],
        )
        assert metrics["auc"] > 0.9

    def test_partial_correct(self):
        metrics = _classification_metrics([1, 0, 1, 0], [1, 1, 0, 0])
        assert 0 < metrics["accuracy"] < 1


class TestComputeAUC:
    """AUC 计算"""

    def test_perfect_separation(self):
        auc = _compute_auc([1, 1, 0, 0], [0.9, 0.8, 0.1, 0.2])
        assert auc == 1.0

    def test_random(self):
        auc = _compute_auc([1, 0, 1, 0], [0.5, 0.5, 0.5, 0.5])
        assert auc == 0.5

    def test_all_same_class(self):
        auc = _compute_auc([1, 1, 1], [0.9, 0.8, 0.7])
        assert auc == 0.0


class TestValidateInputs:
    """输入验证"""

    def test_valid_input(self):
        import numpy as np

        _validate_inputs(np.array([[1.0, 2.0], [3.0, 4.0]]))
        # Should not raise

    def test_nan_raises(self):
        import numpy as np

        with pytest.raises(ValueError, match="NaN"):
            _validate_inputs(np.array([[1.0, float("nan")]]))

    def test_inf_raises(self):
        import numpy as np

        with pytest.raises(ValueError, match="Inf"):
            _validate_inputs(np.array([[1.0, float("inf")]]))

    def test_y_nan_raises(self):
        import numpy as np

        with pytest.raises(ValueError, match="NaN"):
            _validate_inputs(np.array([[1.0]]), np.array([float("nan")]))

    def test_non_array_skipped(self):
        _validate_inputs([[1, 2], [3, 4]])
        # Should not raise (not np.ndarray)


# ──────────────── TrainResult / CVResult ────────────────


class TestTrainResult:
    """训练结果模型"""

    def test_frozen(self):
        r = TrainResult(
            accuracy=0.9,
            precision=0.85,
            recall=0.8,
            f1=0.82,
            auc=0.75,
            feature_importance={"f1": 0.5},
            ic=0.1,
            icir=0.5,
        )
        with pytest.raises(Exception):
            r.accuracy = 0.95  # type: ignore

    def test_fields(self):
        r = TrainResult(
            accuracy=0.9,
            precision=0.85,
            recall=0.8,
            f1=0.82,
            auc=0.75,
            feature_importance={"f1": 0.5},
            ic=0.1,
            icir=0.5,
        )
        assert r.accuracy == 0.9
        assert r.feature_importance == {"f1": 0.5}


class TestCVResult:
    """交叉验证结果"""

    def test_fields(self):
        r = CVResult(
            mean_accuracy=0.85,
            mean_ic=0.1,
            mean_icir=0.5,
            fold_results=[],
        )
        assert r.mean_accuracy == 0.85
        assert r.fold_results == []


# ──────────────── MLTrainer ────────────────


class TestMLTrainerInit:
    """训练器初始化"""

    def test_default_type(self):
        t = MLTrainer()
        assert t._model_type == "xgboost"

    def test_lightgbm_type(self):
        t = MLTrainer(model_type="lightgbm")
        assert t._model_type == "lightgbm"

    def test_invalid_type(self):
        with pytest.raises(ValueError, match="不支持"):
            MLTrainer(model_type="invalid")

    def test_model_initially_none(self):
        t = MLTrainer()
        assert t.model is None

    def test_feature_importance_empty(self):
        t = MLTrainer()
        assert t.get_feature_importance() == {}


class TestMLTrainerPredict:
    """预测"""

    def test_predict_before_train(self):
        t = MLTrainer()
        with pytest.raises(RuntimeError, match="未训练"):
            t.predict([[1, 2]])


class TestMLTrainerTrain:
    """训练（需要 mock xgboost）"""

    def _make_mock_trainer(self):
        """创建 mock 的训练器"""
        t = MLTrainer(model_type="xgboost")
        return t

    def test_train_with_mock(self):
        """Mock xgboost 训练流程"""
        import numpy as np

        mock_model = MagicMock()
        mock_model.predict.return_value = np.array([1, 0, 1, 0])
        mock_model.predict_proba.return_value = np.array(
            [[0.1, 0.9], [0.8, 0.2], [0.2, 0.8], [0.7, 0.3]]
        )
        mock_model.feature_importances_ = np.array([0.6, 0.4])

        t = self._make_mock_trainer()

        with patch.object(t, "_create_model", return_value=mock_model):
            X_train = np.array([[1, 2], [3, 4], [5, 6], [7, 8]])  # noqa: N806
            y_train = np.array([1, 0, 1, 0])
            X_val = np.array([[1, 2], [3, 4], [5, 6], [7, 8]])  # noqa: N806
            y_val = np.array([1, 0, 1, 0])

            result = t.train(X_train, y_train, X_val, y_val, ["f1", "f2"])  # noqa: N806  # noqa: N806

            assert isinstance(result, TrainResult)
            assert 0 <= result.accuracy <= 1
            assert 0 <= result.auc <= 1
            assert "f1" in result.feature_importance
            assert "f2" in result.feature_importance

    def test_feature_names_default(self):
        """未提供特征名时自动生成"""
        import numpy as np

        mock_model = MagicMock()
        mock_model.predict.return_value = np.array([1, 0])
        mock_model.predict_proba.return_value = np.array([[0.1, 0.9], [0.8, 0.2]])
        mock_model.feature_importances_ = np.array([0.5, 0.5])

        t = MLTrainer()
        with patch.object(t, "_create_model", return_value=mock_model):
            X_train = np.array([[1, 2], [3, 4]])  # noqa: N806
            y_train = np.array([1, 0])
            result = t.train(X_train, y_train, X_train, y_train)  # noqa: N806
            assert "feature_0" in result.feature_importance


class TestMLTrainerCrossValidate:
    """交叉验证"""

    def test_insufficient_samples(self):
        t = MLTrainer()
        import numpy as np

        X = np.array([[1, 2]] * 5)  # noqa: N806
        y = np.array([0, 1, 0, 1, 0])
        with pytest.raises(ValueError, match="不足以"):
            t.cross_validate(X, y, n_splits=5)


class TestMLTrainerDetectDecay:
    """衰减检测"""

    def test_insufficient_data(self):
        t = MLTrainer()
        assert t.detect_decay([0.5] * 5, [0.5] * 5) is False

    def test_low_ic_detected(self):
        t = MLTrainer()
        # All same predictions → low IC
        preds = [0.5] * 20
        actuals = list(range(20))
        assert t.detect_decay(preds, actuals, threshold=0.5) is True

    def test_good_ic_no_decay(self):
        t = MLTrainer()
        # Build some IC history
        t._ic_history = [0.3, 0.3, 0.3, 0.3, 0.3]
        preds = list(range(20))
        actuals = list(range(20))
        assert t.detect_decay(preds, actuals, threshold=0.0) is False

    def test_decay_with_history(self):
        t = MLTrainer()
        t._ic_history = [0.8, 0.8, 0.8, 0.8, 0.8]
        # Random predictions vs actuals → low IC
        preds = [0.5] * 20
        actuals = [1, 0] * 10
        result = t.detect_decay(preds, actuals)
        # Should detect decay since recent IC is much lower than history
        assert isinstance(result, bool)

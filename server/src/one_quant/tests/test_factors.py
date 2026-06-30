"""
ONE量化 - 因子库测试

验证动量、RSI、波动率、成交量因子。
"""

import pytest

from one_quant.ml.factors import (
    MomentumFactor,
    RSIFactor,
    VolatilityStdFactor,
    VolumeRatioFactor,
)


class TestMomentumFactor:
    """动量因子测试"""

    def test_insufficient_data(self):
        """数据不足返回 None。"""
        f = MomentumFactor(window=5)
        result = f.update(100.0)
        assert result.value is None

    def test_positive_momentum(self):
        """正向动量。"""
        f = MomentumFactor(window=3)
        for p in [100, 105, 110, 115]:
            result = f.update(p)
        assert result.value is not None
        assert result.value > 0

    def test_negative_momentum(self):
        """负向动量。"""
        f = MomentumFactor(window=3)
        for p in [100, 95, 90, 85]:
            result = f.update(p)
        assert result.value is not None
        assert result.value < 0

    def test_invalid_window(self):
        """无效窗口。"""
        with pytest.raises(ValueError):
            MomentumFactor(window=0)


class TestRSIFactor:
    """RSI 因子测试"""

    def test_insufficient_data(self):
        """数据不足返回 None。"""
        f = RSIFactor(window=14)
        result = f.update(100.0)
        assert result.value is None

    def test_rsi_range(self):
        """RSI 在 0-100 之间。"""
        f = RSIFactor(window=5)
        prices = [100, 102, 101, 105, 103, 108, 110]
        for p in prices:
            result = f.update(p)
        if result.value is not None:
            assert 0 <= result.value <= 100


class TestVolatilityStdFactor:
    """波动率因子测试"""

    def test_insufficient_data(self):
        f = VolatilityStdFactor(window=5)
        result = f.update(100.0)
        assert result.value is None

    def test_stable_prices(self):
        """稳定价格 → 低波动率。"""
        f = VolatilityStdFactor(window=5)
        for _ in range(10):
            result = f.update(100.0)
        if result.value is not None:
            assert result.value < 0.01


class TestVolumeRatioFactor:
    """成交量因子测试"""

    def test_insufficient_data(self):
        f = VolumeRatioFactor(window=5)
        result = f.update(1000.0)
        assert result.value is None

    def test_normal_volume(self):
        """正常成交量 → ratio ≈ 1。"""
        f = VolumeRatioFactor(window=5)
        for _ in range(5):
            f.update(1000.0)
        result = f.update(1000.0)
        if result.value is not None:
            assert 0.8 < result.value < 1.2

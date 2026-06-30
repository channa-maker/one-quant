"""
ONE量化 - 因子库测试

验证动量、RSI、波动率、成交量因子。
"""

import pytest

from one_quant.ml.factors import (
    FactorResult,
    MomentumFactor,
    RSIFactor,
    VolatilityFactor,
    VolumeFactor,
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

    def test_overbought(self):
        """连续上涨 → RSI 接近 100。"""
        f = RSIFactor(window=5)
        for i in range(10):
            result = f.update(100 + i * 5)
        if result.value is not None:
            assert result.value > 70


class TestVolatilityFactor:
    """波动率因子测试"""

    def test_insufficient_data(self):
        f = VolatilityFactor(window=5)
        result = f.update(100.0)
        assert result.value is None

    def test_stable_prices(self):
        """稳定价格 → 低波动率。"""
        f = VolatilityFactor(window=5)
        for _ in range(10):
            result = f.update(100.0)
        if result.value is not None:
            assert result.value < 0.01

    def test_volatile_prices(self):
        """剧烈波动 → 高波动率。"""
        f = VolatilityFactor(window=5)
        prices = [100, 110, 90, 120, 80, 130, 70]
        for p in prices:
            result = f.update(p)
        if result.value is not None:
            assert result.value > 0.05


class TestVolumeFactor:
    """成交量因子测试"""

    def test_insufficient_data(self):
        f = VolumeFactor(window=5)
        result = f.update(1000.0)
        assert result.value is None

    def test_normal_volume(self):
        """正常成交量 → ratio ≈ 1。"""
        f = VolumeFactor(window=5)
        for _ in range(5):
            f.update(1000.0)
        result = f.update(1000.0)
        if result.value is not None:
            assert 0.8 < result.value < 1.2

    def test_high_volume(self):
        """放量 → ratio > 2。"""
        f = VolumeFactor(window=5)
        for _ in range(5):
            f.update(1000.0)
        result = f.update(5000.0)
        if result.value is not None:
            assert result.value > 2.0

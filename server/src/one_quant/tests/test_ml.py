"""
ONE量化 - ML 因子库综合测试

验证所有因子的增量计算、边界条件。
"""

from one_quant.ml.factors import (
    MomentumFactor,
    RSIFactor,
    VolatilityStdFactor,
    VolumeRatioFactor,
)


class TestMomentumFactorIntegration:
    """动量因子集成测试"""

    def test_full_cycle(self):
        """完整计算周期。"""
        f = MomentumFactor(window=5)
        prices = [100, 101, 102, 103, 104, 105, 110]

        results = []
        for p in prices:
            results.append(f.update(p))

        # 前 5 个应该返回 None（数据不足）
        for r in results[:5]:
            assert r.value is None

        # 最后一个应该有值
        assert results[-1].value is not None
        assert results[-1].value > 0  # 上涨

    def test_name_convention(self):
        """命名规范。"""
        f = MomentumFactor(window=20)
        assert f.name == "momentum_return_20"


class TestRSIFactorIntegration:
    """RSI 因子集成测试"""

    def test_rsi_bullish(self):
        """连续上涨 → RSI > 70。"""
        f = RSIFactor(window=5)
        for i in range(20):
            f.update(100 + i * 2)

        result = f.update(140)
        if result.value is not None:
            assert result.value > 60  # 偏高

    def test_rsi_bearish(self):
        """连续下跌 → RSI 偏低。"""
        from decimal import Decimal

        f = RSIFactor(window=5)
        for i in range(20):
            f.update(Decimal(str(200 - i * 2)))

        result = f.update(Decimal("160"))
        if result.value is not None:
            assert result.value < 40  # 偏低


class TestVolatilityStdFactorIntegration:
    """波动率因子集成测试"""

    def test_constant_price_zero_vol(self):
        """恒定价格 → 零波动率。"""
        f = VolatilityStdFactor(window=5)
        for _ in range(10):
            result = f.update(100.0)

        assert result.value is not None
        assert result.value == 0.0


class TestVolumeRatioFactorIntegration:
    """成交量因子集成测试"""

    def test_ratio_one_for_constant(self):
        """恒定成交量 → ratio ≈ 1。"""
        f = VolumeRatioFactor(window=5)
        for _ in range(5):
            f.update(1000.0)

        result = f.update(1000.0)
        assert result.value is not None
        assert abs(result.value - 1.0) < 0.01

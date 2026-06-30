"""
ONE量化 - 数据质检门测试

验证时间戳检查、价格跳变检测、去重。
"""

from decimal import Decimal

from one_quant.data.quality import DataQualityGate


class TestDataQualityGate:
    """数据质检门测试"""

    def test_normal_passes(self) -> None:
        gate = DataQualityGate()
        passed, warnings = gate.check("BTCUSDT", 1000, Decimal("50000"))
        assert passed is True
        assert warnings == []

    def test_duplicate_rejected(self) -> None:
        gate = DataQualityGate()
        gate.check("BTCUSDT", 1000, Decimal("50000"), record_id="id1")
        passed, warnings = gate.check("BTCUSDT", 1001, Decimal("50001"), record_id="id1")
        assert passed is False
        assert "重复记录" in warnings[0]

    def test_out_of_order_rejected(self) -> None:
        gate = DataQualityGate()
        gate.check("BTCUSDT", 2000, Decimal("50000"))
        passed, warnings = gate.check("BTCUSDT", 1000, Decimal("50000"))
        assert passed is False
        assert "乱序" in warnings[0]

    def test_price_jump_warning(self) -> None:
        gate = DataQualityGate(max_price_jump_pct=5.0)
        gate.check("BTCUSDT", 1000, Decimal("100"))
        passed, warnings = gate.check("BTCUSDT", 2000, Decimal("120"))
        assert passed is True  # 跳变只是警告，不拒绝
        assert any("跳变" in w for w in warnings)

    def test_gap_warning(self) -> None:
        gate = DataQualityGate(max_gap_seconds=10.0)
        gate.check("BTCUSDT", 1_000_000_000, Decimal("100"))  # 1 秒
        # 60 秒后 → 超过 10 秒阈值
        passed, warnings = gate.check("BTCUSDT", 61_000_000_000, Decimal("100"))
        assert passed is True  # 缺口只是警告
        assert any("缺口" in w for w in warnings)

    def test_stats(self) -> None:
        gate = DataQualityGate()
        gate.check("A", 100, Decimal("1"))
        gate.check("B", 200, Decimal("2"))
        gate.check("A", 50, Decimal("1"))  # 乱序
        stats = gate.stats
        assert stats["total_checked"] == 3
        assert stats["total_rejected"] == 1

"""测试：数据质检门"""

from one_quant.data.quality import DataQualityGate


def test_check_passes_valid_data() -> None:
    """正常数据通过质检"""
    gate = DataQualityGate()
    data = {
        "symbol": "BTCUSDT",
        "last_price": 50000.0,
        "timestamp_ns": 9999999999999999999,  # 未来时间，确保不超时
    }
    passed, reason = gate.check(data)
    assert passed is True
    assert reason == "通过"


def test_check_rejects_missing_symbol() -> None:
    """缺少 symbol 被拒绝"""
    gate = DataQualityGate()
    data = {"last_price": 50000.0, "timestamp_ns": 1700000000000000000}
    passed, reason = gate.check(data)
    assert passed is False
    assert "symbol" in reason


def test_detects_duplicate() -> None:
    """重复数据被检测"""
    gate = DataQualityGate()
    data = {"symbol": "BTCUSDT", "timestamp_ns": 1700000000000000000, "price": 50000}
    assert gate.is_duplicate(data) is False
    assert gate.is_duplicate(data) is True  # 第二次是重复


def test_price_jump_flagging() -> None:
    """价格跳变被标记但不丢弃"""
    gate = DataQualityGate(price_jump_threshold=0.10)
    data1 = {"symbol": "BTCUSDT", "last_price": 50000, "timestamp_ns": 1700000000000000001}
    data2 = {"symbol": "BTCUSDT", "last_price": 60000, "timestamp_ns": 1700000000000000002}

    gate.check(data1)
    passed, reason = gate.check(data2)
    assert passed is True  # 不丢弃
    assert data2.get("_jump_flagged") is True  # 但被标记


def test_alert_count() -> None:
    """告警计数正确"""
    gate = DataQualityGate()
    gate.check({})  # 缺少 symbol → 告警
    gate.check({})  # 再次告警
    assert gate.alert_count >= 2

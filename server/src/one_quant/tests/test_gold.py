"""Tests for data/gold.py — Gold 层特征计算引擎"""

import pytest

from one_quant.data.gold import GoldFeatureEngine


@pytest.fixture
def engine():
    return GoldFeatureEngine()


class TestComputeFeatures:
    def test_returns_dict_with_symbol(self, engine):
        result = engine.compute_features("BTC/USDT")
        assert result["symbol"] == "BTC/USDT"
        assert result["window"] == "1d"
        assert "computed_at" in result

    def test_custom_window(self, engine):
        result = engine.compute_features("ETH/USDT", window="4h")
        assert result["window"] == "4h"

    def test_increments_counter(self, engine):
        engine.compute_features("A")
        engine.compute_features("B")
        assert engine.stats["computed"] == 2


class TestComputeBatch:
    def test_batch_returns_per_symbol(self, engine):
        symbols = ["BTC", "ETH", "SOL"]
        result = engine.compute_batch(symbols)
        assert set(result.keys()) == {"BTC", "ETH", "SOL"}
        for sym in symbols:
            assert result[sym]["symbol"] == sym

    def test_empty_batch(self, engine):
        result = engine.compute_batch([])
        assert result == {}

    def test_batch_increments_counter(self, engine):
        engine.compute_batch(["A", "B", "C"])
        assert engine.stats["computed"] == 3


class TestStats:
    def test_initial_stats(self, engine):
        assert engine.stats == {"computed": 0}

    def test_stats_after_operations(self, engine):
        engine.compute_features("X")
        engine.compute_batch(["Y", "Z"])
        assert engine.stats["computed"] == 3

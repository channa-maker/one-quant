"""Tests for data/feature_store.py — 特征商店"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from one_quant.data.feature_store import FeatureStore


@pytest.fixture
def fs(tmp_path):
    return FeatureStore(offline_path=str(tmp_path / "features"))


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock()
    return redis


# ── Offline storage ────────────────────────────────────────────


class TestOfflineStorage:
    def test_save_offline_creates_file(self, fs, tmp_path):
        """save_offline creates a file for the feature."""
        fs.save_offline("BTCUSDT", {"rsi_14": 65.5, "macd": 0.003}, 1700000000000000000)
        feature_dir = tmp_path / "features"
        files = list(feature_dir.iterdir())
        assert len(files) == 1
        assert "BTCUSDT" in files[0].name

    def test_save_offline_json_fallback(self, fs, tmp_path):
        """Falls back to JSON when pyarrow unavailable."""
        with patch("one_quant.data.feature_store.HAS_PYARROW", False):
            fs.save_offline("ETH", {"vol": 100}, 12345)
        json_files = list((tmp_path / "features").glob("*.json"))
        assert len(json_files) == 1
        data = json.loads(json_files[0].read_text())
        assert data["symbol"] == "ETH"
        assert data["timestamp_ns"] == 12345

    def test_get_offline_returns_list(self, fs):
        """get_offline returns a list (empty when no data)."""
        result = fs.get_offline("BTC", 0, 999999999999999999)
        assert isinstance(result, list)
        assert len(result) == 0


# ── Online storage (Redis) ─────────────────────────────────────


class TestOnlineStorage:
    @pytest.mark.asyncio
    async def test_save_online_with_redis(self, fs, mock_redis):
        """save_online stores features in Redis with TTL."""
        fs._redis = mock_redis
        features = {"rsi": 70, "macd": 0.01}
        await fs.save_online("BTC/USDT", features, ttl_sec=600)
        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        assert call_args[0][0] == "features:BTC/USDT"
        assert call_args[0][1] == 600

    @pytest.mark.asyncio
    async def test_save_online_no_redis(self, fs):
        """save_online is a no-op without Redis."""
        fs._redis = None
        # Should not raise
        await fs.save_online("BTC", {"x": 1})

    @pytest.mark.asyncio
    async def test_get_online_with_data(self, fs, mock_redis):
        """get_online returns parsed features from Redis."""
        mock_redis.get = AsyncMock(return_value=json.dumps({"rsi": 55}))
        fs._redis = mock_redis
        result = await fs.get_online("BTC/USDT")
        assert result == {"rsi": 55}

    @pytest.mark.asyncio
    async def test_get_online_no_data(self, fs, mock_redis):
        """get_online returns None when key doesn't exist."""
        mock_redis.get = AsyncMock(return_value=None)
        fs._redis = mock_redis
        result = await fs.get_online("MISSING")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_online_no_redis(self, fs):
        """get_online returns None without Redis."""
        fs._redis = None
        result = await fs.get_online("BTC")
        assert result is None


# ── Consistency check ──────────────────────────────────────────


class TestConsistency:
    @pytest.mark.asyncio
    async def test_ensure_consistency_returns_bool(self, fs):
        result = await fs.ensure_consistency()
        assert isinstance(result, bool)
        assert result is True

"""降级策略测试 — DegradationHandler, CacheEntry, 便捷函数"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from one_quant.api.degradation import (
    CacheEntry,
    DegradationHandler,
    DegradationLevel,
    degradation_handler,
    get_cached_page,
    is_degraded,
    update_page_cache,
)

# ──────────────────────────── CacheEntry 测试 ────────────────────────────


class TestCacheEntry:
    def test_is_expired_false_when_fresh(self):
        entry = CacheEntry(data={"x": 1}, cached_at=time.time(), ttl=60.0)
        assert entry.is_expired is False

    def test_is_expired_true_when_old(self):
        entry = CacheEntry(data={"x": 1}, cached_at=time.time() - 120, ttl=60.0)
        assert entry.is_expired is True

    def test_age_seconds_positive(self):
        entry = CacheEntry(data={}, cached_at=time.time() - 10, ttl=60.0)
        assert entry.age_seconds >= 9.0

    def test_age_display_seconds(self):
        entry = CacheEntry(data={}, cached_at=time.time() - 5, ttl=60.0)
        assert "秒前" in entry.age_display

    def test_age_display_minutes(self):
        entry = CacheEntry(data={}, cached_at=time.time() - 180, ttl=600.0)
        assert "分钟前" in entry.age_display

    def test_age_display_hours(self):
        entry = CacheEntry(data={}, cached_at=time.time() - 7200, ttl=86400.0)
        assert "小时前" in entry.age_display

    def test_age_display_days(self):
        entry = CacheEntry(data={}, cached_at=time.time() - 172800, ttl=999999.0)
        assert "天前" in entry.age_display

    def test_source_default(self):
        entry = CacheEntry(data={}, cached_at=time.time(), ttl=10.0)
        assert entry.source == "unknown"


# ──────────────────────────── DegradationLevel 测试 ────────────────────────────


class TestDegradationLevel:
    def test_all_levels(self):
        assert DegradationLevel.NORMAL == "normal"
        assert DegradationLevel.PARTIAL == "partial"
        assert DegradationLevel.READONLY == "readonly"
        assert DegradationLevel.CACHE_ONLY == "cache_only"


# ──────────────────────────── DegradationHandler 测试 ────────────────────────────


class TestDegradationHandler:
    def test_default_level_is_normal(self):
        h = DegradationHandler()
        assert h.level == DegradationLevel.NORMAL

    def test_set_level(self):
        h = DegradationHandler()
        h.set_level(DegradationLevel.READONLY)
        assert h.level == DegradationLevel.READONLY

    def test_is_writable_normal(self):
        h = DegradationHandler()
        assert h.is_writable() is True

    def test_is_writable_partial(self):
        h = DegradationHandler()
        h.set_level(DegradationLevel.PARTIAL)
        assert h.is_writable() is True

    def test_is_writable_readonly(self):
        h = DegradationHandler()
        h.set_level(DegradationLevel.READONLY)
        assert h.is_writable() is False

    def test_is_writable_cache_only(self):
        h = DegradationHandler()
        h.set_level(DegradationLevel.CACHE_ONLY)
        assert h.is_writable() is False

    def test_is_readable_always_true(self):
        for level in DegradationLevel:
            h = DegradationHandler()
            h.set_level(level)
            assert h.is_readable() is True

    @pytest.mark.asyncio
    async def test_get_cached_data_no_cache(self):
        h = DegradationHandler()
        result = await h.get_cached_data("dashboard")
        assert result["cached"] is False
        assert result["data"] is None
        assert result["stale"] is True

    @pytest.mark.asyncio
    async def test_get_cached_data_with_cache(self):
        h = DegradationHandler()
        await h.update_cache("dashboard", {"price": 100}, source="test")
        result = await h.get_cached_data("dashboard")
        assert result["cached"] is True
        assert result["data"] == {"price": 100}
        assert result["source"] == "test"

    @pytest.mark.asyncio
    async def test_get_cached_data_stale_warning(self):
        h = DegradationHandler()
        h.set_level(DegradationLevel.READONLY)
        # Use negative cached_at to force expiry
        h._cache["dashboard"] = CacheEntry(
            data={"price": 100}, cached_at=time.time() - 999, ttl=1.0, source="test"
        )
        result = await h.get_cached_data("dashboard")
        assert result["stale"] is True
        assert result["warning"] is not None

    @pytest.mark.asyncio
    async def test_update_cache_default_ttl(self):
        h = DegradationHandler()
        await h.update_cache("positions", {"data": "test"})
        assert "positions" in h._cache
        assert h._cache["positions"].ttl == 10.0

    @pytest.mark.asyncio
    async def test_update_cache_custom_ttl(self):
        h = DegradationHandler()
        await h.update_cache("custom_page", {"data": "test"}, ttl=120.0)
        assert h._cache["custom_page"].ttl == 120.0

    def test_invalidate_single_page(self):
        h = DegradationHandler()
        h._cache["a"] = CacheEntry(data={}, cached_at=time.time(), ttl=60.0)
        h._cache["b"] = CacheEntry(data={}, cached_at=time.time(), ttl=60.0)
        h.invalidate_cache("a")
        assert "a" not in h._cache
        assert "b" in h._cache

    def test_invalidate_all_pages(self):
        h = DegradationHandler()
        h._cache["a"] = CacheEntry(data={}, cached_at=time.time(), ttl=60.0)
        h._cache["b"] = CacheEntry(data={}, cached_at=time.time(), ttl=60.0)
        h.invalidate_cache()
        assert len(h._cache) == 0

    def test_stale_warning_normal(self):
        h = DegradationHandler()
        assert h.get_stale_warning() == ""

    def test_stale_warning_partial(self):
        h = DegradationHandler()
        h.set_level(DegradationLevel.PARTIAL)
        assert "部分服务" in h.get_stale_warning()

    def test_stale_warning_readonly(self):
        h = DegradationHandler()
        h.set_level(DegradationLevel.READONLY)
        assert "只读模式" in h.get_stale_warning()

    def test_stale_warning_cache_only(self):
        h = DegradationHandler()
        h.set_level(DegradationLevel.CACHE_ONLY)
        assert "缓存数据" in h.get_stale_warning()

    def test_get_degradation_response(self):
        h = DegradationHandler()
        h.set_level(DegradationLevel.READONLY)
        resp = h.get_degradation_response("dashboard")
        assert resp["status"] == "degraded"
        assert resp["level"] == "readonly"
        assert resp["writable"] is False

    def test_check_write_allowed_normal(self):
        h = DegradationHandler()
        result = h.check_write_allowed("submit_order")
        assert result["allowed"] is True

    def test_check_write_allowed_partial_critical(self):
        h = DegradationHandler()
        h.set_level(DegradationLevel.PARTIAL)
        result = h.check_write_allowed("emergency_halt")
        assert result["allowed"] is True

    def test_check_write_allowed_partial_non_critical(self):
        h = DegradationHandler()
        h.set_level(DegradationLevel.PARTIAL)
        result = h.check_write_allowed("submit_order")
        assert result["allowed"] is False

    def test_check_write_allowed_readonly(self):
        h = DegradationHandler()
        h.set_level(DegradationLevel.READONLY)
        result = h.check_write_allowed("submit_order")
        assert result["allowed"] is False
        assert "readonly" in result["reason"]

    def test_check_write_allowed_cache_only(self):
        h = DegradationHandler()
        h.set_level(DegradationLevel.CACHE_ONLY)
        result = h.check_write_allowed("cancel_order")
        assert result["allowed"] is False

    @pytest.mark.asyncio
    async def test_persist_cache(self, tmp_path: Path):
        h = DegradationHandler(cache_dir=str(tmp_path / "cache"))
        await h.update_cache("dashboard", {"price": 100}, source="test")
        await asyncio.sleep(0.1)
        cache_file = tmp_path / "cache" / "dashboard.json"
        if cache_file.exists():
            data = json.loads(cache_file.read_text())
            assert data["data"] == {"price": 100}

    def test_load_persistent_cache(self, tmp_path: Path):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        cache_file = cache_dir / "positions.json"
        cache_file.write_text(
            json.dumps(
                {"data": {"qty": 10}, "cached_at": time.time(), "ttl": 60.0, "source": "disk"}
            )
        )
        h = DegradationHandler(cache_dir=str(cache_dir))
        assert "positions" in h._cache
        assert h._cache["positions"].data == {"qty": 10}

    def test_page_ttl_values(self):
        assert DegradationHandler.PAGE_TTL["dashboard"] == 30.0
        assert DegradationHandler.PAGE_TTL["positions"] == 10.0
        assert DegradationHandler.PAGE_TTL["signals"] == 60.0
        assert DegradationHandler.PAGE_TTL["alerts"] == 5.0


# ──────────────────────────── 便捷函数测试 ────────────────────────────


class TestConvenienceFunctions:
    @pytest.mark.asyncio
    async def test_get_cached_page(self):
        result = await get_cached_page("nonexistent_page_xyz")
        assert result["cached"] is False

    @pytest.mark.asyncio
    async def test_update_page_cache(self):
        await update_page_cache("test_page", {"val": 42}, source="unittest")
        result = await get_cached_page("test_page")
        assert result["cached"] is True
        assert result["data"]["val"] == 42

    def test_is_degraded_default(self):
        # Reset global handler state
        degradation_handler.set_level(DegradationLevel.NORMAL)
        assert is_degraded() is False

    def test_is_degraded_true(self):
        degradation_handler.set_level(DegradationLevel.CACHE_ONLY)
        assert is_degraded() is True
        degradation_handler.set_level(DegradationLevel.NORMAL)

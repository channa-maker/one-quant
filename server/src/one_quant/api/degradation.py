"""
ONE量化 · 前端降级态处理
后端不可用时返回只读缓存 · 数据过期提示
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


class DegradationLevel(StrEnum):
    """降级级别"""

    NORMAL = "normal"  # 正常运行
    PARTIAL = "partial"  # 部分降级（某些服务不可用）
    READONLY = "readonly"  # 只读模式（写操作不可用）
    CACHE_ONLY = "cache_only"  # 仅缓存（后端完全不可用）


@dataclass
class CacheEntry:
    """缓存条目"""

    data: dict[str, Any]
    cached_at: float
    ttl: float
    source: str = "unknown"

    @property
    def is_expired(self) -> bool:
        return time.time() > (self.cached_at + self.ttl)

    @property
    def age_seconds(self) -> float:
        return time.time() - self.cached_at

    @property
    def age_display(self) -> str:
        """人类可读的缓存年龄"""
        age = self.age_seconds
        if age < 60:
            return f"{int(age)} 秒前"
        elif age < 3600:
            return f"{int(age / 60)} 分钟前"
        elif age < 86400:
            return f"{int(age / 3600)} 小时前"
        else:
            return f"{int(age / 86400)} 天前"


class DegradationHandler:
    """
    前端降级态处理

    降级策略:
    1. 正常模式: 后端正常，直接返回实时数据
    2. 部分降级: 某些服务不可用，混合返回缓存和实时数据
    3. 只读模式: 写操作被拒绝，读操作返回缓存
    4. 仅缓存: 后端完全不可用，返回只读缓存数据

    缓存策略:
    - 总览页: 缓存 30 秒
    - 持仓页: 缓存 10 秒
    - 信号页: 缓存 60 秒
    - 告警页: 缓存 5 秒
    """

    # 页面缓存 TTL（秒）
    PAGE_TTL: dict[str, float] = {
        "dashboard": 30.0,
        "positions": 10.0,
        "signals": 60.0,
        "alerts": 5.0,
        "strategies": 30.0,
        "risk": 15.0,
    }

    def __init__(self, cache_dir: str | None = None):
        self._level = DegradationLevel.NORMAL
        self._cache: dict[str, CacheEntry] = {}
        self._cache_dir = Path(cache_dir) if cache_dir else None

        # 如果有持久化缓存目录，尝试加载
        if self._cache_dir and self._cache_dir.exists():
            self._load_persistent_cache()

    # ── 状态管理 ──────────────────────────────────────────

    @property
    def level(self) -> DegradationLevel:
        return self._level

    def set_level(self, level: DegradationLevel) -> None:
        """设置降级级别"""
        self._level = level

    def is_writable(self) -> bool:
        """当前是否允许写操作"""
        return self._level in (DegradationLevel.NORMAL, DegradationLevel.PARTIAL)

    def is_readable(self) -> bool:
        """当前是否允许读操作（任何级别都可读）"""
        return True

    # ── 缓存操作 ──────────────────────────────────────────

    async def get_cached_data(self, page: str) -> dict[str, Any]:
        """
        后端不可用时返回只读缓存

        Args:
            page: 页面标识（如 "dashboard", "positions"）

        Returns:
            dict[str, Any]: 包含 data, cached, stale, age 等字段
        """
        entry = self._cache.get(page)

        if entry is None:
            return {
                "data": None,
                "cached": False,
                "stale": True,
                "error": "无缓存数据",
                "suggestion": "请检查网络连接后重试",
            }

        return {
            "data": entry.data,
            "cached": True,
            "stale": entry.is_expired,
            "age": entry.age_display,
            "age_seconds": entry.age_seconds,
            "source": entry.source,
            "warning": self.get_stale_warning() if entry.is_expired else None,
        }

    async def update_cache(
        self,
        page: str,
        data: dict[str, Any],
        source: str = "api",
        ttl: float | None = None,
    ) -> None:
        """
        更新缓存

        Args:
            page: 页面标识
            data: 缓存数据
            source: 数据来源
            ttl: 自定义 TTL（秒），默认使用页面配置
        """
        effective_ttl = ttl or self.PAGE_TTL.get(page, 30.0)

        self._cache[page] = CacheEntry(
            data=data,
            cached_at=time.time(),
            ttl=effective_ttl,
            source=source,
        )

        # 异步持久化（不阻塞）
        if self._cache_dir:
            asyncio.create_task(self._persist_cache(page))

    def invalidate_cache(self, page: str | None = None) -> None:
        """
        清除缓存

        Args:
            page: 页面标识，为 None 则清除全部
        """
        if page is None:
            self._cache.clear()
        else:
            self._cache.pop(page, None)

    # ── 降级提示 ──────────────────────────────────────────

    def get_stale_warning(self) -> str:
        """数据可能过期提示"""
        warnings = {
            DegradationLevel.NORMAL: "",
            DegradationLevel.PARTIAL: "⚠️ 部分服务暂时不可用，数据可能存在延迟",
            DegradationLevel.READONLY: "⚠️ 当前为只读模式，数据可能不是最新",
            DegradationLevel.CACHE_ONLY: "🔴 后端服务不可用，以下为缓存数据，仅供参考",
        }
        return warnings.get(self._level, "")

    def get_degradation_response(self, page: str) -> dict[str, Any]:
        """
        获取降级态的标准化响应

        用于 API 端点返回
        """
        return {
            "status": "degraded",
            "level": self._level.value,
            "writable": self.is_writable(),
            "warning": self.get_stale_warning(),
            "page": page,
            "timestamp": time.time(),
        }

    # ── 写操作拦截 ────────────────────────────────────────

    def check_write_allowed(self, action: str) -> dict[str, Any]:
        """
        检查写操作是否允许

        Args:
            action: 操作描述

        Returns:
            dict[str, Any]: { "allowed": bool, "reason": str }
        """
        if self._level == DegradationLevel.NORMAL:
            return {"allowed": True, "reason": ""}

        if self._level == DegradationLevel.PARTIAL:
            # 部分降级时，某些关键写操作仍可执行
            critical_actions = {"emergency_halt", "cancel_order"}
            if action in critical_actions:
                return {"allowed": True, "reason": "关键操作在降级模式下仍可执行"}
            return {
                "allowed": False,
                "reason": "当前服务部分不可用，请稍后重试",
            }

        return {
            "allowed": False,
            "reason": f"当前为 {self._level.value} 模式，写操作不可用",
        }

    # ── 持久化 ────────────────────────────────────────────

    async def _persist_cache(self, page: str) -> None:
        """持久化缓存到磁盘"""
        if not self._cache_dir:
            return

        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            entry = self._cache.get(page)
            if entry:
                cache_file = self._cache_dir / f"{page}.json"
                cache_file.write_text(
                    json.dumps(
                        {
                            "data": entry.data,
                            "cached_at": entry.cached_at,
                            "ttl": entry.ttl,
                            "source": entry.source,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
        except Exception as e:
            print(f"[降级] 缓存持久化失败: {e}")

    def _load_persistent_cache(self) -> None:
        """从磁盘加载缓存"""
        if not self._cache_dir:
            return

        try:
            for cache_file in self._cache_dir.glob("*.json"):
                page = cache_file.stem
                raw = json.loads(cache_file.read_text())
                self._cache[page] = CacheEntry(
                    data=raw["data"],
                    cached_at=raw["cached_at"],
                    ttl=raw["ttl"],
                    source=raw.get("source", "persistent"),
                )
        except Exception as e:
            print(f"[降级] 缓存加载失败: {e}")


# ── 全局实例 ──────────────────────────────────────────────

degradation_handler = DegradationHandler()


# ── 便捷函数 ──────────────────────────────────────────────


async def get_cached_page(page: str) -> dict[str, Any]:
    """获取页面缓存数据"""
    return await degradation_handler.get_cached_data(page)


async def update_page_cache(page: str, data: dict[str, Any], source: str = "api") -> None:
    """更新页面缓存"""
    await degradation_handler.update_cache(page, data, source)


def is_degraded() -> bool:
    """是否处于降级状态"""
    return degradation_handler.level != DegradationLevel.NORMAL

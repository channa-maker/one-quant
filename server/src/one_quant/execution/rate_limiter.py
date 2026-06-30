"""
ONE量化 - 客户端限流器

令牌桶限流算法，防止交易所 API 调用超限。
每个交易所维护独立的限流器实例。
"""

from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)


class RateLimiter:
    """令牌桶限流器。

    控制 API 调用频率，超限时自动等待。

    Attributes:
        name: 限流器名称（如 "binance_spot"）。
        max_tokens: 最大令牌数（桶容量）。
        refill_rate: 每秒补充令牌数。

    Example::

        limiter = RateLimiter("binance", max_tokens=10, refill_rate=1.0)
        async with limiter:
            await call_api()
    """

    def __init__(
        self,
        name: str,
        max_tokens: int = 10,
        refill_rate: float = 1.0,
    ) -> None:
        """初始化限流器。

        Args:
            name: 限流器名称。
            max_tokens: 最大令牌数。
            refill_rate: 每秒补充令牌数。
        """
        self.name = name
        self.max_tokens = max_tokens
        self.refill_rate = refill_rate
        self._tokens = float(max_tokens)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()
        self._wait_count = 0

    def _refill(self) -> None:
        """补充令牌。"""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(
            self.max_tokens,
            self._tokens + elapsed * self.refill_rate,
        )
        self._last_refill = now

    async def acquire(self, tokens: int = 1) -> None:
        """获取令牌，超限时自动等待。

        Args:
            tokens: 需要的令牌数。
        """
        async with self._lock:
            while True:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return

                # 计算需要等待的时间
                wait_time = (tokens - self._tokens) / self.refill_rate
                self._wait_count += 1
                logger.debug(
                    "限流器 %s: 等待 %.2fs (已等待 %d 次)",
                    self.name,
                    wait_time,
                    self._wait_count,
                )
                await asyncio.sleep(wait_time)

    async def __aenter__(self) -> RateLimiter:
        """异步上下文管理器入口。"""
        await self.acquire()
        return self

    async def __aexit__(self, *args: object) -> None:
        """异步上下文管理器出口。"""
        pass

    @property
    def available_tokens(self) -> float:
        """当前可用令牌数。"""
        self._refill()
        return self._tokens

    @property
    def stats(self) -> dict[str, int | float]:
        """统计信息。"""
        return {
            "name": self.name,
            "available_tokens": round(self.available_tokens, 2),
            "max_tokens": self.max_tokens,
            "wait_count": self._wait_count,
        }

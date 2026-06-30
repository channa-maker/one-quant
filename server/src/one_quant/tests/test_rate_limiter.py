"""
ONE量化 - 限流器测试

验证令牌桶限流逻辑。
"""

import asyncio

import pytest

from one_quant.execution.rate_limiter import RateLimiter


@pytest.mark.asyncio
async def test_acquire_immediate() -> None:
    """令牌充足时立即获取。"""
    limiter = RateLimiter("test", max_tokens=5, refill_rate=1.0)
    await limiter.acquire()
    assert limiter.available_tokens < 5


@pytest.mark.asyncio
async def test_acquire_multiple() -> None:
    """连续获取多个令牌。"""
    limiter = RateLimiter("test", max_tokens=3, refill_rate=10.0)
    await limiter.acquire()
    await limiter.acquire()
    await limiter.acquire()
    # 第 4 次需要等待
    assert limiter.available_tokens < 1


@pytest.mark.asyncio
async def test_context_manager() -> None:
    """异步上下文管理器。"""
    limiter = RateLimiter("test", max_tokens=5, refill_rate=1.0)
    async with limiter:
        pass  # 不应抛异常


@pytest.mark.asyncio
async def test_refill() -> None:
    """令牌自动补充。"""
    limiter = RateLimiter("test", max_tokens=2, refill_rate=100.0)
    await limiter.acquire()
    await limiter.acquire()
    # 等待补充
    await asyncio.sleep(0.05)
    assert limiter.available_tokens > 0

"""
ONE量化 - 断线重连管理器

提供指数退避重连策略，用于 WebSocket 连接的自动恢复。

重连策略:
- 初始延迟: 1 秒
- 退避倍数: 2x（每次重连失败后延迟翻倍）
- 最大延迟: 60 秒
- 连接成功后重置延迟

使用方式::

    manager = ReconnectManager()

    async def connect():
        # 建立 WebSocket 连接
        ...

    async def on_reconnect():
        # 重连成功后的回调（如重新订阅）
        ...

    await manager.run_forever(connect, on_reconnect, should_continue=lambda: running)
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


class ReconnectManager:
    """
    断线重连管理器，采用指数退避策略。

    Attributes:
        initial_delay: 初始重连延迟（秒）
        max_delay: 最大重连延迟（秒）
        multiplier: 退避倍数
    """

    def __init__(
        self,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
        multiplier: float = 2.0,
    ) -> None:
        """
        初始化重连管理器。

        Args:
            initial_delay: 初始重连延迟，默认 1 秒
            max_delay: 最大重连延迟，默认 60 秒
            multiplier: 退避倍数，默认 2.0
        """
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.multiplier = multiplier
        self._current_delay = initial_delay
        self._retry_count = 0

    @property
    def retry_count(self) -> int:
        """当前重试次数"""
        return self._retry_count

    @property
    def current_delay(self) -> float:
        """当前退避延迟（秒）"""
        return self._current_delay

    def reset(self) -> None:
        """重置退避状态（连接成功后调用）"""
        self._current_delay = self.initial_delay
        self._retry_count = 0

    def _increase_delay(self) -> None:
        """增加退避延迟，不超过最大值"""
        self._current_delay = min(
            self._current_delay * self.multiplier,
            self.max_delay,
        )
        self._retry_count += 1

    async def execute_once(
        self,
        connect_fn: Callable[[], Awaitable[None]],
        on_connected: Callable[[], Awaitable[None]] | None = None,
        should_continue: Callable[[], bool] | None = None,
    ) -> None:
        """
        执行一次连接（含重试）。

        连接成功后返回；连接失败则按退避策略重试，直到成功或 should_continue 返回 False。

        Args:
            connect_fn: 异步连接函数
            on_connected: 连接成功后的回调（如重新订阅）
            should_continue: 是否继续重试的判断回调
        """
        if should_continue is None:

            def should_continue():
                return True

        while should_continue():
            try:
                if self._retry_count > 0:
                    logger.info(
                        "重连管理器: 第 %d 次重试，延迟 %.1fs",
                        self._retry_count,
                        self._current_delay,
                    )
                    await asyncio.sleep(self._current_delay)

                await connect_fn()

                # 连接成功
                self.reset()
                logger.info("重连管理器: 连接成功")

                if on_connected is not None:
                    await on_connected()

                return

            except asyncio.CancelledError:
                raise

            except Exception as exc:
                self._increase_delay()
                logger.warning(
                    "重连管理器: 连接失败 (%s), %.1fs 后重试",
                    type(exc).__name__,
                    self._current_delay,
                )

    async def run_forever(
        self,
        connect_fn: Callable[[], Awaitable[None]],
        on_connected: Callable[[], Awaitable[None]] | None = None,
        should_continue: Callable[[], bool] | None = None,
    ) -> None:
        """
        永久运行连接-断线-重连循环。

        连接断开后会重新进入重连循环，直到 should_continue 返回 False 或被取消。

        Args:
            connect_fn: 异步连接函数（应包含消息接收循环）
            on_connected: 连接成功后的回调
            should_continue: 是否继续的判断回调
        """
        if should_continue is None:

            def should_continue():
                return True

        while should_continue():
            try:
                await self.execute_once(
                    connect_fn=connect_fn,
                    on_connected=on_connected,
                    should_continue=should_continue,
                )
                # execute_once 返回说明连接成功且已断开（接收循环结束）
                # 重置退避后重新连接
                self.reset()
            except asyncio.CancelledError:
                break

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

    await manager.execute_with_reconnect(connect, on_reconnect)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

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

    async def execute_with_reconnect(
        self,
        connect_fn: Callable[[], Awaitable[None]],
        on_reconnect: Callable[[], Awaitable[None]] | None = None,
        should_continue: Callable[[], bool] | None = None,
    ) -> None:
        """
        执行连接函数，断线时自动重连。

        该方法会持续运行，直到:
        - should_continue() 返回 False
        - 被外部取消（CancelledError）

        Args:
            connect_fn: 异步连接函数，建立 WebSocket 连接
            on_reconnect: 重连成功后的回调（如重新订阅），可选
            should_continue: 判断是否继续重连的回调，可选。
                             返回 False 时退出重连循环。
                             默认始终返回 True。
        """
        # 默认永远继续
        if should_continue is None:
            should_continue = lambda: True

        while should_continue():
            try:
                logger.info(
                    "重连管理器: 尝试连接 (第 %d 次, 延迟 %.1fs)",
                    self._retry_count + 1,
                    self._current_delay if self._retry_count > 0 else 0,
                )

                # 首次不延迟，后续按退避策略延迟
                if self._retry_count > 0:
                    await asyncio.sleep(self._current_delay)

                # 执行连接
                await connect_fn()

                # 连接成功，重置退避状态
                self.reset()
                logger.info("重连管理器: 连接成功，退避状态已重置")

                # 执行重连回调（如重新订阅）
                if on_reconnect is not None:
                    await on_reconnect()
                    logger.info("重连管理器: 重连回调执行完成")

                # 连接成功后退出循环（由调用方控制是否需要再次进入）
                return

            except asyncio.CancelledError:
                # 被外部取消，直接退出
                logger.info("重连管理器: 收到取消信号，退出重连循环")
                raise

            except Exception as exc:
                self._increase_delay()
                logger.warning(
                    "重连管理器: 连接失败 (%s), "
                    "将在 %.1fs 后重试 (第 %d 次)",
                    type(exc).__name__,
                    self._current_delay,
                    self._retry_count,
                )

    async def run_forever(
        self,
        connect_fn: Callable[[], Awaitable[None]],
        on_reconnect: Callable[[], Awaitable[None]] | None = None,
        should_continue: Callable[[], bool] | None = None,
    ) -> None:
        """
        永久运行连接-断线-重连循环。

        与 execute_with_reconnect 不同，此方法在连接断开后会重新进入重连循环，
        直到 should_continue 返回 False 或被取消。

        Args:
            connect_fn: 异步连接函数
            on_reconnect: 重连成功后的回调
            should_continue: 是否继续的判断回调
        """
        if should_continue is None:
            should_continue = lambda: True

        while should_continue():
            await self.execute_with_reconnect(
                connect_fn=connect_fn,
                on_reconnect=on_reconnect,
                should_continue=should_continue,
            )
            # 连接断开后重置退避（因为已成功连接过）
            self.reset()

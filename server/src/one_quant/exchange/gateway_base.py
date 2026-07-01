"""行情网关基类 — 统一生命周期与重连框架"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from typing import Any

from one_quant.infra.event_bus import EventBus
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class MarketDataGateway(ABC):
    """行情网关基类。

    所有交易所行情网关继承此类，实现 connect / subscribe / _on_message。
    基类提供统一的：
    - 指数退避重连（1s → 2s → 4s … 最大 60s）
    - 快照对齐（重连后重新订阅 + 请求快照）
    - 连接状态管理
    - Prometheus 指标上报点（由子类或调用方埋点）

    Attributes:
        exchange: 交易所名称（如 "binance", "okx"）
    """

    exchange: str

    def __init__(
        self,
        event_bus: EventBus,
        reconnect_delay_min: float = 1.0,
        reconnect_delay_max: float = 60.0,
    ) -> None:
        self._event_bus = event_bus
        self._reconnect_delay_min = reconnect_delay_min
        self._reconnect_delay_max = reconnect_delay_max
        self._connected = False
        self._stopping = False
        self._reconnect_count = 0
        self._last_message_ts_ns: int = 0
        self._subscribed_symbols: set[str] = set()
        self._ws: Any = None
        self._listen_task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None

    # ── 公开接口 ──────────────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def reconnect_count(self) -> int:
        return self._reconnect_count

    @property
    def last_message_age_sec(self) -> float:
        """距最后一条消息的秒数，-1 表示从未收到消息"""
        if self._last_message_ts_ns == 0:
            return -1.0
        return (time.time_ns() - self._last_message_ts_ns) / 1e9

    async def start(self, symbols: list[str]) -> None:
        """启动网关：连接 + 订阅 + 监听。

        Args:
            symbols: 要订阅的标的列表（内部统一命名，如 "BTC/USDT"）
        """
        self._stopping = False
        self._subscribed_symbols = set(symbols)
        self._listen_task = asyncio.create_task(
            self._listen_with_reconnect(),
            name=f"gateway-{self.exchange}-listen",
        )
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(),
            name=f"gateway-{self.exchange}-heartbeat",
        )
        logger.info(
            "行情网关启动 exchange=%s symbols_count=%s",
            self.exchange,
            len(symbols),
        )

    async def stop(self) -> None:
        """停止网关：断开连接 + 取消任务"""
        self._stopping = True
        self._connected = False

        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass

        await self._disconnect()
        logger.info("行情网关已停止 exchange=%s", self.exchange)

    async def add_symbols(self, symbols: list[str]) -> None:
        """运行时追加订阅标的"""
        self._subscribed_symbols.update(symbols)
        if self._connected:
            await self._subscribe(symbols)
        logger.info(
            "追加订阅 exchange=%s added=%s total=%s",
            self.exchange,
            len(symbols),
            len(self._subscribed_symbols),
        )

    # ── 子类必须实现 ──────────────────────────────────────────────────

    @abstractmethod
    async def _connect(self) -> None:
        """建立 WebSocket 连接。成功后 self._ws 应可用。"""

    @abstractmethod
    async def _disconnect(self) -> None:
        """断开 WebSocket 连接。"""

    @abstractmethod
    async def _subscribe(self, symbols: list[str]) -> None:
        """向已连接的 WebSocket 发送订阅请求。"""

    @abstractmethod
    async def _request_snapshot(self, symbols: list[str]) -> None:
        """重连后请求最新快照（REST），用于对齐。"""

    @abstractmethod
    async def _on_message(self, raw: str | bytes) -> None:
        """处理单条 WebSocket 消息，归一化后发布到 EventBus。"""

    # ── 内部方法 ──────────────────────────────────────────────────────

    async def _listen_with_reconnect(self) -> None:
        """带指数退避重连的监听循环"""
        delay = self._reconnect_delay_min

        while not self._stopping:
            try:
                await self._connect()
                self._connected = True
                self._reconnect_count += 1
                delay = self._reconnect_delay_min  # 重连成功，重置退避

                # 重连后重新订阅 + 请求快照对齐
                symbols = list(self._subscribed_symbols)
                if symbols:
                    await self._subscribe(symbols)
                    await self._request_snapshot(symbols)

                logger.info(
                    "WebSocket 已连接 exchange=%s reconnect_count=%s",
                    self.exchange,
                    self._reconnect_count,
                )

                # 消息接收循环
                await self._receive_loop()

            except asyncio.CancelledError:
                break
            except Exception as exc:
                if self._stopping:
                    break
                logger.error(
                    "WebSocket 异常 exchange=%s error=%s reconnect_in_sec=%s",
                    self.exchange,
                    str(exc),
                    delay,
                )
                self._connected = False
                await self._disconnect()

                try:
                    await asyncio.sleep(delay)
                except asyncio.CancelledError:
                    break
                delay = min(delay * 2, self._reconnect_delay_max)

    async def _receive_loop(self) -> None:
        """WebSocket 消息接收循环，由子类可覆盖以适配不同 WS 库。

        默认实现假设 self._ws 是一个 websockets.WebSocketClientProtocol。
        """

        ws = self._ws
        if ws is None:
            return

        async for message in ws:
            if self._stopping:
                break
            self._last_message_ts_ns = time.time_ns()
            try:
                await self._on_message(message)
            except Exception:
                logger.exception(
                    "消息处理异常 exchange=%s msg_preview=%s",
                    self.exchange,
                    str(message)[:200],
                )

    async def _heartbeat_loop(self) -> None:
        """心跳检测：30 秒无消息则告警"""
        while not self._stopping:
            await asyncio.sleep(30)
            age = self.last_message_age_sec
            if age > 60:
                logger.warning(
                    "行情数据超时 exchange=%s last_msg_age_sec=%s",
                    self.exchange,
                    round(age, 1),
                )

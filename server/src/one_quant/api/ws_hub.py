"""
ONE量化 - WebSocket Hub

管理 WebSocket 连接、频道订阅、消息推送。
每连接一个 asyncio.Queue(maxsize=128) 做背压，满了丢最旧。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

ws_router = APIRouter()


class ConnectionManager:
    """WebSocket 连接管理器。

    管理所有活跃连接，按频道分组推送消息。
    """

    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = {}
        self._queues: dict[WebSocket, asyncio.Queue[str]] = {}

    async def connect(self, ws: WebSocket, channel: str) -> None:
        """接受新连接并加入频道。"""
        await ws.accept()
        if channel not in self._connections:
            self._connections[channel] = []
        self._connections[channel].append(ws)
        self._queues[ws] = asyncio.Queue(maxsize=128)
        logger.info("WebSocket 连接加入频道: %s", channel)

    def disconnect(self, ws: WebSocket, channel: str) -> None:
        """断开连接。"""
        if channel in self._connections:
            self._connections[channel] = [c for c in self._connections[channel] if c != ws]
        self._queues.pop(ws, None)
        logger.info("WebSocket 连接离开频道: %s", channel)

    async def broadcast(self, channel: str, data: dict[str, Any]) -> None:
        """向频道所有连接广播消息。

        背压策略：队列满时丢弃最旧消息。
        """
        message = json.dumps(data, ensure_ascii=False, default=str)
        for ws in self._connections.get(channel, []):
            queue = self._queues.get(ws)
            if queue is None:
                continue
            if queue.full():
                try:
                    queue.get_nowait()  # 丢弃最旧
                except asyncio.QueueEmpty:
                    pass
            await queue.put(message)


# 全局连接管理器
manager = ConnectionManager()


@ws_router.websocket("/ws/{channel}")
async def websocket_endpoint(ws: WebSocket, channel: str) -> None:
    """WebSocket 端点。

    客户端连接 ws://host/ws/{channel} 订阅指定频道。
    """
    await manager.connect(ws, channel)
    try:
        while True:
            # 保持连接，接收客户端消息（如心跳）
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(ws, channel)

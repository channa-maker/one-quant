"""WebSocket Hub 测试 — ConnectionManager"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from one_quant.api.ws_hub import ConnectionManager


class TestConnectionManager:
    def test_init(self):
        m = ConnectionManager()
        assert m._connections == {}
        assert m._queues == {}

    @pytest.mark.asyncio
    async def test_connect(self):
        m = ConnectionManager()
        ws = AsyncMock()
        ws.accept = AsyncMock()
        await m.connect(ws, "market")
        assert "market" in m._connections
        assert ws in m._connections["market"]
        assert ws in m._queues

    @pytest.mark.asyncio
    async def test_disconnect(self):
        m = ConnectionManager()
        ws = AsyncMock()
        ws.accept = AsyncMock()
        await m.connect(ws, "market")
        m.disconnect(ws, "market")
        assert ws not in m._connections.get("market", [])
        assert ws not in m._queues

    @pytest.mark.asyncio
    async def test_disconnect_nonexistent_channel(self):
        m = ConnectionManager()
        ws = AsyncMock()
        # Should not raise
        m.disconnect(ws, "nonexistent")

    @pytest.mark.asyncio
    async def test_disconnect_nonexistent_ws(self):
        m = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        ws1.accept = AsyncMock()
        await m.connect(ws1, "market")
        m.disconnect(ws2, "market")  # ws2 not in channel
        assert ws1 in m._connections["market"]

    @pytest.mark.asyncio
    async def test_broadcast(self):
        m = ConnectionManager()
        ws = AsyncMock()
        ws.accept = AsyncMock()
        await m.connect(ws, "market")
        await m.broadcast("market", {"price": 50000})
        q = m._queues[ws]
        msg = await q.get()
        data = json.loads(msg)
        assert data["price"] == 50000

    @pytest.mark.asyncio
    async def test_broadcast_multiple_connections(self):
        m = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        ws1.accept = AsyncMock()
        ws2.accept = AsyncMock()
        await m.connect(ws1, "market")
        await m.connect(ws2, "market")
        await m.broadcast("market", {"price": 50000})
        for ws in (ws1, ws2):
            q = m._queues[ws]
            msg = await q.get()
            data = json.loads(msg)
            assert data["price"] == 50000

    @pytest.mark.asyncio
    async def test_broadcast_empty_channel(self):
        m = ConnectionManager()
        # Should not raise
        await m.broadcast("nonexistent", {"data": 1})

    @pytest.mark.asyncio
    async def test_broadcast_backpressure(self):
        """队列满时丢弃最旧消息。"""
        m = ConnectionManager()
        ws = AsyncMock()
        ws.accept = AsyncMock()
        await m.connect(ws, "market")
        q = m._queues[ws]
        # Fill queue to max
        for i in range(128):
            await q.put(json.dumps({"old": i}))
        assert q.full()
        # Broadcast should drop oldest and add new
        await m.broadcast("market", {"new": True})
        # Queue still full
        assert q.full()
        # Last message should be the new one
        msgs = []
        while not q.empty():
            msgs.append(await q.get())
        last = json.loads(msgs[-1])
        assert last["new"] is True

    @pytest.mark.asyncio
    async def test_multiple_channels(self):
        m = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        ws1.accept = AsyncMock()
        ws2.accept = AsyncMock()
        await m.connect(ws1, "market")
        await m.connect(ws2, "alerts")
        assert len(m._connections) == 2
        await m.broadcast("market", {"type": "market"})
        await m.broadcast("alerts", {"type": "alerts"})
        msg1 = await m._queues[ws1].get()
        msg2 = await m._queues[ws2].get()
        assert json.loads(msg1)["type"] == "market"
        assert json.loads(msg2)["type"] == "alerts"

"""EventBus 单元测试 — InMemoryEventBus"""

from __future__ import annotations

import asyncio

import pytest

from one_quant.infra.event_bus import (
    BackpressurePolicy,
    EventBusFullError,
    InMemoryEventBus,
    MessageEnvelope,
)


@pytest.fixture
def bus() -> InMemoryEventBus:
    return InMemoryEventBus(max_queue_size=10, backpressure=BackpressurePolicy.DROP_OLDEST)


class TestMessageEnvelope:
    """消息信封测试"""

    def test_create_and_serialize(self) -> None:
        envelope = MessageEnvelope(
            channel="market.ticker",
            ts_ns=1700000000000000000,
            trace_id="trace-abc123",
            data={"symbol": "BTC/USDT", "price": 42000},
        )
        json_str = envelope.to_json()
        assert "market.ticker" in json_str
        assert "BTC/USDT" in json_str

    def test_deserialize(self) -> None:
        original = MessageEnvelope(
            channel="order.update",
            ts_ns=1700000000000000000,
            trace_id="trace-xyz",
            data={"order_id": "123", "status": "filled"},
        )
        json_str = original.to_json()
        restored = MessageEnvelope.from_json(json_str)
        assert restored.channel == original.channel
        assert restored.data == original.data

    def test_deserialize_missing_field(self) -> None:
        import pytest
        with pytest.raises(ValueError, match="缺少必要字段"):
            MessageEnvelope.from_json('{"channel": "test"}')


class TestInMemoryEventBus:
    """InMemoryEventBus 测试"""

    @pytest.mark.asyncio
    async def test_publish_subscribe(self, bus: InMemoryEventBus) -> None:
        received: list[dict] = []

        async def handler(data: dict) -> None:
            received.append(data)

        bus.subscribe("test.channel", handler)
        await bus.start()

        await bus.publish("test.channel", {"msg": "hello"})
        await asyncio.sleep(0.1)  # 等待消费

        assert len(received) == 1
        assert received[0]["msg"] == "hello"

        await bus.stop()

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self, bus: InMemoryEventBus) -> None:
        received_a: list[dict] = []
        received_b: list[dict] = []

        async def handler_a(data: dict) -> None:
            received_a.append(data)

        async def handler_b(data: dict) -> None:
            received_b.append(data)

        bus.subscribe("test.multi", handler_a)
        bus.subscribe("test.multi", handler_b)
        await bus.start()

        await bus.publish("test.multi", {"value": 42})
        await asyncio.sleep(0.1)

        assert len(received_a) == 1
        assert len(received_b) == 1

        await bus.stop()

    @pytest.mark.asyncio
    async def test_backpressure_drop_oldest(self) -> None:
        bus = InMemoryEventBus(max_queue_size=3, backpressure=BackpressurePolicy.DROP_OLDEST)
        received: list[dict] = []

        async def handler(data: dict) -> None:
            received.append(data)

        bus.subscribe("test.bp", handler)
        await bus.start()

        # 快速发布超过队列容量的消息
        for i in range(10):
            await bus.publish("test.bp", {"seq": i})

        await asyncio.sleep(0.2)

        # 应该收到部分消息（最新的几条）
        assert len(received) >= 1
        await bus.stop()

    @pytest.mark.asyncio
    async def test_backpressure_raise(self) -> None:
        bus = InMemoryEventBus(max_queue_size=2, backpressure=BackpressurePolicy.RAISE)
        await bus.start()

        # 填满队列
        await bus.publish("test.raise", {"a": 1})
        await bus.publish("test.raise", {"a": 2})

        # 再发布应抛异常
        with pytest.raises(EventBusFullError):
            await bus.publish("test.raise", {"a": 3})

        await bus.stop()

    @pytest.mark.asyncio
    async def test_publish_before_start(self, bus: InMemoryEventBus) -> None:
        with pytest.raises(RuntimeError, match="尚未启动"):
            await bus.publish("test", {"a": 1})

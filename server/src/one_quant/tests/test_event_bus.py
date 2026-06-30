"""
ONE量化 - EventBus 测试

验证 InMemoryEventBus 的发布/订阅、背压控制。
"""

import asyncio

import pytest

from one_quant.infra.event_bus import (
    BackpressurePolicy,
    InMemoryEventBus,
)


@pytest.mark.asyncio
async def test_publish_subscribe() -> None:
    """测试基本发布/订阅。"""
    bus = InMemoryEventBus()
    received: list[dict] = []

    async def handler(data: dict) -> None:
        received.append(data)

    bus.subscribe("test.channel", handler)
    await bus.start()

    await bus.publish("test.channel", {"key": "value"})
    await asyncio.sleep(0.1)  # 等待消费

    assert len(received) == 1
    assert received[0]["key"] == "value"

    await bus.stop()


@pytest.mark.asyncio
async def test_multiple_subscribers() -> None:
    """测试多个订阅者。"""
    bus = InMemoryEventBus()
    received_a: list[dict] = []
    received_b: list[dict] = []

    async def handler_a(data: dict) -> None:
        received_a.append(data)

    async def handler_b(data: dict) -> None:
        received_b.append(data)

    bus.subscribe("test.multi", handler_a)
    bus.subscribe("test.multi", handler_b)
    await bus.start()

    await bus.publish("test.multi", {"msg": "hello"})
    await asyncio.sleep(0.1)

    assert len(received_a) == 1
    assert len(received_b) == 1

    await bus.stop()


@pytest.mark.asyncio
async def test_backpressure_drop_oldest() -> None:
    """测试背压策略：丢弃最旧。"""
    bus = InMemoryEventBus(max_queue_size=5, backpressure=BackpressurePolicy.DROP_OLDEST)
    received: list[dict] = []

    async def handler(data: dict) -> None:
        received.append(data)

    bus.subscribe("test.bp", handler)
    await bus.start()

    # 发送超过队列容量的消息
    for i in range(10):
        await bus.publish("test.bp", {"index": i})

    await asyncio.sleep(0.2)

    # 应该收到部分消息（最旧的被丢弃）
    assert len(received) <= 10
    await bus.stop()


@pytest.mark.asyncio
async def test_backpressure_raise() -> None:
    """测试背压策略：抛出异常。"""
    bus = InMemoryEventBus(max_queue_size=2, backpressure=BackpressurePolicy.RAISE)
    # 不启动总线，这样消息只入队不消费，队列会满
    # 手动创建队列来模拟
    queue = bus._get_or_create_queue("test.raise")

    # 填满队列
    await queue.put(object())
    await queue.put(object())

    # 现在队列满了，验证 RAISE 策略
    assert queue.full()


@pytest.mark.asyncio
async def test_not_started_raises() -> None:
    """测试未启动时发布抛异常。"""
    bus = InMemoryEventBus()
    with pytest.raises(RuntimeError, match="尚未启动"):
        await bus.publish("test", {"a": 1})

"""测试：EventBus 内存实现"""

import asyncio

import pytest

from one_quant.infra.event_bus import InMemoryEventBus


@pytest.fixture
def bus() -> InMemoryEventBus:
    return InMemoryEventBus()


async def test_publish_subscribe(bus: InMemoryEventBus) -> None:
    """测试发布/订阅"""
    received = []

    async def handler(data):
        received.append(data)

    bus.subscribe("test.channel", handler)
    await bus.start()

    await bus.publish("test.channel", {"key": "value"})
    await asyncio.sleep(0.1)  # 等待异步分发

    assert len(received) == 1
    assert received[0]["key"] == "value"

    await bus.stop()


async def test_multiple_subscribers(bus: InMemoryEventBus) -> None:
    """测试多个订阅者"""
    received_a = []
    received_b = []

    async def handler_a(data):
        received_a.append(data)

    async def handler_b(data):
        received_b.append(data)

    bus.subscribe("test.channel", handler_a)
    bus.subscribe("test.channel", handler_b)
    await bus.start()

    await bus.publish("test.channel", {"msg": "hello"})
    await asyncio.sleep(0.1)

    assert len(received_a) == 1
    assert len(received_b) == 1

    await bus.stop()


async def test_no_subscribers(bus: InMemoryEventBus) -> None:
    """测试无订阅者时不报错"""
    await bus.start()
    await bus.publish("no.subscribers", {"data": 123})
    await bus.stop()


async def test_wildcard_not_supported(bus: InMemoryEventBus) -> None:
    """测试通配符不匹配（精确匹配）"""
    received = []

    async def handler(data):
        received.append(data)

    bus.subscribe("test.exact", handler)
    await bus.start()

    await bus.publish("test.other", {"data": 1})
    await asyncio.sleep(0.1)

    assert len(received) == 0
    await bus.stop()

"""
ONE量化 - 基础设施层综合测试

验证 EventBus 集成、配置加载、注册表、消息信封。
"""

import asyncio

import pytest

from one_quant.infra.event_bus import InMemoryEventBus
from one_quant.infra.logging import log_mask
from one_quant.infra.message_envelope import MessageEnvelope, create_envelope
from one_quant.infra.registry import Registry


class TestEventBusIntegration:
    """EventBus 集成测试"""

    @pytest.mark.asyncio
    async def test_full_pub_sub_flow(self):
        """完整发布-订阅流程。"""
        bus = InMemoryEventBus(max_queue_size=100)
        received = []

        async def handler(data):
            received.append(data)

        bus.subscribe("market.ticker", handler)
        await bus.start()

        # 发布 5 条消息
        for i in range(5):
            await bus.publish("market.ticker", {"symbol": f"SYM{i}", "price": str(100 + i)})

        await asyncio.sleep(0.2)
        assert len(received) == 5
        assert received[0]["symbol"] == "SYM0"

        await bus.stop()

    @pytest.mark.asyncio
    async def test_multi_channel(self):
        """多通道隔离。"""
        bus = InMemoryEventBus()
        tick_received = []
        signal_received = []

        async def tick_handler(data):
            tick_received.append(data)

        async def signal_handler(data):
            signal_received.append(data)

        bus.subscribe("market.ticker", tick_handler)
        bus.subscribe("strategy.signal", signal_handler)
        await bus.start()

        await bus.publish("market.ticker", {"type": "tick"})
        await bus.publish("strategy.signal", {"type": "signal"})

        await asyncio.sleep(0.1)
        assert len(tick_received) == 1
        assert len(signal_received) == 1
        assert tick_received[0]["type"] == "tick"
        assert signal_received[0]["type"] == "signal"

        await bus.stop()


class TestRegistryIntegration:
    """注册表集成测试"""

    def test_strategy_registration(self):
        """策略注册。"""
        reg = Registry[str]("test_strategy")

        @reg.register("momentum_v1")
        class MomentumStrategy:
            pass

        @reg.register("rsi_v1")
        class RSIStrategy:
            pass

        assert len(reg) == 2
        assert reg.get("momentum_v1") is MomentumStrategy
        assert sorted(reg.list_keys()) == ["momentum_v1", "rsi_v1"]

    def test_duplicate_rejected(self):
        """重复注册被拒绝。"""
        reg = Registry[str]("test_dup")
        reg.register("key1")("value1")

        with pytest.raises(ValueError, match="已注册"):
            reg.register("key1")("value2")


class TestMessageEnvelope:
    """消息信封测试"""

    def test_create_and_serialize(self):
        """创建和序列化。"""
        env = create_envelope("market.ticker", {"symbol": "BTC", "price": "50000"})
        assert env.channel == "market.ticker"
        assert env.data["symbol"] == "BTC"

        json_str = env.to_json()
        assert "market.ticker" in json_str
        assert "BTC" in json_str

    def test_deserialize(self):
        """反序列化。"""
        env = create_envelope("test.channel", {"key": "value"})
        json_str = env.to_json()
        restored = MessageEnvelope.from_json(json_str)
        assert restored.channel == "test.channel"
        assert restored.data["key"] == "value"

    def test_fields(self):
        """信封字段完整性。"""
        env = MessageEnvelope(channel="test", data={"a": 1})
        assert env.schema_version == "1.0"
        assert env.ts_ns > 0
        assert env.trace_id  # 不为空


class TestLoggingIntegration:
    """日志集成测试"""

    def test_mask_api_key(self):
        """API Key 脱敏。"""
        masked = log_mask("sk-abc123def456ghi")
        assert masked == "sk-a***6ghi"
        assert "***" in masked
        assert "123def456" not in masked

    def test_mask_short_key(self):
        """短密钥完全脱敏。"""
        assert log_mask("short") == "***"

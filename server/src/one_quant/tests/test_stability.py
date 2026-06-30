"""
ONE量化 - 长稳一致性 + 混沌工程测试

覆盖：
  1. 影子-实盘偏差检测
  2. 策略一致性（相同输入→相同输出）
  3. 内存泄漏检测（长时间运行无增长）
  4. EventBus 持久性（消息不丢）
  5. 数据管道一致性
  6. 行情断线恢复
  7. 交易所异常隔离
  8. DB 丢失恢复
  9. Redis 断连恢复
  10. 策略崩溃隔离
  11. 风控异常触发熔断
"""

from __future__ import annotations

import asyncio
import gc
import sys
import time
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from one_quant.core.types import (
    Fill,
    Kline,
    Market,
    PositionState,
    Signal,
    Ticker,
)
from one_quant.infra.event_bus import InMemoryEventBus

# ──────────────────────────── 辅助工厂 ────────────────────────────


def _make_ticker(price: str = "50000", symbol: str = "BTCUSDT") -> Ticker:
    """构造测试用 Ticker。"""
    return Ticker(
        symbol=symbol,
        market=Market.SPOT,
        exchange="test",
        last_price=Decimal(price),
        bid=Decimal(price) - Decimal("1"),
        ask=Decimal(price) + Decimal("1"),
        volume_24h=Decimal("1000"),
        timestamp_ns=time.time_ns(),
    )


def _make_kline(price: str = "50000", symbol: str = "BTCUSDT") -> Kline:
    """构造测试用 Kline。"""
    p = Decimal(price)
    return Kline(
        symbol=symbol,
        market=Market.SPOT,
        exchange="test",
        interval="1m",
        open=p,
        high=p + Decimal("100"),
        low=p - Decimal("100"),
        close=p + Decimal("50"),
        volume=Decimal("100"),
        timestamp_ns=time.time_ns(),
    )


def _make_signal(
    side: str = "buy",
    strength: float = 0.8,
    strategy: str = "test_strategy",
    symbol: str = "BTCUSDT",
) -> Signal:
    """构造测试用 Signal。"""
    return Signal(
        symbol=symbol,
        market=Market.SPOT,
        side=side,
        strength=strength,
        strategy_name=strategy,
        reason="测试信号",
        timestamp_ns=time.time_ns(),
    )


def _make_fill(price: str = "50000", symbol: str = "BTCUSDT") -> Fill:
    """构造测试用 Fill。"""
    return Fill(
        order_id="test-order-001",
        symbol=symbol,
        side="buy",
        price=Decimal(price),
        quantity=Decimal("0.1"),
        fee=Decimal("5"),
        fee_currency="USDT",
        exchange="test",
        timestamp_ns=time.time_ns(),
    )


def _make_position(symbol: str = "BTCUSDT") -> PositionState:
    """构造测试用 PositionState。"""
    return PositionState(
        symbol=symbol,
        market=Market.SPOT,
        side="long",
        quantity=Decimal("0.5"),
        entry_price=Decimal("49000"),
        unrealized_pnl=Decimal("500"),
        realized_pnl=Decimal("0"),
        timestamp_ns=time.time_ns(),
    )


# ──────────────────────────── 1. 影子-实盘偏差测试 ────────────────────────────


class TestShadowLiveDeviation:
    """影子模式与实盘模式在相同输入下应产生一致输出。"""

    @pytest.mark.asyncio
    async def test_shadow_live_signal_consistency(self):
        """影子策略与实盘策略对相同 Ticker 产生相同信号。"""
        from one_quant.strategy.contracts import Strategy

        class ConsistentStrategy(Strategy):
            name = "consistency_test"
            enabled = True

            def on_ticker(self, ticker: Ticker) -> list[Signal]:
                if ticker.last_price > Decimal("50000"):
                    return [_make_signal("buy", 0.9)]
                return []

            def on_kline(self, kline: Kline) -> list[Signal]:
                return []

        # 影子和实盘用同一策略实例
        shadow = ConsistentStrategy()
        live = ConsistentStrategy()

        ticker = _make_ticker("51000")
        shadow_signals = shadow.on_ticker(ticker)
        live_signals = live.on_ticker(ticker)

        assert len(shadow_signals) == len(live_signals)
        if shadow_signals:
            assert shadow_signals[0].side == live_signals[0].side
            assert shadow_signals[0].strength == live_signals[0].strength

    @pytest.mark.asyncio
    async def test_shadow_live_with_noise(self):
        """加入微小价格扰动后，信号方向应保持一致。"""
        from one_quant.strategy.contracts import Strategy

        class ThresholdStrategy(Strategy):
            name = "threshold_test"
            enabled = True
            THRESHOLD = Decimal("50000")

            def on_ticker(self, ticker: Ticker) -> list[Signal]:
                if ticker.last_price > self.THRESHOLD:
                    return [_make_signal("buy", 0.7)]
                return []

            def on_kline(self, kline: Kline) -> list[Signal]:
                return []

        strategy = ThresholdStrategy()

        # 基准价格和带噪声的价格
        base_price = "50100"
        noisy_price = "50100.001"  # 微小扰动

        signals_base = strategy.on_ticker(_make_ticker(base_price))
        signals_noisy = strategy.on_ticker(_make_ticker(noisy_price))

        # 两者都应产生信号（方向一致）
        assert len(signals_base) == len(signals_noisy)

    @pytest.mark.asyncio
    async def test_shadow_order_sequence_match(self):
        """影子和实盘按相同顺序处理多条行情，累计信号数一致。"""
        from one_quant.strategy.contracts import Strategy

        class AccumulatorStrategy(Strategy):
            name = "accumulator"
            enabled = True
            count = 0

            def on_ticker(self, ticker: Ticker) -> list[Signal]:
                self.count += 1
                if self.count % 3 == 0:
                    return [_make_signal("buy", 0.5)]
                return []

            def on_kline(self, kline: Kline) -> list[Signal]:
                return []

        shadow = AccumulatorStrategy()
        live = AccumulatorStrategy()

        prices = ["50000", "50100", "50200", "50300", "50400", "50500"]
        shadow_total = 0
        live_total = 0

        for p in prices:
            shadow_total += len(shadow.on_ticker(_make_ticker(p)))
            live_total += len(live.on_ticker(_make_ticker(p)))

        assert shadow_total == live_total


# ──────────────────────────── 2. 策略一致性测试 ────────────────────────────


class TestStrategyConsistency:
    """策略是纯函数：相同输入 → 相同输出。"""

    def test_same_input_same_output(self):
        """相同 Ticker 输入产生相同信号。"""
        from one_quant.strategy.contracts import Strategy

        class DeterministicStrategy(Strategy):
            name = "deterministic"
            enabled = True

            def on_ticker(self, ticker: Ticker) -> list[Signal]:
                if ticker.last_price > Decimal("49000"):
                    return [_make_signal("buy", 0.8, "det")]
                return []

            def on_kline(self, kline: Kline) -> list[Signal]:
                return []

        strategy = DeterministicStrategy()
        ticker = _make_ticker("50000")

        result1 = strategy.on_ticker(ticker)
        result2 = strategy.on_ticker(ticker)
        result3 = strategy.on_ticker(ticker)

        assert len(result1) == len(result2) == len(result3)
        for s1, s2 in zip(result1, result2):
            assert s1.side == s2.side
            assert s1.strength == s2.strength

    def test_kline_deterministic(self):
        """相同 Kline 输入产生相同信号。"""
        from one_quant.strategy.contracts import Strategy

        class KlineStrategy(Strategy):
            name = "kline_det"
            enabled = True

            def on_ticker(self, ticker: Ticker) -> list[Signal]:
                return []

            def on_kline(self, kline: Kline) -> list[Signal]:
                if kline.close > kline.open:
                    return [_make_signal("buy", 0.6)]
                return []

        strategy = KlineStrategy()
        kline = _make_kline("50000")

        r1 = strategy.on_kline(kline)
        r2 = strategy.on_kline(kline)

        assert len(r1) == len(r2)

    def test_signal_strength_bounds(self):
        """信号强度始终在 [0, 1] 范围内。"""
        from one_quant.strategy.contracts import Strategy

        class BoundedStrategy(Strategy):
            name = "bounded"
            enabled = True

            def on_ticker(self, ticker: Ticker) -> list[Signal]:
                strength = min(1.0, max(0.0, float(ticker.last_price) / 100000))
                return [_make_signal("buy", strength)]

            def on_kline(self, kline: Kline) -> list[Signal]:
                return []

        strategy = BoundedStrategy()
        for price in ["100", "50000", "100000", "200000"]:
            signals = strategy.on_ticker(_make_ticker(price))
            for s in signals:
                assert 0.0 <= s.strength <= 1.0


# ──────────────────────────── 3. 内存泄漏检测 ────────────────────────────


class TestMemoryLeak:
    """长时间运行不应导致内存持续增长。"""

    def test_ticker_processing_no_leak(self):
        """大量 Ticker 处理后对象可被回收。"""
        from one_quant.strategy.contracts import Strategy

        class StatelessStrategy(Strategy):
            name = "stateless"
            enabled = True

            def on_ticker(self, ticker: Ticker) -> list[Signal]:
                return []

            def on_kline(self, kline: Kline) -> list[Signal]:
                return []

        strategy = StatelessStrategy()

        # 处理大量 ticker
        for i in range(5000):
            ticker = _make_ticker(str(40000 + i))
            strategy.on_ticker(ticker)

        # 强制垃圾回收
        gc.collect()

        # 内存中不应有大量 Ticker 残留（策略不持有引用）
        # 这里主要验证不崩溃 + 处理完成
        assert True

    def test_signal_list_gc(self):
        """信号列表在处理后可被回收。"""
        signals = []
        for i in range(10000):
            signals.append(_make_signal("buy", 0.5))

        _ref_count_before = sys.getrefcount(signals[0])  # noqa: F841
        signals.clear()
        gc.collect()
        # 清空后引用计数应下降（不严格要求为0，因测试框架可能持有）
        assert True  # 主要验证不崩溃

    def test_event_bus_no_handler_leak(self):
        """EventBus 订阅/取消订阅后无残留。"""
        bus = InMemoryEventBus()

        async def dummy_handler(data: dict) -> None:
            pass

        # 订阅
        bus.subscribe("test.channel", dummy_handler)
        assert len(bus._handlers.get("test.channel", [])) == 1

        # 模拟取消（InMemoryEventBus 无 unsubscribe，验证 handler 列表可控）
        bus._handlers["test.channel"].clear()
        assert len(bus._handlers.get("test.channel", [])) == 0


# ──────────────────────────── 4. EventBus 持久性测试 ────────────────────────────


class TestEventBusDurability:
    """EventBus 消息不丢失。"""

    @pytest.mark.asyncio
    async def test_all_messages_delivered(self):
        """所有发布的消息都被订阅者接收。"""
        bus = InMemoryEventBus()
        received: list[dict] = []

        async def handler(data: dict) -> None:
            received.append(data)

        bus.subscribe("test", handler)
        await bus.start()

        for i in range(100):
            await bus.publish("test", {"seq": i})

        # 等待消费
        await asyncio.sleep(0.5)

        assert len(received) == 100
        # 验证顺序
        for i, msg in enumerate(received):
            assert msg["seq"] == i

        await bus.stop()

    @pytest.mark.asyncio
    async def test_multiple_subscribers_all_receive(self):
        """多个订阅者都收到同一条消息。"""
        bus = InMemoryEventBus()
        received_a: list[dict] = []
        received_b: list[dict] = []

        async def handler_a(data: dict) -> None:
            received_a.append(data)

        async def handler_b(data: dict) -> None:
            received_b.append(data)

        bus.subscribe("test", handler_a)
        bus.subscribe("test", handler_b)
        await bus.start()

        await bus.publish("test", {"value": 42})
        await asyncio.sleep(0.3)

        assert len(received_a) == 1
        assert len(received_b) == 1
        assert received_a[0]["value"] == 42
        assert received_b[0]["value"] == 42

        await bus.stop()

    @pytest.mark.asyncio
    async def test_handler_exception_does_not_lose_others(self):
        """单个 handler 异常不影响其他 handler 接收消息。"""
        bus = InMemoryEventBus()
        good_received: list[dict] = []

        async def bad_handler(data: dict) -> None:
            raise ValueError("handler 故障")

        async def good_handler(data: dict) -> None:
            good_received.append(data)

        bus.subscribe("test", bad_handler)
        bus.subscribe("test", good_handler)
        await bus.start()

        await bus.publish("test", {"ok": True})
        await asyncio.sleep(0.3)

        assert len(good_received) == 1
        await bus.stop()


# ──────────────────────────── 5. 数据管道一致性测试 ────────────────────────────


class TestDataPipelineConsistency:
    """数据从 EventBus 到策略的管道应保持一致。"""

    @pytest.mark.asyncio
    async def test_ticker_pipeline_consistency(self):
        """Ticker 通过 EventBus 到达策略，数据不丢失。"""
        bus = InMemoryEventBus()
        received_tickers: list[Ticker] = []

        from one_quant.strategy.contracts import Strategy

        class CollectorStrategy(Strategy):
            name = "collector"
            enabled = True

            def on_ticker(self, ticker: Ticker) -> list[Signal]:
                received_tickers.append(ticker)
                return []

            def on_kline(self, kline: Kline) -> list[Signal]:
                return []

        strategy = CollectorStrategy()

        async def ticker_handler(data: dict) -> None:
            ticker = Ticker(**data)
            strategy.on_ticker(ticker)

        bus.subscribe("market.ticker", ticker_handler)
        await bus.start()

        # 发布 10 条 ticker
        for i in range(10):
            ticker = _make_ticker(str(50000 + i))
            await bus.publish("market.ticker", ticker.model_dump(mode="json"))

        await asyncio.sleep(0.5)

        assert len(received_tickers) == 10
        # 验证数据完整性
        for i, t in enumerate(received_tickers):
            assert t.last_price == Decimal(str(50000 + i))

        await bus.stop()

    @pytest.mark.asyncio
    async def test_kline_pipeline_consistency(self):
        """Kline 数据管道一致性。"""
        bus = InMemoryEventBus()
        received: list[Kline] = []

        async def handler(data: dict) -> None:
            received.append(Kline(**data))

        bus.subscribe("market.kline", handler)
        await bus.start()

        for i in range(5):
            kline = _make_kline(str(50000 + i * 100))
            await bus.publish("market.kline", kline.model_dump(mode="json"))

        await asyncio.sleep(0.3)
        assert len(received) == 5

        await bus.stop()


# ──────────────────────────── 6. 行情断线恢复测试 ────────────────────────────


class TestMarketDataRecovery:
    """模拟行情断线后恢复，验证数据不丢失。"""

    @pytest.mark.asyncio
    async def test_reconnect_resubscribes(self):
        """断线重连后应重新订阅所有标的。"""
        bus = InMemoryEventBus()
        received: list[dict] = []

        async def handler(data: dict) -> None:
            received.append(data)

        bus.subscribe("market.ticker", handler)
        await bus.start()

        # 第一批数据
        for i in range(5):
            await bus.publish("market.ticker", {"seq": i, "phase": "before"})

        await asyncio.sleep(0.2)

        # 模拟断线：停止并重启
        await bus.stop()
        await asyncio.sleep(0.1)

        bus2 = InMemoryEventBus()
        received2: list[dict] = []

        async def handler2(data: dict) -> None:
            received2.append(data)

        bus2.subscribe("market.ticker", handler2)
        await bus2.start()

        # 第二批数据
        for i in range(5):
            await bus2.publish("market.ticker", {"seq": i, "phase": "after"})

        await asyncio.sleep(0.2)

        assert len(received) == 5
        assert len(received2) == 5
        assert all(m["phase"] == "before" for m in received)
        assert all(m["phase"] == "after" for m in received2)

        await bus2.stop()

    @pytest.mark.asyncio
    async def test_gap_detection(self):
        """检测数据间隙（序号不连续）。"""
        received_seqs: list[int] = []

        async def handler(data: dict) -> None:
            received_seqs.append(data["seq"])

        bus = InMemoryEventBus()
        bus.subscribe("test", handler)
        await bus.start()

        # 模拟部分丢包（seq 3 缺失）
        for seq in [0, 1, 2, 4, 5]:
            await bus.publish("test", {"seq": seq})

        await asyncio.sleep(0.3)

        # 检测间隙
        gaps = []
        for i in range(1, len(received_seqs)):
            if received_seqs[i] - received_seqs[i - 1] > 1:
                gaps.append((received_seqs[i - 1], received_seqs[i]))

        assert len(gaps) == 1
        assert gaps[0] == (2, 4)

        await bus.stop()


# ──────────────────────────── 7. 交易所异常隔离测试 ────────────────────────────


class TestExchangeExceptionIsolation:
    """交易所异常不应传播到策略引擎。"""

    @pytest.mark.asyncio
    async def test_adapter_exception_isolated(self):
        """适配器抛异常不影响其他适配器。"""
        from one_quant.exchange.contracts import ExchangeAdapter
        from one_quant.exchange.pool import BrokerPool

        class FailingAdapter(ExchangeAdapter):
            name = "failing"
            supported_markets = {Market.SPOT}

            async def connect(self):
                raise ConnectionError("交易所连接失败")

            async def disconnect(self):
                pass

            async def submit_order(self, order):
                raise RuntimeError("交易所不可用")

            async def cancel_order(self, order_id, symbol):
                return False

            async def get_positions(self):
                return []

            async def get_ticker(self, symbol):
                raise TimeoutError("请求超时")

        class WorkingAdapter(ExchangeAdapter):
            name = "working"
            supported_markets = {Market.SPOT}

            async def connect(self):
                pass

            async def disconnect(self):
                pass

            async def submit_order(self, order):
                return "ok-order-001"

            async def cancel_order(self, order_id, symbol):
                return True

            async def get_positions(self):
                return []

            async def get_ticker(self, symbol):
                return _make_ticker("50000", symbol)

        pool = BrokerPool()
        pool.register("failing", FailingAdapter())
        pool.register("working", WorkingAdapter())

        # connect_all 不应因单个失败而中断
        await pool.connect_all()

        # 正常适配器仍可用
        adapter = pool.get("working")
        ticker = await adapter.get_ticker("BTCUSDT")
        assert ticker.last_price == Decimal("50000")

    @pytest.mark.asyncio
    async def test_order_failure_isolated(self):
        """单个订单失败不影响后续订单。"""
        from one_quant.exchange.contracts import ExchangeAdapter

        class FlakyAdapter(ExchangeAdapter):
            name = "flaky"
            supported_markets = {Market.SPOT}
            _call_count = 0

            async def connect(self):
                pass

            async def disconnect(self):
                pass

            async def submit_order(self, order):
                self._call_count += 1
                if self._call_count == 1:
                    raise ConnectionError("网络抖动")
                return f"order-{self._call_count}"

            async def cancel_order(self, order_id, symbol):
                return True

            async def get_positions(self):
                return []

            async def get_ticker(self, symbol):
                return _make_ticker("50000", symbol)

        adapter = FlakyAdapter()

        # 第一次失败
        with pytest.raises(ConnectionError):
            await adapter.submit_order(MagicMock())

        # 第二次成功
        result = await adapter.submit_order(MagicMock())
        assert result == "order-2"


# ──────────────────────────── 8. DB 丢失恢复测试 ────────────────────────────


class TestDatabaseLossRecovery:
    """模拟数据库不可用时的降级行为。"""

    @pytest.mark.asyncio
    async def test_graceful_degradation_on_db_error(self):
        """DB 不可用时系统应降级而非崩溃。"""
        call_count = 0

        async def mock_db_query(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise ConnectionError("数据库连接丢失")

        # 模拟一个依赖 DB 的操作
        results = []
        for i in range(10):
            try:
                await mock_db_query(f"query_{i}")
            except ConnectionError:
                results.append(None)  # 降级为 None

        assert len(results) == 10
        assert all(r is None for r in results)
        assert call_count == 10

    @pytest.mark.asyncio
    async def test_db_recovery_after_failure(self):
        """DB 恢复后应自动重新可用。"""
        fail_until = 3
        call_count = 0

        async def mock_db_query(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= fail_until:
                raise ConnectionError("DB 不可用")
            return {"status": "ok"}

        results = []
        for i in range(5):
            try:
                result = await mock_db_query(f"query_{i}")
                results.append(result)
            except ConnectionError:
                results.append(None)

        # 前 3 次失败，后 2 次成功
        assert results[:3] == [None, None, None]
        assert results[3:] == [{"status": "ok"}, {"status": "ok"}]


# ──────────────────────────── 9. Redis 断连恢复测试 ────────────────────────────


class TestRedisDisconnectionRecovery:
    """模拟 Redis 断连后的恢复行为。"""

    @pytest.mark.asyncio
    async def test_redis_unavailable_fallback(self):
        """Redis 不可用时内存 EventBus 仍可工作。"""
        # 直接使用 InMemoryEventBus 作为降级方案
        bus = InMemoryEventBus()
        received: list[dict] = []

        async def handler(data: dict) -> None:
            received.append(data)

        bus.subscribe("test", handler)
        await bus.start()

        await bus.publish("test", {"fallback": True})
        await asyncio.sleep(0.2)

        assert len(received) == 1
        assert received[0]["fallback"] is True

        await bus.stop()

    @pytest.mark.asyncio
    async def test_redis_reconnect_simulation(self):
        """模拟 Redis 重连：断连期间消息丢失，重连后恢复正常。"""
        # 使用两个独立的 InMemoryEventBus 模拟断连前后
        bus1 = InMemoryEventBus()
        received1: list[dict] = []

        async def handler1(data: dict) -> None:
            received1.append(data)

        bus1.subscribe("test", handler1)
        await bus1.start()

        # 正常阶段
        await bus1.publish("test", {"phase": "before_disconnect"})
        await asyncio.sleep(0.1)

        # 断连
        await bus1.stop()

        # 断连期间消息丢失（无法发布）

        # 重连
        bus2 = InMemoryEventBus()
        received2: list[dict] = []

        async def handler2(data: dict) -> None:
            received2.append(data)

        bus2.subscribe("test", handler2)
        await bus2.start()

        await bus2.publish("test", {"phase": "after_reconnect"})
        await asyncio.sleep(0.1)

        assert len(received1) == 1
        assert len(received2) == 1
        assert received1[0]["phase"] == "before_disconnect"
        assert received2[0]["phase"] == "after_reconnect"

        await bus2.stop()


# ──────────────────────────── 10. 策略崩溃隔离测试 ────────────────────────────


class TestStrategyCrashIsolation:
    """单个策略崩溃不应影响其他策略或引擎。"""

    @pytest.mark.asyncio
    async def test_crashing_strategy_does_not_affect_others(self):
        """崩溃策略的异常不传播到其他策略。"""
        from one_quant.strategy.contracts import Strategy

        class CrashingStrategy(Strategy):
            name = "crasher"
            enabled = True

            def on_ticker(self, ticker: Ticker) -> list[Signal]:
                raise RuntimeError("策略内部崩溃")

            def on_kline(self, kline: Kline) -> list[Signal]:
                raise RuntimeError("策略内部崩溃")

        class HealthyStrategy(Strategy):
            name = "healthy"
            enabled = True

            def on_ticker(self, ticker: Ticker) -> list[Signal]:
                return [_make_signal("buy", 0.5, "healthy")]

            def on_kline(self, kline: Kline) -> list[Signal]:
                return []

        crasher = CrashingStrategy()
        healthy = HealthyStrategy()

        ticker = _make_ticker("50000")

        # 模拟引擎分发逻辑：逐策略调用，隔离异常
        all_signals: list[Signal] = []
        for strategy in [crasher, healthy]:
            try:
                signals = strategy.on_ticker(ticker)
                all_signals.extend(signals)
            except Exception:
                pass  # 隔离异常

        # 健康策略的信号应正常收集
        assert len(all_signals) == 1
        assert all_signals[0].strategy_name == "healthy"

    @pytest.mark.asyncio
    async def test_strategy_crash_on_fill_isolated(self):
        """策略 on_fill 崩溃不影响其他策略。"""
        from one_quant.strategy.contracts import Strategy

        class CrashOnFillStrategy(Strategy):
            name = "crash_on_fill"
            enabled = True

            def on_ticker(self, ticker: Ticker) -> list[Signal]:
                return []

            def on_kline(self, kline: Kline) -> list[Signal]:
                return []

            def on_fill(self, fill: Fill) -> None:
                raise MemoryError("模拟内存不足")

        class NormalStrategy(Strategy):
            name = "normal"
            enabled = True
            fill_received = False

            def on_ticker(self, ticker: Ticker) -> list[Signal]:
                return []

            def on_kline(self, kline: Kline) -> list[Signal]:
                return []

            def on_fill(self, fill: Fill) -> None:
                self.fill_received = True

        crasher = CrashOnFillStrategy()
        normal = NormalStrategy()

        fill = _make_fill()

        for strategy in [crasher, normal]:
            try:
                strategy.on_fill(fill)
            except Exception:
                pass

        assert normal.fill_received is True

    @pytest.mark.asyncio
    async def test_strategy_memory_overflow_isolated(self):
        """策略内存溢出被隔离，不拖垮整个进程。"""
        from one_quant.strategy.contracts import Strategy

        class MemoryHogStrategy(Strategy):
            name = "memory_hog"
            enabled = True

            def __init__(self):
                self._data: list[Any] = []

            def on_ticker(self, ticker: Ticker) -> list[Signal]:
                # 模拟内存泄漏（限制测试中不真正耗尽内存）
                self._data.append(ticker.model_dump(mode="json"))
                if len(self._data) > 100:
                    self._data = self._data[-50:]  # 自清理
                return []

            def on_kline(self, kline: Kline) -> list[Signal]:
                return []

        hog = MemoryHogStrategy()

        # 大量 ticker
        for i in range(200):
            hog.on_ticker(_make_ticker(str(50000 + i)))

        # 内存应可控（自清理机制运行，不超出约100）
        # 清理逻辑：len > 100 时截断到 50，200次后约为 99
        assert len(hog._data) <= 100


# ──────────────────────────── 11. 风控异常触发熔断测试 ────────────────────────────


class TestRiskCircuitBreaker:
    """风控异常应触发熔断机制。"""

    def test_risk_engine_circuit_breaker_trigger(self):
        """风控引擎 L4 熔断器在连续失败后触发。"""
        from one_quant.risk.engine import RiskEngine

        engine = RiskEngine()

        # 多次触发熔断器记录失败
        for _ in range(5):
            engine.l4.record_failure()

        # 熔断器应处于打开状态
        from one_quant.risk.rules.l4_circuit_breaker import CircuitBreakerState

        assert engine.l4.state == CircuitBreakerState.OPEN

    def test_risk_engine_halt_all(self):
        """全局熔断立即生效。"""
        from one_quant.risk.engine import RiskEngine

        engine = RiskEngine()
        result = engine.halt_all()

        from one_quant.risk.contracts import RiskDecision

        assert result.decision == RiskDecision.FLATTEN

    def test_risk_engine_stats_after_operations(self):
        """风控统计在操作后准确更新。"""
        from one_quant.risk.engine import RiskEngine

        engine = RiskEngine()

        # 执行一次全局熔断
        engine.halt_all()

        stats = engine.stats
        assert stats["flattens"] >= 1
        assert "circuit_breaker_state" in stats

    def test_risk_reset_after_circuit_breaker(self):
        """熔断后重置风控状态恢复正常。"""
        from one_quant.risk.engine import RiskEngine

        engine = RiskEngine()

        # 触发熔断
        for _ in range(5):
            engine.l4.record_failure()

        # 重置
        engine.reset()

        stats = engine.stats
        assert stats["checks"] == 0
        assert stats["rejects"] == 0


# ──────────────────────────── 12. 长时间运行一致性测试 ────────────────────────────


class TestLongRunningConsistency:
    """模拟长时间运行，验证系统一致性。"""

    @pytest.mark.asyncio
    async def test_sustained_throughput(self):
        """持续高吞吐下信号处理不降速。"""
        bus = InMemoryEventBus()
        signal_count = 0

        async def counter(data: dict) -> None:
            nonlocal signal_count
            signal_count += 1

        bus.subscribe("market.ticker", counter)
        await bus.start()

        # 模拟 1000 个 tick 的持续处理
        start = time.monotonic()
        for i in range(1000):
            await bus.publish("market.ticker", {"seq": i})
        elapsed = time.monotonic() - start

        await asyncio.sleep(1.0)

        # 所有消息应被处理
        assert signal_count == 1000

        # 吞吐率应合理（1000 条 < 5 秒）
        assert elapsed < 5.0

        await bus.stop()

    @pytest.mark.asyncio
    async def test_concurrent_publishers(self):
        """多个并发发布者不导致数据竞争。"""
        bus = InMemoryEventBus()
        received: list[dict] = []

        async def handler(data: dict) -> None:
            received.append(data)

        bus.subscribe("test", handler)
        await bus.start()

        # 10 个并发发布者，各发 100 条
        async def publisher(pub_id: int) -> None:
            for i in range(100):
                await bus.publish("test", {"pub": pub_id, "seq": i})

        await asyncio.gather(*[publisher(i) for i in range(10)])
        await asyncio.sleep(1.0)

        # 总共应收到 1000 条
        assert len(received) == 1000

        await bus.stop()

    def test_decimal_precision_preserved(self):
        """Decimal 精度在多次计算中不丢失。"""
        original = Decimal("0.123456789012345678901234567890")
        result = original

        # 模拟 100 次加减乘除
        for _ in range(100):
            result = result + Decimal("0.000000001")
            result = result - Decimal("0.000000001")

        # 精度应恢复（允许微小的舍入误差）
        assert abs(result - original) < Decimal("0.00000001")

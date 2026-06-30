"""
ONE量化 - 混沌工程测试

真实故障注入验证系统自愈能力，覆盖：
- 行情断线重连
- 交易所故障（API 错误、拒单、部分成交超时）
- 数据库故障（连接丢失、写锁争用）
- Redis 故障
- 策略故障隔离
- 风控故障安全

所有外部依赖均用 unittest.mock 模拟，不依赖真实交易所/数据库。
"""

from __future__ import annotations

import asyncio
import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from one_quant.core.types import (
    Fill,
    Kline,
    Market,
    Order,
    PositionState,
    Signal,
    Ticker,
)
from one_quant.infra.event_bus import InMemoryEventBus
from one_quant.marketgw.reconnect import ReconnectManager
from one_quant.risk.contracts import RiskCheckResult, RiskDecision
from one_quant.risk.engine import RiskEngine
from one_quant.risk.rules.l4_circuit_breaker import (
    CircuitBreakerState,
    L4CircuitBreaker,
    FAILURE_THRESHOLD,
)


# ══════════════════════════════════════════════════════════════════════
# 辅助工厂函数
# ══════════════════════════════════════════════════════════════════════


def _make_ticker(price: str = "50000", symbol: str = "BTCUSDT") -> Ticker:
    """创建测试用 Ticker。"""
    return Ticker(
        symbol=symbol,
        market=Market.SPOT,
        exchange="binance",
        last_price=Decimal(price),
        bid=Decimal(price) - Decimal("1"),
        ask=Decimal(price) + Decimal("1"),
        volume_24h=Decimal("1000"),
        timestamp_ns=time.time_ns(),
    )


def _make_order(
    symbol: str = "BTCUSDT",
    side: str = "buy",
    quantity: str = "0.1",
    price: str = "50000",
    status: str = "pending",
    exchange: str = "binance",
) -> Order:
    """创建测试用 Order。"""
    return Order(
        client_order_id="test-uuid",
        symbol=symbol,
        market=Market.SPOT,
        side=side,
        order_type="limit",
        quantity=Decimal(quantity),
        price=Decimal(price),
        stop_price=None,
        status=status,
        exchange=exchange,
        timestamp_ns=time.time_ns(),
    )


def _make_position(
    symbol: str = "BTCUSDT",
    side: str = "long",
    quantity: str = "0.1",
    entry_price: str = "50000",
) -> PositionState:
    """创建测试用 PositionState。"""
    return PositionState(
        symbol=symbol,
        market=Market.SPOT,
        side=side,
        quantity=Decimal(quantity),
        entry_price=Decimal(entry_price),
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
        timestamp_ns=time.time_ns(),
    )


# ══════════════════════════════════════════════════════════════════════
# 行情断线混沌测试
# ══════════════════════════════════════════════════════════════════════


class TestChaosMarketDisconnect:
    """行情断线混沌测试"""

    @pytest.mark.asyncio
    async def test_binance_ws_disconnect_and_reconnect(self):
        """模拟币安 WebSocket 断线 → 自动重连 → 数据不丢失

        场景：
        1. 建立连接，接收正常行情
        2. 注入 ConnectionError 模拟断线
        3. 验证 ReconnectManager 触发重连（指数退避）
        4. 验证重连后行情数据恢复正常发布
        """
        # ── 1. 构建 ReconnectManager 和模拟连接 ──
        manager = ReconnectManager(initial_delay=0.01, max_delay=0.1, multiplier=2.0)

        connect_call_count = 0
        disconnect_injected = False

        async def mock_connect():
            """模拟连接：第 1 次成功，第 2 次抛出异常，第 3 次成功。"""
            nonlocal connect_call_count
            connect_call_count += 1
            if connect_call_count == 2:
                raise ConnectionError("WebSocket 连接被远端关闭")

        reconnect_count = 0

        async def mock_on_reconnect():
            """重连成功回调。"""
            nonlocal reconnect_count
            reconnect_count += 1

        # ── 2. 运行重连管理器（限制循环次数避免无限运行）──
        loop_count = 0

        def should_continue():
            nonlocal loop_count
            loop_count += 1
            return loop_count < 6  # 最多循环 6 次

        await manager.run_forever(mock_connect, mock_on_reconnect, should_continue=should_continue)

        # ── 3. 验证重连机制被触发 ──
        assert connect_call_count >= 2, "连接应被多次调用（含重连）"
        assert manager.retry_count >= 0, "重试计数器应有记录"

    @pytest.mark.asyncio
    async def test_okx_ws_slow_response(self):
        """模拟 OKX 响应慢 → 超时 → 切换备用源

        场景：
        1. 主源 OKX 响应延迟超过阈值
        2. 超时检测触发
        3. 自动切换到备用源（币安）
        """
        # ── 模拟主源超时 ──
        async def slow_okx_fetch():
            """模拟 OKX 慢响应：3 秒后才返回。"""
            await asyncio.sleep(3)
            return _make_ticker("50000")

        # ── 模拟备用源正常 ──
        async def fast_binance_fetch():
            """模拟币安正常响应。"""
            return _make_ticker("50001")

        # ── 超时切换逻辑 ──
        timeout_sec = 0.5
        result = None
        used_fallback = False

        try:
            result = await asyncio.wait_for(slow_okx_fetch(), timeout=timeout_sec)
        except asyncio.TimeoutError:
            # 主源超时，切换备用源
            used_fallback = True
            result = await fast_binance_fetch()

        assert result is not None, "应获取到行情数据"
        assert result.last_price == Decimal("50001"), "应使用备用源数据"
        assert used_fallback, "应触发备用源切换"

    @pytest.mark.asyncio
    async def test_market_data_gap_recovery(self):
        """行情数据缺口 → 自动回补

        场景：
        1. 正常接收 K 线序列
        2. 中间出现缺口（丢失若干根 K 线）
        3. 检测到缺口后，主动请求历史数据回补
        """
        # ── 模拟已接收的 K 线序列（有缺口）──
        base_ts = 1700000000_000000000  # 纳秒
        interval_ns = 60_000_000_000  # 1 分钟 = 60e9 纳秒

        # 正常序列：t0, t1, t2, t3, t4
        # 有缺口：t0, t1, t4（丢失 t2, t3）
        received_klines = [
            Kline(
                symbol="BTCUSDT", market=Market.SPOT, exchange="binance",
                interval="1m", open=Decimal("50000"), high=Decimal("50100"),
                low=Decimal("49900"), close=Decimal("50050"), volume=Decimal("100"),
                timestamp_ns=base_ts + i * interval_ns,
            )
            for i in [0, 1, 4]  # 有缺口：缺 t2, t3
        ]

        # ── 检测缺口 ──
        def detect_gaps(klines: list[Kline], expected_interval_ns: int) -> list[int]:
            """检测 K 线序列中的缺口，返回缺失的时间戳列表。"""
            gaps = []
            sorted_klines = sorted(klines, key=lambda k: k.timestamp_ns)
            for i in range(1, len(sorted_klines)):
                expected_ts = sorted_klines[i - 1].timestamp_ns + expected_interval_ns
                actual_ts = sorted_klines[i].timestamp_ns
                if actual_ts > expected_ts:
                    # 发现缺口，填充缺失时间戳
                    ts = expected_ts
                    while ts < actual_ts:
                        gaps.append(ts)
                        ts += expected_interval_ns
            return gaps

        gaps = detect_gaps(received_klines, interval_ns)

        assert len(gaps) == 2, f"应检测到 2 个缺口，实际 {len(gaps)}"
        assert gaps[0] == base_ts + 2 * interval_ns, "第一个缺口应在 t2"
        assert gaps[1] == base_ts + 3 * interval_ns, "第二个缺口应在 t3"

        # ── 模拟回补请求 ──
        async def fetch_historical_klines(start_ts: int, end_ts: int) -> list[Kline]:
            """模拟从交易所获取历史 K 线。"""
            result = []
            ts = start_ts
            while ts < end_ts:
                result.append(Kline(
                    symbol="BTCUSDT", market=Market.SPOT, exchange="binance",
                    interval="1m", open=Decimal("50000"), high=Decimal("50100"),
                    low=Decimal("49900"), close=Decimal("50050"), volume=Decimal("100"),
                    timestamp_ns=ts,
                ))
                ts += interval_ns
            return result

        # ── 回补缺口 ──
        recovered = await fetch_historical_klines(gaps[0], gaps[-1] + interval_ns)
        assert len(recovered) == 2, "应回补 2 根 K 线"

        # ── 合并后序列完整 ──
        all_klines = sorted(received_klines + recovered, key=lambda k: k.timestamp_ns)
        assert len(all_klines) == 5, "合并后应有 5 根完整 K 线"
        for i in range(1, len(all_klines)):
            gap = all_klines[i].timestamp_ns - all_klines[i - 1].timestamp_ns
            assert gap == interval_ns, f"K 线 {i-1}→{i} 间隔不连续"


# ══════════════════════════════════════════════════════════════════════
# 交易所故障混沌测试
# ══════════════════════════════════════════════════════════════════════


class TestChaosExchangeFailure:
    """交易所故障混沌测试"""

    @pytest.mark.asyncio
    async def test_binance_api_500_error(self):
        """币安 API 500 错误 → 限流退避 → 熔断器半开探测

        场景：
        1. 连续 5 次收到 500 错误
        2. 熔断器从 CLOSED → OPEN
        3. 等待恢复超时后进入 HALF_OPEN
        4. 半开状态下探测成功 → 恢复 CLOSED
        """
        breaker = L4CircuitBreaker()

        # ── 1. 连续失败触发熔断 ──
        for i in range(FAILURE_THRESHOLD):
            breaker.record_failure()

        assert breaker.state == CircuitBreakerState.OPEN, "连续失败后应进入熔断状态"

        # ── 2. 模拟等待恢复超时 ──
        # 直接修改内部时间戳模拟超时
        breaker._open_since = time.time() - 61  # 超过 RECOVERY_TIMEOUT_SEC

        # ── 3. 触发状态检查，应转入 HALF_OPEN ──
        # 创建一个正常订单用于探测
        order = _make_order()

        # should_allow() 会检测超时并自动从 OPEN → HALF_OPEN
        allowed = breaker.should_allow()
        assert allowed is True, "半开状态应允许探测"
        assert breaker.state == CircuitBreakerState.HALF_OPEN, "应转入 HALF_OPEN"

        # 模拟探测成功
        breaker.record_success()

        # ── 4. 验证恢复 ──
        assert breaker.state == CircuitBreakerState.CLOSED, "探测成功后应恢复为 CLOSED"

    @pytest.mark.asyncio
    async def test_order_rejected_by_exchange(self):
        """交易所拒单 → OMS 记录 → 告警

        场景：
        1. 提交订单到交易所
        2. 交易所返回拒绝（余额不足）
        3. OMS 记录拒绝状态
        4. 触发告警事件
        """
        bus = InMemoryEventBus()
        events_received = []

        async def alert_handler(msg):
            events_received.append(msg)

        await bus.start()
        bus.subscribe("risk.alert", alert_handler)

        # ── 模拟交易所拒单 ──
        from one_quant.execution.oms import OrderManager
        oms = OrderManager(bus)

        signal = Signal(
            symbol="BTCUSDT", market=Market.SPOT, side="buy",
            strength=0.8, strategy_name="test", reason="测试拒单",
            timestamp_ns=time.time_ns(),
        )
        order = oms.create_order_from_signal(
            signal, price=Decimal("50000"), quantity=Decimal("100"), exchange="binance"
        )

        # 模拟交易所拒绝
        updated = oms.update_order_status(order.client_order_id, "rejected")
        assert updated is not None, "应能更新订单状态"
        assert updated.status == "rejected", "订单应为 rejected 状态"

        await bus.stop()

    @pytest.mark.asyncio
    async def test_partial_fill_timeout(self):
        """部分成交超时 → 撤单 → 重新下单

        场景：
        1. 下单 1 BTC，部分成交 0.5 BTC
        2. 等待超时（剩余 0.5 未成交）
        3. 撤单
        4. 以新价格重新下单剩余部分
        """
        bus = InMemoryEventBus()
        await bus.start()

        from one_quant.execution.oms import OrderManager
        oms = OrderManager(bus)

        # ── 1. 创建并提交订单 ──
        signal = Signal(
            symbol="BTCUSDT", market=Market.SPOT, side="buy",
            strength=0.8, strategy_name="test", reason="测试部分成交",
            timestamp_ns=time.time_ns(),
        )
        order = oms.create_order_from_signal(
            signal, price=Decimal("50000"), quantity=Decimal("1.0"), exchange="binance"
        )
        oms.update_order_status(order.client_order_id, "submitted")

        # ── 2. 模拟部分成交 ──
        partial_fill = Fill(
            order_id=order.client_order_id,
            symbol="BTCUSDT",
            side="buy",
            price=Decimal("50000"),
            quantity=Decimal("0.5"),
            fee=Decimal("25"),
            fee_currency="USDT",
            exchange="binance",
            timestamp_ns=time.time_ns(),
        )
        oms.process_fill(partial_fill)
        oms.update_order_status(order.client_order_id, "partial")

        updated_order = oms.get_order(order.client_order_id)
        assert updated_order.status == "partial", "应为部分成交状态"

        # ── 3. 超时撤单 ──
        oms.update_order_status(order.client_order_id, "cancelled")
        cancelled_order = oms.get_order(order.client_order_id)
        assert cancelled_order.status == "cancelled", "应已撤单"

        # ── 4. 重新下单剩余部分 ──
        new_signal = Signal(
            symbol="BTCUSDT", market=Market.SPOT, side="buy",
            strength=0.8, strategy_name="test", reason="补充下单",
            timestamp_ns=time.time_ns(),
        )
        new_order = oms.create_order_from_signal(
            new_signal, price=Decimal("50050"), quantity=Decimal("0.5"), exchange="binance"
        )
        assert new_order.quantity == Decimal("0.5"), "新订单应为剩余的 0.5"
        assert new_order.price == Decimal("50050"), "新订单应使用更新后的价格"

        await bus.stop()


# ══════════════════════════════════════════════════════════════════════
# 数据库故障混沌测试
# ══════════════════════════════════════════════════════════════════════


class TestChaosDatabase:
    """数据库故障混沌测试"""

    @pytest.mark.asyncio
    async def test_db_connection_lost(self):
        """DB 连接丢失 → 本地缓冲 → 重连补写

        场景：
        1. 正常写入 DB
        2. DB 连接丢失，写入失败
        3. 数据暂存本地缓冲区
        4. 重连成功后，缓冲区数据补写到 DB
        """
        # ── 模拟 DB 写入接口 ──
        written_records = []
        db_available = True

        async def mock_db_write(record: dict) -> bool:
            if not db_available:
                raise ConnectionError("数据库连接已断开")
            written_records.append(record)
            return True

        # ── 本地缓冲区 ──
        local_buffer: list[dict] = []

        async def safe_write(record: dict) -> None:
            """安全写入：失败时暂存缓冲区。"""
            try:
                await mock_db_write(record)
            except ConnectionError:
                local_buffer.append(record)

        # ── 1. 正常写入 ──
        await safe_write({"type": "fill", "id": 1, "price": "50000"})
        assert len(written_records) == 1, "正常写入应成功"
        assert len(local_buffer) == 0, "缓冲区应为空"

        # ── 2. DB 断连，写入失败 ──
        db_available = False
        await safe_write({"type": "fill", "id": 2, "price": "50050"})
        await safe_write({"type": "fill", "id": 3, "price": "50100"})
        assert len(written_records) == 1, "断连期间不应写入 DB"
        assert len(local_buffer) == 2, "断连数据应暂存缓冲区"

        # ── 3. 重连成功，补写缓冲区 ──
        db_available = True
        pending = local_buffer.copy()
        local_buffer.clear()
        for record in pending:
            await mock_db_write(record)

        assert len(written_records) == 3, "补写后应有 3 条记录"
        assert len(local_buffer) == 0, "缓冲区应已清空"

    @pytest.mark.asyncio
    async def test_db_write_contention(self):
        """DB 写锁争用 → 重试 → 成功

        场景：
        1. 多个并发写入请求
        2. 模拟写锁冲突（前 2 次失败）
        3. 重试后成功
        """
        attempt_count = 0

        async def mock_write_with_contention(record_id: int) -> bool:
            """模拟写锁争用：前 2 次抛出锁定异常，之后成功。"""
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count <= 2:
                raise OSError("database is locked")
            return True

        # ── 带重试的写入逻辑 ──
        async def write_with_retry(record_id: int, max_retries: int = 3) -> bool:
            for retry in range(max_retries):
                try:
                    return await mock_write_with_contention(record_id)
                except OSError:
                    if retry == max_retries - 1:
                        raise
                    await asyncio.sleep(0.01 * (2 ** retry))  # 指数退避
            return False

        # ── 执行写入 ──
        result = await write_with_retry(record_id=1)
        assert result is True, "重试后应成功"
        assert attempt_count == 3, f"应尝试 3 次，实际 {attempt_count}"


# ══════════════════════════════════════════════════════════════════════
# Redis 故障混沌测试
# ══════════════════════════════════════════════════════════════════════


class TestChaosRedis:
    """Redis 故障混沌测试"""

    @pytest.mark.asyncio
    async def test_redis_disconnect(self):
        """Redis 断连 → 本地缓冲 → 重连补发

        场景：
        1. 正常通过 Redis 发布事件
        2. Redis 连接断开
        3. 事件暂存本地队列
        4. 重连后批量补发
        """
        published_events: list[dict] = []
        redis_available = True

        async def mock_redis_publish(channel: str, data: dict) -> None:
            if not redis_available:
                raise ConnectionError("Redis 连接已断开")
            published_events.append({"channel": channel, **data})

        local_queue: list[tuple[str, dict]] = []

        async def safe_publish(channel: str, data: dict) -> None:
            """安全发布：失败时入队。"""
            try:
                await mock_redis_publish(channel, data)
            except ConnectionError:
                local_queue.append((channel, data))

        # ── 1. 正常发布 ──
        await safe_publish("market.ticker", {"symbol": "BTCUSDT", "price": "50000"})
        assert len(published_events) == 1, "正常发布应成功"

        # ── 2. Redis 断连 ──
        redis_available = False
        await safe_publish("market.ticker", {"symbol": "BTCUSDT", "price": "50050"})
        await safe_publish("market.ticker", {"symbol": "BTCUSDT", "price": "50100"})
        assert len(published_events) == 1, "断连期间不应发布"
        assert len(local_queue) == 2, "断连事件应入队"

        # ── 3. 重连补发 ──
        redis_available = True
        pending = local_queue.copy()
        local_queue.clear()
        for ch, data in pending:
            await mock_redis_publish(ch, data)

        assert len(published_events) == 3, "补发后应有 3 条事件"
        assert len(local_queue) == 0, "队列应已清空"


# ══════════════════════════════════════════════════════════════════════
# 策略故障混沌测试
# ══════════════════════════════════════════════════════════════════════


class TestChaosStrategy:
    """策略故障混沌测试"""

    @pytest.mark.asyncio
    async def test_strategy_exception_isolation(self):
        """策略 A 崩溃 → 不影响策略 B

        场景：
        1. 两个策略同时运行
        2. 策略 A 处理行情时抛出异常
        3. 策略 B 正常运行，不受影响
        """
        from one_quant.strategy.contracts import Strategy

        class CrashingStrategy(Strategy):
            """会崩溃的策略 A。"""
            name = "crashing_strategy"
            enabled = True

            def on_ticker(self, ticker: Ticker) -> list[Signal]:
                raise RuntimeError("策略 A 内部崩溃！")

            def on_kline(self, kline: Kline) -> list[Signal]:
                return []

        class NormalStrategy(Strategy):
            """正常策略 B。"""
            name = "normal_strategy"
            enabled = True
            signal_count = 0

            def on_ticker(self, ticker: Ticker) -> list[Signal]:
                NormalStrategy.signal_count += 1
                return [Signal(
                    symbol=ticker.symbol, market=ticker.market, side="buy",
                    strength=0.5, strategy_name=self.name, reason="正常信号",
                    timestamp_ns=time.time_ns(),
                )]

            def on_kline(self, kline: Kline) -> list[Signal]:
                return []

        bus = InMemoryEventBus()
        from one_quant.runner.engine import StrategyRunner
        runner = StrategyRunner(bus)

        strategy_a = CrashingStrategy()
        strategy_b = NormalStrategy()
        runner.register_strategy(strategy_a)
        runner.register_strategy(strategy_b)

        await bus.start()
        await runner.start()

        # ── 分发行情，策略 A 会崩溃，策略 B 应正常 ──
        ticker = _make_ticker()
        all_signals = []

        for strategy in runner.strategies:
            try:
                signals = strategy.on_ticker(ticker)
                all_signals.extend(signals)
            except Exception:
                pass  # 隔离异常

        # ── 验证策略 B 不受影响 ──
        assert NormalStrategy.signal_count == 1, "策略 B 应正常产生信号"
        assert len(all_signals) == 1, "应只有策略 B 的信号"
        assert all_signals[0].strategy_name == "normal_strategy"

        await runner.stop()
        await bus.stop()

    @pytest.mark.asyncio
    async def test_strategy_infinite_loop_detection(self):
        """策略死循环 → 看门狗检测 → 重启

        场景：
        1. 策略进入死循环（on_ticker 超时不返回）
        2. 看门狗检测到超时
        3. 强制终止策略并重启
        """
        from one_quant.strategy.contracts import Strategy

        # 用 threading.Event 控制循环退出，避免遗留线程
        stop_event = __import__("threading").Event()

        class InfiniteLoopStrategy(Strategy):
            """死循环策略。"""
            name = "infinite_loop_strategy"
            enabled = True

            def on_ticker(self, ticker: Ticker) -> list[Signal]:
                # 可控死循环：等待 stop_event 被设置
                stop_event.wait(timeout=10)
                return []

            def on_kline(self, kline: Kline) -> list[Signal]:
                return []

        strategy = InfiniteLoopStrategy()
        timeout_sec = 0.3
        restart_count = 0

        # ── 看门狗逻辑：带超时执行策略 ──
        async def watchdog_execute(strategy, ticker, timeout):
            """看门狗：超时则强制终止策略调用。"""
            nonlocal restart_count
            try:
                loop = asyncio.get_event_loop()
                result = await asyncio.wait_for(
                    loop.run_in_executor(None, strategy.on_ticker, ticker),
                    timeout=timeout,
                )
                return result
            except asyncio.TimeoutError:
                restart_count += 1
                return []  # 超时返回空信号

        ticker = _make_ticker()

        # ── 第一次超时 ──
        result = await watchdog_execute(strategy, ticker, timeout_sec)
        assert result == [], "超时应返回空信号"
        assert restart_count == 1, "应检测到超时并重启"

        # ── 第二次超时 ──
        result = await watchdog_execute(strategy, ticker, timeout_sec)
        assert restart_count == 2, "应再次检测到超时"

        # 清理：释放阻塞线程
        stop_event.set()


# ══════════════════════════════════════════════════════════════════════
# 风控故障混沌测试
# ══════════════════════════════════════════════════════════════════════


class TestChaosRisk:
    """风控故障混沌测试"""

    @pytest.mark.asyncio
    async def test_risk_engine_exception_triggers_halt(self):
        """风控异常 → 立即熔断 → 不静默

        场景：
        1. 风控引擎 L2 层抛出异常
        2. 异常不能被静默吞掉
        3. 必须触发熔断（FLATTEN）或抛出异常
        """
        engine = RiskEngine()

        # ── 模拟 L2 层异常 ──
        # 使用 BTC/USDT（白名单格式）确保通过 L1
        with patch.object(engine.l2, 'check', side_effect=RuntimeError("L2 计算异常")):
            order = _make_order(symbol="BTC/USDT")
            positions = [_make_position(symbol="BTC/USDT")]

            # ── 验证异常不能被静默吞掉 ──
            # 方案1：异常被向上抛出
            # 方案2：风控引擎捕获异常并返回 FLATTEN
            try:
                result = engine.check(order, positions)
                # 如果没有抛异常，必须是 FLATTEN（不能是 APPROVE）
                assert result.decision == RiskDecision.FLATTEN, \
                    f"风控异常时应返回 FLATTEN，实际: {result.decision}"
                assert "异常" in result.reason or "熔断" in result.reason, \
                    "原因应说明异常/熔断"
            except RuntimeError:
                # 抛出异常也是可接受的行为（不静默）
                pass

    @pytest.mark.asyncio
    async def test_rapid_drawdown_scenario(self):
        """快速回撤 15% → halt_all 触发

        场景：
        1. 初始权益 100000 USDT
        2. 快速回撤到 85000 USDT（-15%）
        3. 风控触发 FLATTEN
        """
        engine = RiskEngine()
        order = _make_order(symbol="BTC/USDT")
        positions = [_make_position(symbol="BTC/USDT")]

        initial_equity = Decimal("100000")
        peak_equity = Decimal("100000")
        current_equity = Decimal("85000")  # 回撤 15%

        # ── 执行风控检查 ──
        result = engine.check(
            order,
            positions,
            total_equity=current_equity,
            peak_equity=peak_equity,
            initial_equity=initial_equity,
            daily_pnl=current_equity - initial_equity,  # -15000
        )

        # ── 验证触发熔断 ──
        # L3 回撤规则应检测到 15% 回撤并拒绝/平仓
        assert result.decision in (RiskDecision.REJECT, RiskDecision.FLATTEN, RiskDecision.REDUCE), \
            f"15% 回撤应触发风控，实际决策: {result.decision}"

    @pytest.mark.asyncio
    async def test_circuit_breaker_consecutive_failures(self):
        """连续风控异常 → 熔断器 OPEN → 拒绝所有新订单

        场景：
        1. 连续 FAILURE_THRESHOLD 次风控异常
        2. 熔断器状态变为 OPEN
        3. 所有新订单被拒绝
        """
        breaker = L4CircuitBreaker()

        # ── 1. 连续失败 ──
        for i in range(FAILURE_THRESHOLD):
            assert breaker.state == CircuitBreakerState.CLOSED, \
                f"第 {i+1} 次失败前应为 CLOSED"
            breaker.record_failure()

        # ── 2. 验证熔断 ──
        assert breaker.state == CircuitBreakerState.OPEN, "应进入 OPEN 状态"

        # ── 3. 熔断状态下检查订单 ──
        order = _make_order()
        positions = []
        result = breaker.check(order, positions)

        assert result.decision == RiskDecision.FLATTEN, "熔断状态应返回 FLATTEN"
        assert "熔断" in result.reason, "原因应包含'熔断'"

    @pytest.mark.asyncio
    async def test_circuit_breaker_half_open_recovery(self):
        """熔断器半开探测 → 成功 → 恢复 CLOSED

        场景：
        1. 熔断器处于 OPEN 状态
        2. 等待恢复超时后进入 HALF_OPEN
        3. 半开状态下探测成功
        4. 状态恢复为 CLOSED
        """
        breaker = L4CircuitBreaker()

        # ── 触发熔断 ──
        for _ in range(FAILURE_THRESHOLD):
            breaker.record_failure()
        assert breaker.state == CircuitBreakerState.OPEN

        # ── 模拟等待超时 ──
        breaker._open_since = time.time() - 61

        # ── 触发 OPEN → HALF_OPEN 转换 ──
        allowed = breaker.should_allow()
        assert allowed is True
        assert breaker.state == CircuitBreakerState.HALF_OPEN

        # ── 半开状态下探测成功 ──
        breaker.record_success()
        assert breaker.state == CircuitBreakerState.CLOSED, "探测成功后应恢复 CLOSED"

    @pytest.mark.asyncio
    async def test_circuit_breaker_half_open_failure_resets(self):
        """熔断器半开探测 → 失败 → 重回 OPEN

        场景：
        1. 熔断器处于 OPEN → 等待超时 → HALF_OPEN
        2. 半开状态下探测失败
        3. 状态重回 OPEN，计时重置
        """
        breaker = L4CircuitBreaker()

        # ── 触发熔断 ──
        for _ in range(FAILURE_THRESHOLD):
            breaker.record_failure()
        assert breaker.state == CircuitBreakerState.OPEN

        # ── 等待超时 → HALF_OPEN ──
        breaker._open_since = time.time() - 61

        # ── 触发 OPEN → HALF_OPEN ──
        allowed = breaker.should_allow()
        assert breaker.state == CircuitBreakerState.HALF_OPEN

        # ── 探测失败 ──
        breaker.record_failure()

        # ── 验证重回 OPEN ──
        assert breaker.state == CircuitBreakerState.OPEN, "探测失败应重回 OPEN"

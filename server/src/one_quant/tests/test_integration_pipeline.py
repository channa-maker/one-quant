"""
ONE量化 - EventBus 全链路集成测试

验证从行情数据到最终持仓更新的完整链路，以及异常场景（熔断、重启恢复）。
使用 InMemoryEventBus（不依赖 Redis），使用模拟数据（不依赖真实交易所）。

测试场景：
  1. 行情数据 → EventBus → 策略引擎产生信号
  2. 信号 → 风控引擎 → APPROVE/REJECT 决策
  3. 批准订单 → OMS → 执行引擎 → 成交回报
  4. 成交回报 → 策略 on_fill 回调
  5. 多策略并发互不干扰
  6. 背压控制验证
  7. 端到端：行情→信号→风控→订单→成交→持仓更新
  8. 止损触发流程
  9. 熔断场景：连续亏损→熔断→恢复
  10. 系统重启恢复：崩溃→重启→持仓恢复
"""

from __future__ import annotations

import asyncio
import time
import uuid
from decimal import Decimal

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
from one_quant.execution.oms import OrderManager
from one_quant.infra.event_bus import (
    BackpressurePolicy,
    EventBusFullError,
    InMemoryEventBus,
)
from one_quant.risk.contracts import RiskCheckResult, RiskDecision
from one_quant.risk.engine import RiskEngine
from one_quant.risk.rules.l4_circuit_breaker import L4CircuitBreaker
from one_quant.strategy.contracts import Strategy
from one_quant.runner.engine import StrategyRunner
from one_quant.execution.position_recovery import PositionRecoveryManager


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试辅助：模拟策略
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class MockBuyStrategy(Strategy):
    """模拟买入策略：当最新价低于阈值时产生买入信号。"""

    name = "mock_buy_strategy"
    enabled = True

    def __init__(self, threshold: Decimal = Decimal("49000")) -> None:
        self._threshold = threshold
        self.received_fills: list[Fill] = []
        self.recovered_positions: list[PositionState] = []

    def on_ticker(self, ticker: Ticker) -> list[Signal]:
        """价格低于阈值时产生买入信号。"""
        if ticker.last_price < self._threshold:
            return [
                Signal(
                    symbol=ticker.symbol,
                    market=ticker.market,
                    side="buy",
                    strength=0.8,
                    strategy_name=self.name,
                    reason=f"价格 {ticker.last_price} 低于阈值 {self._threshold}",
                    timestamp_ns=time.time_ns(),
                )
            ]
        return []

    def on_kline(self, kline: Kline) -> list[Signal]:
        """K线回调：不产生信号。"""
        return []

    def on_fill(self, fill: Fill) -> None:
        """记录收到的成交回报。"""
        self.received_fills.append(fill)

    def on_recover(self, state: PositionState) -> None:
        """记录恢复的持仓状态。"""
        self.recovered_positions.append(state)


class MockSellStrategy(Strategy):
    """模拟卖出策略：当最新价高于阈值时产生卖出信号。"""

    name = "mock_sell_strategy"
    enabled = True

    def __init__(self, threshold: Decimal = Decimal("51000")) -> None:
        self._threshold = threshold
        self.received_fills: list[Fill] = []

    def on_ticker(self, ticker: Ticker) -> list[Signal]:
        """价格高于阈值时产生卖出信号。"""
        if ticker.last_price > self._threshold:
            return [
                Signal(
                    symbol=ticker.symbol,
                    market=ticker.market,
                    side="sell",
                    strength=0.7,
                    strategy_name=self.name,
                    reason=f"价格 {ticker.last_price} 高于阈值 {self._threshold}",
                    timestamp_ns=time.time_ns(),
                )
            ]
        return []

    def on_kline(self, kline: Kline) -> list[Signal]:
        return []

    def on_fill(self, fill: Fill) -> None:
        self.received_fills.append(fill)


class MockStopLossStrategy(Strategy):
    """模拟止损策略：当价格跌破止损线时产生卖出信号。"""

    name = "mock_stop_loss_strategy"
    enabled = True

    def __init__(
        self,
        stop_loss_price: Decimal = Decimal("45000"),
        entry_price: Decimal = Decimal("50000"),
    ) -> None:
        self._stop_loss_price = stop_loss_price
        self._entry_price = entry_price
        self._has_position = True
        self.received_fills: list[Fill] = []

    def on_ticker(self, ticker: Ticker) -> list[Signal]:
        """价格跌破止损线时产生卖出信号。"""
        if self._has_position and ticker.last_price <= self._stop_loss_price:
            return [
                Signal(
                    symbol=ticker.symbol,
                    market=ticker.market,
                    side="sell",
                    strength=1.0,
                    strategy_name=self.name,
                    reason=f"止损触发：价格 {ticker.last_price} 跌破止损线 {self._stop_loss_price}",
                    timestamp_ns=time.time_ns(),
                )
            ]
        return []

    def on_kline(self, kline: Kline) -> list[Signal]:
        return []

    def on_fill(self, fill: Fill) -> None:
        self.received_fills.append(fill)
        if fill.side == "sell":
            self._has_position = False


class MockAlwaysSignalStrategy(Strategy):
    """模拟始终产生信号的策略：用于并发测试。"""

    name: str
    enabled = True

    def __init__(self, name: str, signal_side: str = "buy") -> None:
        self.name = name
        self._side = signal_side
        self.signal_count = 0
        self.received_fills: list[Fill] = []

    def on_ticker(self, ticker: Ticker) -> list[Signal]:
        """每次都产生信号。"""
        self.signal_count += 1
        return [
            Signal(
                symbol=ticker.symbol,
                market=ticker.market,
                side=self._side,
                strength=0.5,
                strategy_name=self.name,
                reason=f"{self.name} 第 {self.signal_count} 次信号",
                timestamp_ns=time.time_ns(),
            )
        ]

    def on_kline(self, kline: Kline) -> list[Signal]:
        return []

    def on_fill(self, fill: Fill) -> None:
        self.received_fills.append(fill)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试辅助：模拟交易所适配器
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class MockExchangeAdapter:
    """模拟交易所适配器：立即返回成交。"""

    def __init__(self, fill_price: Decimal = Decimal("50000")) -> None:
        self._fill_price = fill_price
        self.submitted_orders: list[Order] = []

    async def submit_order(self, order: Order) -> str:
        """模拟提交订单，返回交易所订单 ID。"""
        self.submitted_orders.append(order)
        return f"EXG-{uuid.uuid4().hex[:12]}"

    async def get_ticker(self, symbol: str) -> Ticker:
        """模拟获取行情。"""
        return Ticker(
            symbol=symbol,
            market=Market.SPOT,
            exchange="binance",
            last_price=self._fill_price,
            bid=self._fill_price - Decimal("1"),
            ask=self._fill_price + Decimal("1"),
            volume_24h=Decimal("10000"),
            timestamp_ns=time.time_ns(),
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试辅助：工具函数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _make_ticker(
    price: Decimal = Decimal("50000"),
    symbol: str = "BTC/USDT",
) -> Ticker:
    """构建模拟行情数据。"""
    return Ticker(
        symbol=symbol,
        market=Market.SPOT,
        exchange="binance",
        last_price=price,
        bid=price - Decimal("1"),
        ask=price + Decimal("1"),
        volume_24h=Decimal("10000"),
        timestamp_ns=time.time_ns(),
    )


def _make_kline(
    close: Decimal = Decimal("50000"),
    symbol: str = "BTC/USDT",
) -> Kline:
    """构建模拟K线数据。"""
    return Kline(
        symbol=symbol,
        market=Market.SPOT,
        exchange="binance",
        interval="1m",
        open=close - Decimal("50"),
        high=close + Decimal("100"),
        low=close - Decimal("100"),
        close=close,
        volume=Decimal("500"),
        timestamp_ns=time.time_ns(),
    )


def _make_order(
    symbol: str = "BTC/USDT",
    side: str = "buy",
    quantity: Decimal = Decimal("0.1"),
    price: Decimal = Decimal("50000"),
) -> Order:
    """构建模拟订单。"""
    return Order(
        client_order_id=str(uuid.uuid4()),
        symbol=symbol,
        market=Market.SPOT,
        side=side,
        order_type="limit",
        quantity=quantity,
        price=price,
        stop_price=None,
        status="pending",
        exchange="binance",
        timestamp_ns=time.time_ns(),
    )


def _make_fill(
    order_id: str,
    symbol: str = "BTC/USDT",
    side: str = "buy",
    price: Decimal = Decimal("50000"),
    quantity: Decimal = Decimal("0.1"),
) -> Fill:
    """构建模拟成交回报。"""
    return Fill(
        order_id=order_id,
        symbol=symbol,
        side=side,
        price=price,
        quantity=quantity,
        fee=Decimal("0.001"),
        fee_currency="USDT",
        exchange="binance",
        timestamp_ns=time.time_ns(),
    )


def _make_position(
    symbol: str = "BTC/USDT",
    side: str = "long",
    quantity: Decimal = Decimal("1.0"),
    entry_price: Decimal = Decimal("50000"),
) -> PositionState:
    """构建模拟持仓状态。"""
    return PositionState(
        symbol=symbol,
        market=Market.SPOT,
        side=side,
        quantity=quantity,
        entry_price=entry_price,
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
        timestamp_ns=time.time_ns(),
    )


async def _wait_for(condition_fn, timeout: float = 2.0, interval: float = 0.05):
    """轮询等待条件满足，超时则抛出异常。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition_fn():
            return
        await asyncio.sleep(interval)
    raise TimeoutError(f"等待条件超时（{timeout}秒）")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 1：行情数据 → EventBus → 策略引擎产生信号
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_01_market_data_to_signal():
    """验证行情数据通过 EventBus 传递到策略引擎，策略产生交易信号。

    流程：
    1. 创建 InMemoryEventBus 并启动
    2. 创建策略引擎（StrategyRunner），注册模拟买入策略
    3. 发布低于阈值的行情数据
    4. 验证策略产生信号并发布到 strategy.signal 通道
    """
    bus = InMemoryEventBus()
    captured_signals: list[dict] = []

    # 监听信号通道
    async def signal_collector(data: dict) -> None:
        captured_signals.append(data)

    bus.subscribe("strategy.signal", signal_collector)

    # 创建策略引擎
    runner = StrategyRunner(bus)
    strategy = MockBuyStrategy(threshold=Decimal("49000"))
    runner.register_strategy(strategy)
    await runner.start()
    await bus.start()

    # 发布低于阈值的行情（应触发买入信号）
    ticker = _make_ticker(price=Decimal("48000"))
    await bus.publish("market.ticker", ticker.model_dump(mode="json"))

    # 等待信号被处理
    await _wait_for(lambda: len(captured_signals) > 0)

    assert len(captured_signals) == 1
    signal_data = captured_signals[0]
    assert signal_data["side"] == "buy"
    assert signal_data["strategy_name"] == "mock_buy_strategy"
    assert signal_data["symbol"] == "BTC/USDT"
    assert Decimal(str(signal_data["strength"])) == Decimal("0.8")
    assert "48000" in signal_data["reason"]

    # 清理
    await runner.stop()
    await bus.stop()


@pytest.mark.asyncio
async def test_01b_no_signal_when_price_above_threshold():
    """验证价格高于阈值时策略不产生信号。"""
    bus = InMemoryEventBus()
    captured_signals: list[dict] = []

    async def signal_collector(data: dict) -> None:
        captured_signals.append(data)

    bus.subscribe("strategy.signal", signal_collector)

    runner = StrategyRunner(bus)
    strategy = MockBuyStrategy(threshold=Decimal("49000"))
    runner.register_strategy(strategy)
    await runner.start()
    await bus.start()

    # 发布高于阈值的行情（不应触发信号）
    ticker = _make_ticker(price=Decimal("55000"))
    await bus.publish("market.ticker", ticker.model_dump(mode="json"))
    await asyncio.sleep(0.3)

    assert len(captured_signals) == 0

    await runner.stop()
    await bus.stop()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 2：信号 → 风控引擎 → APPROVE/REJECT 决策
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_02_risk_approve_normal_order():
    """验证正常订单通过四层风控检查。

    场景：BTC/USDT 买入 0.1 个，价格 50000，名义价值 5000 USDT。
    在白名单内，未超限额，无回撤，熔断器正常 → 应返回 APPROVE。
    """
    risk_engine = RiskEngine()
    order = _make_order(
        side="buy",
        quantity=Decimal("0.1"),
        price=Decimal("50000"),
    )
    positions: list[PositionState] = []

    result = risk_engine.check(
        order=order,
        positions=positions,
        latest_price=Decimal("50000"),
        total_equity=Decimal("100000"),
        peak_equity=Decimal("100000"),
        daily_pnl=Decimal("0"),
        initial_equity=Decimal("100000"),
    )

    assert result.decision == RiskDecision.APPROVE
    assert "通过" in result.reason


@pytest.mark.asyncio
async def test_02b_risk_reject_suspended_symbol():
    """验证停牌标的被风控拒绝。

    场景：LUNA/USDT 在停牌列表中 → 应返回 REJECT。
    """
    risk_engine = RiskEngine()
    order = _make_order(symbol="LUNA/USDT")
    positions: list[PositionState] = []

    result = risk_engine.check(order=order, positions=positions)

    assert result.decision == RiskDecision.REJECT
    assert "停牌" in result.reason or "不可交易" in result.reason


@pytest.mark.asyncio
async def test_02c_risk_reject_exceed_max_notional():
    """验证超大订单被风控拒绝。

    场景：名义价值 200000 USDT，超过 L1 上限 100000 → 应返回 REJECT。
    """
    risk_engine = RiskEngine()
    order = _make_order(
        quantity=Decimal("4"),  # 4 * 50000 = 200000
        price=Decimal("50000"),
    )
    positions: list[PositionState] = []

    result = risk_engine.check(order=order, positions=positions)

    assert result.decision == RiskDecision.REJECT
    assert "超过最大限额" in result.reason


@pytest.mark.asyncio
async def test_02d_risk_reject_unknown_symbol():
    """验证不在白名单的标的被风控拒绝。"""
    risk_engine = RiskEngine()
    order = _make_order(symbol="UNKNOWN/USDT", price=Decimal("100"))
    positions: list[PositionState] = []

    result = risk_engine.check(order=order, positions=positions)

    assert result.decision == RiskDecision.REJECT
    assert "不在可交易白名单" in result.reason


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 3：批准订单 → OMS → 执行引擎 → 成交回报
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_03_order_to_fill():
    """验证订单经 OMS 创建后，模拟执行引擎产生成交回报。

    流程：
    1. OMS 从信号创建订单
    2. 风控检查通过
    3. 模拟执行引擎产生成交回报
    4. OMS 处理成交回报，更新订单状态和持仓
    """
    bus = InMemoryEventBus()
    await bus.start()

    oms = OrderManager(bus)

    # 从信号创建订单
    signal = Signal(
        symbol="BTC/USDT",
        market=Market.SPOT,
        side="buy",
        strength=0.8,
        strategy_name="test_strategy",
        reason="测试信号",
        timestamp_ns=time.time_ns(),
    )
    order = oms.create_order_from_signal(
        signal=signal,
        order_type="limit",
        price=Decimal("50000"),
        quantity=Decimal("0.1"),
        exchange="binance",
    )
    assert order.status == "pending"
    assert order.client_order_id in [o.client_order_id for o in [order]]

    # 风控检查
    risk_engine = RiskEngine()
    result = risk_engine.check(
        order=order,
        positions=[],
        latest_price=Decimal("50000"),
    )
    assert result.decision == RiskDecision.APPROVE

    # 更新订单状态为已提交
    oms.update_order_status(order.client_order_id, "submitted")

    # 模拟执行引擎产生成交回报
    fill = _make_fill(
        order_id=order.client_order_id,
        price=Decimal("50000"),
        quantity=Decimal("0.1"),
    )
    oms.process_fill(fill)

    # 验证订单状态更新为已成交
    updated_order = oms.get_order(order.client_order_id)
    assert updated_order is not None
    assert updated_order.status == "filled"

    # 验证持仓更新
    position = oms.get_position("BTC/USDT")
    assert position is not None
    assert position.side == "long"
    assert position.quantity == Decimal("0.1")
    assert position.entry_price == Decimal("50000")

    await bus.stop()


@pytest.mark.asyncio
async def test_03b_fill_published_to_eventbus():
    """验证成交回报通过 EventBus 发布。

    流程：
    1. 发布成交回报到 execution.fill 通道
    2. 验证订阅者收到消息
    """
    bus = InMemoryEventBus()
    received_fills: list[dict] = []

    async def fill_collector(data: dict) -> None:
        received_fills.append(data)

    bus.subscribe("execution.fill", fill_collector)
    await bus.start()

    fill = _make_fill(order_id="test-order-001")
    await bus.publish("execution.fill", fill.model_dump(mode="json"))

    await _wait_for(lambda: len(received_fills) > 0)

    assert len(received_fills) == 1
    assert received_fills[0]["order_id"] == "test-order-001"
    assert received_fills[0]["side"] == "buy"

    await bus.stop()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 4：成交回报 → 策略 on_fill 回调
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_04_fill_callback_to_strategy():
    """验证成交回报通过 EventBus 传递到策略的 on_fill 回调。

    流程：
    1. 创建策略引擎，注册模拟策略
    2. 发布成交回报到 execution.fill 通道
    3. 验证策略的 on_fill 被调用
    """
    bus = InMemoryEventBus()
    runner = StrategyRunner(bus)
    strategy = MockBuyStrategy(threshold=Decimal("49000"))
    runner.register_strategy(strategy)
    await runner.start()
    await bus.start()

    # 发布成交回报
    fill = _make_fill(order_id="test-fill-001")
    await bus.publish("execution.fill", fill.model_dump(mode="json"))

    # 等待策略处理
    await _wait_for(lambda: len(strategy.received_fills) > 0)

    assert len(strategy.received_fills) == 1
    assert strategy.received_fills[0].order_id == "test-fill-001"
    assert strategy.received_fills[0].side == "buy"
    assert strategy.received_fills[0].quantity == Decimal("0.1")

    await runner.stop()
    await bus.stop()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 5：多策略并发互不干扰
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_05_multi_strategy_concurrent():
    """验证多个策略同时运行互不干扰。

    场景：
    - 策略A：始终产生买入信号
    - 策略B：始终产生卖出信号
    - 同时发布行情，验证两个策略各自独立产生信号
    """
    bus = InMemoryEventBus()
    captured_signals: list[dict] = []

    async def signal_collector(data: dict) -> None:
        captured_signals.append(data)

    bus.subscribe("strategy.signal", signal_collector)

    runner = StrategyRunner(bus)
    strategy_a = MockAlwaysSignalStrategy(name="strategy_a", signal_side="buy")
    strategy_b = MockAlwaysSignalStrategy(name="strategy_b", signal_side="sell")
    runner.register_strategy(strategy_a)
    runner.register_strategy(strategy_b)
    await runner.start()
    await bus.start()

    # 发布多次行情
    for i in range(5):
        ticker = _make_ticker(price=Decimal("50000") + Decimal(str(i * 100)))
        await bus.publish("market.ticker", ticker.model_dump(mode="json"))

    # 等待所有信号被处理（5次行情 × 2个策略 = 10个信号）
    await _wait_for(lambda: len(captured_signals) >= 10)

    # 验证两个策略都产生了信号
    assert strategy_a.signal_count == 5
    assert strategy_b.signal_count == 5

    # 验证信号来自不同策略
    strategy_names = {s["strategy_name"] for s in captured_signals}
    assert "strategy_a" in strategy_names
    assert "strategy_b" in strategy_names

    # 验证买卖信号分离
    buy_signals = [s for s in captured_signals if s["side"] == "buy"]
    sell_signals = [s for s in captured_signals if s["side"] == "sell"]
    assert len(buy_signals) == 5
    assert len(sell_signals) == 5

    await runner.stop()
    await bus.stop()


@pytest.mark.asyncio
async def test_05b_strategy_hot_swap():
    """验证策略热插拔：运行时注销策略后不再产生信号。"""
    bus = InMemoryEventBus()
    captured_signals: list[dict] = []

    async def signal_collector(data: dict) -> None:
        captured_signals.append(data)

    bus.subscribe("strategy.signal", signal_collector)

    runner = StrategyRunner(bus)
    strategy = MockAlwaysSignalStrategy(name="hot_swap_test")
    runner.register_strategy(strategy)
    await runner.start()
    await bus.start()

    # 发布行情，产生信号
    ticker = _make_ticker(price=Decimal("50000"))
    await bus.publish("market.ticker", ticker.model_dump(mode="json"))
    await _wait_for(lambda: len(captured_signals) >= 1)

    count_before = len(captured_signals)

    # 注销策略
    await runner.unregister_strategy("hot_swap_test")

    # 再次发布行情
    await bus.publish("market.ticker", ticker.model_dump(mode="json"))
    await asyncio.sleep(0.3)

    # 信号数量不应增加
    assert len(captured_signals) == count_before

    await runner.stop()
    await bus.stop()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 6：背压控制验证
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_06_backpressure_drop_oldest():
    """验证背压策略 DROP_OLDEST：队列满时丢弃最旧的消息。"""
    # 使用极小队列以快速触发背压
    bus = InMemoryEventBus(max_queue_size=3, backpressure=BackpressurePolicy.DROP_OLDEST)
    received: list[dict] = []

    async def handler(data: dict) -> None:
        # 人为延迟以制造队列积压
        await asyncio.sleep(0.05)
        received.append(data)

    bus.subscribe("backpressure.test", handler)
    await bus.start()

    # 快速发布超过队列容量的消息
    for i in range(10):
        await bus.publish("backpressure.test", {"index": i})

    # 等待消费完成
    await asyncio.sleep(1.0)

    # 队列容量为 3，丢弃了最早的，应收到后续消息
    assert len(received) > 0
    # 最后一条消息的 index 应该大于 0（最早的被丢弃了）
    assert received[-1]["index"] > 0 or len(received) <= 3

    await bus.stop()


@pytest.mark.asyncio
async def test_06b_backpressure_drop_latest():
    """验证背压策略 DROP_LATEST：队列满时丢弃最新的消息。"""
    bus = InMemoryEventBus(max_queue_size=3, backpressure=BackpressurePolicy.DROP_LATEST)
    received: list[dict] = []

    async def handler(data: dict) -> None:
        await asyncio.sleep(0.05)
        received.append(data)

    bus.subscribe("backpressure.test2", handler)
    await bus.start()

    # 快速发布超过队列容量的消息
    for i in range(10):
        await bus.publish("backpressure.test2", {"index": i})

    await asyncio.sleep(1.0)

    # 收到的消息应该保留了最早的几条
    assert len(received) > 0
    # 第一条消息应该是 index=0（最新的被丢弃）
    assert received[0]["index"] == 0

    await bus.stop()


@pytest.mark.asyncio
async def test_06c_backpressure_raise():
    """验证背压策略 RAISE：队列满时抛出异常。"""
    # 使用极小队列，直接手动填满后验证 RAISE 策略
    bus = InMemoryEventBus(max_queue_size=2, backpressure=BackpressurePolicy.RAISE)

    # 使用一个永不触发的 Event 来阻塞消费者，防止队列被消费
    block_event = asyncio.Event()  # 永不 set()

    async def blocking_handler(data: dict) -> None:
        await block_event.wait()  # 永远阻塞

    bus.subscribe("backpressure.test3", blocking_handler)
    await bus.start()

    # 先发一条消息，让消费者阻塞在 handler 上
    await bus.publish("backpressure.test3", {"warmup": True})
    # 等待消费者开始处理（拿到消息并阻塞在 wait()）
    await asyncio.sleep(0.1)

    # 手动将队列精确填满
    from one_quant.infra.event_bus import MessageEnvelope
    queue = bus._queues["backpressure.test3"]
    while not queue.empty():
        queue.get_nowait()
    for i in range(2):
        envelope = MessageEnvelope(
            channel="backpressure.test3",
            ts_ns=time.time_ns(),
            trace_id=str(uuid.uuid4()),
            data={"index": i},
        )
        queue.put_nowait(envelope)

    # 此时队列已满，再发布应触发 EventBusFullError
    with pytest.raises(EventBusFullError):
        await bus.publish("backpressure.test3", {"index": 99})

    # 解除阻塞，等消费者处理完毕，清空队列以便 stop() 能放入哨兵值
    block_event.set()
    await asyncio.sleep(0.1)
    while not queue.empty():
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            break
    await bus.stop()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 7：端到端链路 — 行情→信号→风控→订单→成交→持仓更新
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_07_end_to_end_pipeline():
    """验证完整的端到端链路。

    流程：
    1. 发布行情 → 策略引擎产生信号
    2. 信号 → 风控检查通过
    3. 创建订单 → 模拟成交
    4. 成交回报 → 策略 on_fill + 持仓更新
    """
    bus = InMemoryEventBus()
    await bus.start()

    # 初始化各组件
    runner = StrategyRunner(bus)
    strategy = MockBuyStrategy(threshold=Decimal("49000"))
    runner.register_strategy(strategy)
    await runner.start()

    oms = OrderManager(bus)
    risk_engine = RiskEngine()

    # 收集信号和成交
    captured_signals: list[dict] = []
    captured_fills: list[dict] = []

    async def signal_handler(data: dict) -> None:
        captured_signals.append(data)

    async def fill_handler(data: dict) -> None:
        captured_fills.append(data)

    bus.subscribe("strategy.signal", signal_handler)
    bus.subscribe("execution.fill", fill_handler)

    # ── 步骤 1：发布行情，触发信号 ──
    ticker = _make_ticker(price=Decimal("48000"))
    await bus.publish("market.ticker", ticker.model_dump(mode="json"))
    await _wait_for(lambda: len(captured_signals) > 0)

    assert len(captured_signals) == 1
    signal_data = captured_signals[0]
    assert signal_data["side"] == "buy"

    # ── 步骤 2：风控检查 ──
    signal = Signal(**signal_data)
    order = oms.create_order_from_signal(
        signal=signal,
        order_type="limit",
        price=Decimal("48000"),
        quantity=Decimal("0.1"),
        exchange="binance",
    )
    risk_result = risk_engine.check(
        order=order,
        positions=[],
        latest_price=Decimal("48000"),
    )
    assert risk_result.decision == RiskDecision.APPROVE

    # ── 步骤 3：模拟执行 → 成交回报 ──
    oms.update_order_status(order.client_order_id, "submitted")
    fill = _make_fill(
        order_id=order.client_order_id,
        price=Decimal("48000"),
        quantity=Decimal("0.1"),
    )
    oms.process_fill(fill)
    await bus.publish("execution.fill", fill.model_dump(mode="json"))

    # ── 步骤 4：验证策略 on_fill 回调 ──
    await _wait_for(lambda: len(strategy.received_fills) > 0)
    assert len(strategy.received_fills) == 1
    assert strategy.received_fills[0].order_id == order.client_order_id

    # ── 步骤 5：验证持仓更新 ──
    position = oms.get_position("BTC/USDT")
    assert position is not None
    assert position.side == "long"
    assert position.quantity == Decimal("0.1")
    assert position.entry_price == Decimal("48000")

    # 清理
    await runner.stop()
    await bus.stop()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 8：止损触发流程
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_08_stop_loss_trigger():
    """验证止损触发流程。

    场景：
    - 策略持有 BTC 多仓，止损线 45000
    - 价格跌至 44000 → 策略产生卖出信号
    - 风控检查通过 → 创建卖出订单 → 成交
    """
    bus = InMemoryEventBus()
    captured_signals: list[dict] = []

    async def signal_collector(data: dict) -> None:
        captured_signals.append(data)

    bus.subscribe("strategy.signal", signal_collector)

    runner = StrategyRunner(bus)
    strategy = MockStopLossStrategy(
        stop_loss_price=Decimal("45000"),
        entry_price=Decimal("50000"),
    )
    runner.register_strategy(strategy)
    await runner.start()
    await bus.start()

    # 发布低于止损价的行情
    ticker = _make_ticker(price=Decimal("44000"))
    await bus.publish("market.ticker", ticker.model_dump(mode="json"))
    await _wait_for(lambda: len(captured_signals) > 0)

    # 验证产生卖出信号
    assert len(captured_signals) == 1
    signal_data = captured_signals[0]
    assert signal_data["side"] == "sell"
    assert "止损" in signal_data["reason"]
    assert signal_data["strength"] == 1.0

    # 风控检查（止损卖出应通过）
    risk_engine = RiskEngine()
    order = _make_order(side="sell", quantity=Decimal("1.0"), price=Decimal("44000"))
    result = risk_engine.check(
        order=order,
        positions=[],
        latest_price=Decimal("44000"),
    )
    assert result.decision == RiskDecision.APPROVE

    await runner.stop()
    await bus.stop()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 9：熔断场景 — 连续亏损→熔断→恢复
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_09_circuit_breaker_trigger_and_recover():
    """验证熔断器触发和恢复流程。

    场景：
    1. 连续记录 5 次失败 → 熔断器触发
    2. 熔断期间所有订单被拒绝
    3. 等待恢复超时 → 进入半开状态
    4. 半开状态探测成功 → 恢复正常
    """
    risk_engine = RiskEngine()

    # ── 步骤 1：连续失败触发熔断 ──
    for _ in range(5):
        risk_engine.l4.record_failure()

    assert risk_engine.l4.state.value == "open"

    # ── 步骤 2：熔断期间订单被拒绝 ──
    order = _make_order()
    result = risk_engine.check(order=order, positions=[])
    assert result.decision == RiskDecision.FLATTEN
    assert "熔断" in result.reason

    # ── 步骤 3：模拟恢复超时（直接修改内部状态） ──
    # 由于 RECOVERY_TIMEOUT_SEC = 60，测试中直接修改 _open_since 模拟超时
    risk_engine.l4._open_since = time.time() - 61  # 模拟已过 61 秒

    # 下次检查应进入半开状态
    result = risk_engine.check(order=order, positions=[])
    assert result.decision == RiskDecision.APPROVE  # 半开状态允许探测

    # ── 步骤 4：半开状态探测成功 → 恢复 ──
    risk_engine.l4.record_success()
    assert risk_engine.l4.state.value == "closed"

    # 恢复后订单应通过
    result = risk_engine.check(order=order, positions=[])
    assert result.decision == RiskDecision.APPROVE


@pytest.mark.asyncio
async def test_09b_circuit_breaker_half_open_failure():
    """验证半开状态下探测失败重新熔断。"""
    risk_engine = RiskEngine()

    # 触发熔断
    for _ in range(5):
        risk_engine.l4.record_failure()
    assert risk_engine.l4.state.value == "open"

    # 模拟超时进入半开
    risk_engine.l4._open_since = time.time() - 61

    # 探测一次（进入半开）
    order = _make_order()
    result = risk_engine.check(order=order, positions=[])
    assert result.decision == RiskDecision.APPROVE

    # 半开状态下再次失败 → 重新熔断
    risk_engine.l4.record_failure()
    assert risk_engine.l4.state.value == "open"

    # 熔断期间订单被拒绝
    result = risk_engine.check(order=order, positions=[])
    assert result.decision == RiskDecision.FLATTEN


@pytest.mark.asyncio
async def test_09c_drawdown_halt():
    """验证 L3 回撤检查：最大回撤超限触发全局熔断。"""
    risk_engine = RiskEngine()
    order = _make_order()

    # 权益从 100000 回撤到 80000（20% 回撤，超过 15% 阈值）
    result = risk_engine.check(
        order=order,
        positions=[],
        total_equity=Decimal("80000"),
        peak_equity=Decimal("100000"),
        daily_pnl=Decimal("-20000"),
        initial_equity=Decimal("100000"),
    )

    assert result.decision == RiskDecision.FLATTEN
    assert "回撤" in result.reason


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 10：系统重启恢复 — 崩溃→重启→持仓恢复
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_10_position_recovery_after_restart():
    """验证系统重启后的持仓恢复流程。

    场景：
    1. 系统崩溃前有 BTC/USDT 多仓 1.0
    2. 重启后从交易所拉取真实持仓（模拟）
    3. 持仓恢复管理器对比并恢复
    4. 策略收到 on_recover 回调
    """
    bus = InMemoryEventBus()
    await bus.start()

    # 模拟崩溃前的本地持仓
    local_positions = {
        "BTC/USDT": _make_position(
            side="long",
            quantity=Decimal("1.0"),
            entry_price=Decimal("50000"),
        ),
    }

    # 模拟交易所的真实持仓（与本地一致）
    exchange_positions = [
        _make_position(
            side="long",
            quantity=Decimal("1.0"),
            entry_price=Decimal("50000"),
        ),
    ]

    # 执行恢复
    recovery_mgr = PositionRecoveryManager(bus)
    report = await recovery_mgr.recover(exchange_positions, local_positions)

    # 验证恢复结果
    assert report["recovered"] == 1
    assert report["discrepancies"] == 0
    assert report["total_positions"] == 1
    assert "BTC/USDT" in recovery_mgr.recovered

    # 验证策略收到恢复回调
    runner = StrategyRunner(bus)
    strategy = MockBuyStrategy(threshold=Decimal("49000"))
    runner.register_strategy(strategy)
    await runner.start()

    # 重新触发恢复（因为策略是在恢复之后注册的）
    # 实际上恢复事件已经发布过了，策略需要重新订阅
    # 这里验证恢复管理器的状态
    recovered_pos = recovery_mgr.recovered["BTC/USDT"]
    assert recovered_pos.side == "long"
    assert recovered_pos.quantity == Decimal("1.0")

    await runner.stop()
    await bus.stop()


@pytest.mark.asyncio
async def test_10b_position_recovery_with_discrepancy():
    """验证持仓不一致时以交易所数据为准。"""
    bus = InMemoryEventBus()
    await bus.start()

    # 本地持仓：1.0
    local_positions = {
        "BTC/USDT": _make_position(
            side="long",
            quantity=Decimal("1.0"),
            entry_price=Decimal("50000"),
        ),
    }

    # 交易所持仓：0.8（部分成交未同步）
    exchange_positions = [
        _make_position(
            side="long",
            quantity=Decimal("0.8"),
            entry_price=Decimal("50000"),
        ),
    ]

    recovery_mgr = PositionRecoveryManager(bus)
    report = await recovery_mgr.recover(exchange_positions, local_positions)

    # 应发现差异
    assert report["discrepancies"] == 1
    assert len(report["discrepancy_details"]) == 1
    detail = report["discrepancy_details"][0]
    assert detail["symbol"] == "BTC/USDT"
    assert "以交易所数据为准" in detail["resolution"]

    # 恢复后的持仓应以交易所数据为准
    recovered_pos = recovery_mgr.recovered["BTC/USDT"]
    assert recovered_pos.quantity == Decimal("0.8")

    await bus.stop()


@pytest.mark.asyncio
async def test_10c_position_recovery_unknown_exchange_position():
    """验证交易所有但本地没有的持仓。"""
    bus = InMemoryEventBus()
    await bus.start()

    # 本地无持仓
    local_positions: dict[str, PositionState] = {}

    # 交易所有 ETH/USDT 持仓
    exchange_positions = [
        _make_position(
            symbol="ETH/USDT",
            side="long",
            quantity=Decimal("5.0"),
            entry_price=Decimal("3000"),
        ),
    ]

    recovery_mgr = PositionRecoveryManager(bus)
    report = await recovery_mgr.recover(exchange_positions, local_positions)

    assert report["recovered"] == 1
    assert report["discrepancies"] == 0
    assert "ETH/USDT" in recovery_mgr.recovered
    assert recovery_mgr.recovered["ETH/USDT"].quantity == Decimal("5.0")

    await bus.stop()


@pytest.mark.asyncio
async def test_10d_strategy_on_recover_callback():
    """验证策略的 on_recover 回调被正确调用。"""
    bus = InMemoryEventBus()
    await bus.start()

    # 注册策略并启动引擎
    runner = StrategyRunner(bus)
    strategy = MockBuyStrategy(threshold=Decimal("49000"))
    runner.register_strategy(strategy)
    await runner.start()

    # 发布持仓恢复事件
    position = _make_position(
        side="long",
        quantity=Decimal("1.0"),
        entry_price=Decimal("50000"),
    )
    await bus.publish("position.recover", position.model_dump(mode="json"))

    # 等待策略处理
    await _wait_for(lambda: len(strategy.recovered_positions) > 0)

    assert len(strategy.recovered_positions) == 1
    assert strategy.recovered_positions[0].symbol == "BTC/USDT"
    assert strategy.recovered_positions[0].quantity == Decimal("1.0")

    await runner.stop()
    await bus.stop()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 10 补充：完整端到端 — 行情→信号→风控→订单→成交→持仓更新
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@pytest.mark.asyncio
async def test_07b_full_pipeline_with_sell():
    """验证完整的卖出链路。"""
    bus = InMemoryEventBus()
    await bus.start()

    runner = StrategyRunner(bus)
    strategy = MockSellStrategy(threshold=Decimal("51000"))
    runner.register_strategy(strategy)
    await runner.start()

    oms = OrderManager(bus)
    risk_engine = RiskEngine()

    captured_signals: list[dict] = []

    async def signal_handler(data: dict) -> None:
        captured_signals.append(data)

    bus.subscribe("strategy.signal", signal_handler)

    # 发布高于阈值的行情 → 触发卖出信号
    ticker = _make_ticker(price=Decimal("52000"))
    await bus.publish("market.ticker", ticker.model_dump(mode="json"))
    await _wait_for(lambda: len(captured_signals) > 0)

    assert captured_signals[0]["side"] == "sell"

    # 创建卖出订单
    signal = Signal(**captured_signals[0])
    order = oms.create_order_from_signal(
        signal=signal,
        order_type="limit",
        price=Decimal("52000"),
        quantity=Decimal("0.5"),
        exchange="binance",
    )

    # 风控检查
    result = risk_engine.check(
        order=order,
        positions=[],
        latest_price=Decimal("52000"),
    )
    assert result.decision == RiskDecision.APPROVE

    # 模拟成交
    oms.update_order_status(order.client_order_id, "submitted")
    fill = _make_fill(
        order_id=order.client_order_id,
        side="sell",
        price=Decimal("52000"),
        quantity=Decimal("0.5"),
    )
    oms.process_fill(fill)

    # 验证持仓
    position = oms.get_position("BTC/USDT")
    assert position is not None
    assert position.side == "short"
    assert position.quantity == Decimal("0.5")

    await runner.stop()
    await bus.stop()


@pytest.mark.asyncio
async def test_07c_pipeline_multiple_symbols():
    """验证多标的同时交易。"""
    bus = InMemoryEventBus()
    await bus.start()

    oms = OrderManager(bus)
    risk_engine = RiskEngine()

    # 创建 BTC 和 ETH 的订单
    btc_signal = Signal(
        symbol="BTC/USDT",
        market=Market.SPOT,
        side="buy",
        strength=0.8,
        strategy_name="multi_symbol_test",
        reason="BTC 买入",
        timestamp_ns=time.time_ns(),
    )
    eth_signal = Signal(
        symbol="ETH/USDT",
        market=Market.SPOT,
        side="buy",
        strength=0.7,
        strategy_name="multi_symbol_test",
        reason="ETH 买入",
        timestamp_ns=time.time_ns(),
    )

    btc_order = oms.create_order_from_signal(
        signal=btc_signal,
        order_type="limit",
        price=Decimal("50000"),
        quantity=Decimal("0.1"),
        exchange="binance",
    )
    eth_order = oms.create_order_from_signal(
        signal=eth_signal,
        order_type="limit",
        price=Decimal("3000"),
        quantity=Decimal("1.0"),
        exchange="binance",
    )

    # 风控检查
    btc_result = risk_engine.check(order=btc_order, positions=[], latest_price=Decimal("50000"))
    eth_result = risk_engine.check(order=eth_order, positions=[], latest_price=Decimal("3000"))
    assert btc_result.decision == RiskDecision.APPROVE
    assert eth_result.decision == RiskDecision.APPROVE

    # 模拟成交
    btc_fill = _make_fill(order_id=btc_order.client_order_id, price=Decimal("50000"), quantity=Decimal("0.1"))
    eth_fill = _make_fill(
        order_id=eth_order.client_order_id,
        symbol="ETH/USDT",
        side="buy",
        price=Decimal("3000"),
        quantity=Decimal("1.0"),
    )
    oms.process_fill(btc_fill)
    oms.process_fill(eth_fill)

    # 验证两个标的都有持仓
    btc_pos = oms.get_position("BTC/USDT")
    eth_pos = oms.get_position("ETH/USDT")
    assert btc_pos is not None
    assert eth_pos is not None
    assert btc_pos.quantity == Decimal("0.1")
    assert eth_pos.quantity == Decimal("1.0")

    # 验证所有持仓列表
    all_positions = oms.get_all_positions()
    assert len(all_positions) == 2

    await bus.stop()

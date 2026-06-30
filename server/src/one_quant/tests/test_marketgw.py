"""
ONE量化 - 行情网关模块测试

覆盖:
- normalizer: 币安/OKX 归一化函数
- reconnect: 断线重连管理器
- base: MarketGateway 基类
- EventBus 集成: 归一化数据通过 EventBus 分发
"""

from __future__ import annotations

import asyncio
import time
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from one_quant.core.types import (
    Kline,
    Market,
    OrderBook,
    Ticker,
    Trade,
)
from one_quant.marketgw.normalizer import (
    binance_symbol_to_internal,
    normalize_binance_kline,
    normalize_binance_orderbook,
    normalize_binance_ticker,
    normalize_binance_trade,
    normalize_okx_kline,
    normalize_okx_orderbook,
    normalize_okx_ticker,
    normalize_okx_trade,
    okx_symbol_to_internal,
)
from one_quant.marketgw.reconnect import ReconnectManager

# ══════════════════════════════════════════════════════════════════════
# normalizer 测试
# ══════════════════════════════════════════════════════════════════════


class TestSymbolConversion:
    """symbol 转换测试"""

    def test_binance_to_internal_spot(self) -> None:
        assert binance_symbol_to_internal("BTCUSDT") == "BTC/USDT"

    def test_binance_to_internal_busd(self) -> None:
        assert binance_symbol_to_internal("ETHBUSD") == "ETH/BUSD"

    def test_binance_to_internal_btc_pair(self) -> None:
        assert binance_symbol_to_internal("ETHBTC") == "ETH/BTC"

    def test_binance_to_internal_unknown(self) -> None:
        # 无法识别时原样返回
        assert binance_symbol_to_internal("UNKNOWN") == "UNKNOWN"

    def test_okx_to_internal(self) -> None:
        assert okx_symbol_to_internal("BTC-USDT") == "BTC/USDT"

    def test_okx_to_internal_eth(self) -> None:
        assert okx_symbol_to_internal("ETH-USDT") == "ETH/USDT"

    def test_okx_to_internal_unknown(self) -> None:
        assert okx_symbol_to_internal("UNKNOWN") == "UNKNOWN"


class TestNormalizeBinanceTicker:
    """币安 Ticker 归一化测试"""

    def _make_raw(self) -> dict:
        return {
            "e": "24hrTicker",
            "s": "BTCUSDT",
            "c": "50000.00",
            "b": "49999.00",
            "a": "50001.00",
            "v": "1234.56",
            "E": 1700000000000,
        }

    def test_basic_fields(self) -> None:
        raw = self._make_raw()
        t = normalize_binance_ticker(raw)

        assert isinstance(t, Ticker)
        assert t.symbol == "BTC/USDT"
        assert t.exchange == "binance"
        assert t.market == Market.SPOT
        assert t.last_price == Decimal("50000.00")
        assert t.bid == Decimal("49999.00")
        assert t.ask == Decimal("50001.00")
        assert t.volume_24h == Decimal("1234.56")

    def test_timestamp_conversion(self) -> None:
        raw = self._make_raw()
        t = normalize_binance_ticker(raw)
        # 毫秒 → 纳秒
        assert t.timestamp_ns == 1700000000000 * 1_000_000

    def test_futures_market(self) -> None:
        raw = self._make_raw()
        t = normalize_binance_ticker(raw, market=Market.FUTURES)
        assert t.market == Market.FUTURES

    def test_decimal_precision(self) -> None:
        """验证 Decimal 精度，不出现浮点误差"""
        raw = self._make_raw()
        raw["c"] = "0.12345678"
        t = normalize_binance_ticker(raw)
        assert t.last_price == Decimal("0.12345678")


class TestNormalizeBinanceKline:
    """币安 Kline 归一化测试"""

    def _make_raw(self) -> dict:
        return {
            "e": "kline",
            "s": "BTCUSDT",
            "k": {
                "t": 1700000000000,
                "o": "50000",
                "h": "50100",
                "l": "49900",
                "c": "50050",
                "v": "100",
                "i": "1m",
            },
        }

    def test_basic_fields(self) -> None:
        raw = self._make_raw()
        k = normalize_binance_kline(raw)

        assert isinstance(k, Kline)
        assert k.symbol == "BTC/USDT"
        assert k.exchange == "binance"
        assert k.interval == "1m"
        assert k.open == Decimal("50000")
        assert k.high == Decimal("50100")
        assert k.low == Decimal("49900")
        assert k.close == Decimal("50050")
        assert k.volume == Decimal("100")

    def test_timestamp_is_kline_start(self) -> None:
        """时间戳应为 K 线起始时间"""
        raw = self._make_raw()
        k = normalize_binance_kline(raw)
        assert k.timestamp_ns == 1700000000000 * 1_000_000


class TestNormalizeBinanceOrderbook:
    """币安 OrderBook 归一化测试"""

    def test_depth_update_format(self) -> None:
        """depthUpdate 格式 (b/a 字段)"""
        raw = {
            "e": "depthUpdate",
            "s": "BTCUSDT",
            "b": [["49999", "1.5"], ["49998", "2.0"]],
            "a": [["50001", "2.0"], ["50002", "1.0"]],
            "E": 1700000000000,
        }
        ob = normalize_binance_orderbook(raw, symbol="BTC/USDT")

        assert isinstance(ob, OrderBook)
        assert ob.symbol == "BTC/USDT"
        assert len(ob.bids) == 2
        assert len(ob.asks) == 2
        assert ob.bids[0].price == Decimal("49999")
        assert ob.bids[0].quantity == Decimal("1.5")
        assert ob.asks[0].price == Decimal("50001")

    def test_partial_depth_format(self) -> None:
        """partial depth 格式 (bids/asks 字段)"""
        raw = {
            "lastUpdateId": 12345,
            "bids": [["49999", "1.5"]],
            "asks": [["50001", "2.0"]],
        }
        ob = normalize_binance_orderbook(raw, symbol="BTC/USDT")
        assert len(ob.bids) == 1
        assert len(ob.asks) == 1

    def test_empty_orderbook(self) -> None:
        """空盘口"""
        raw = {"b": [], "a": []}
        ob = normalize_binance_orderbook(raw, symbol="BTC/USDT")
        assert len(ob.bids) == 0
        assert len(ob.asks) == 0


class TestNormalizeBinanceTrade:
    """币安 Trade 归一化测试"""

    def _make_raw(self, m: bool = True) -> dict:
        return {
            "e": "trade",
            "s": "BTCUSDT",
            "p": "50000",
            "q": "0.5",
            "T": 1700000000000,
            "t": 123456789,
            "m": m,
        }

    def test_buy_side(self) -> None:
        """m=False → 买方主动 (taker) → side=buy"""
        raw = self._make_raw(m=False)
        t = normalize_binance_trade(raw)
        assert t.side == "buy"

    def test_sell_side(self) -> None:
        """m=True → 卖方主动 (taker) → side=sell"""
        raw = self._make_raw(m=True)
        t = normalize_binance_trade(raw)
        assert t.side == "sell"

    def test_trade_id(self) -> None:
        raw = self._make_raw()
        t = normalize_binance_trade(raw)
        assert t.trade_id == "123456789"


class TestNormalizeOKXTicker:
    """OKX Ticker 归一化测试"""

    def _make_raw(self) -> dict:
        return {
            "instId": "BTC-USDT",
            "last": "50000.00",
            "bidPx": "49999.00",
            "askPx": "50001.00",
            "vol24h": "1234.56",
            "ts": "1700000000000",
        }

    def test_basic_fields(self) -> None:
        raw = self._make_raw()
        t = normalize_okx_ticker(raw)

        assert isinstance(t, Ticker)
        assert t.symbol == "BTC/USDT"
        assert t.exchange == "okx"
        assert t.market == Market.SPOT
        assert t.last_price == Decimal("50000.00")

    def test_perpetual_market(self) -> None:
        raw = self._make_raw()
        raw["instId"] = "BTC-USDT-SWAP"
        t = normalize_okx_ticker(raw)
        assert t.market == Market.FUTURES


class TestNormalizeOKXKline:
    """OKX Kline 归一化测试"""

    def test_basic_fields(self) -> None:
        # [ts, open, high, low, close, vol, volCcy, volCcyQuote, confirm]
        raw = [
            "1700000000000",
            "50000",
            "50100",
            "49900",
            "50050",
            "100",
            "5000000",
            "5000000",
            "1",
        ]
        k = normalize_okx_kline(raw, inst_id="BTC-USDT", interval="1m")

        assert isinstance(k, Kline)
        assert k.symbol == "BTC/USDT"
        assert k.exchange == "okx"
        assert k.open == Decimal("50000")
        assert k.high == Decimal("50100")
        assert k.close == Decimal("50050")
        assert k.interval == "1m"


class TestNormalizeOKXOrderbook:
    """OKX OrderBook 归一化测试"""

    def test_basic_fields(self) -> None:
        raw = {
            "ts": "1700000000000",
            "bids": [["49999", "1.5", "0", "1"]],
            "asks": [["50001", "2.0", "0", "1"]],
        }
        ob = normalize_okx_orderbook(raw, symbol="BTC/USDT")

        assert isinstance(ob, OrderBook)
        assert ob.symbol == "BTC/USDT"
        assert len(ob.bids) == 1
        assert ob.bids[0].price == Decimal("49999")

    def test_empty(self) -> None:
        raw = {"ts": "1700000000000", "bids": [], "asks": []}
        ob = normalize_okx_orderbook(raw, symbol="BTC/USDT")
        assert len(ob.bids) == 0


class TestNormalizeOKXTrade:
    """OKX Trade 归一化测试"""

    def test_buy(self) -> None:
        raw = {
            "instId": "BTC-USDT",
            "tradeId": "12345",
            "px": "50000",
            "sz": "0.5",
            "side": "buy",
            "ts": "1700000000000",
        }
        t = normalize_okx_trade(raw)
        assert t.side == "buy"
        assert t.symbol == "BTC/USDT"
        assert t.price == Decimal("50000")

    def test_sell(self) -> None:
        raw = {
            "instId": "BTC-USDT",
            "tradeId": "12345",
            "px": "50000",
            "sz": "0.5",
            "side": "sell",
            "ts": "1700000000000",
        }
        t = normalize_okx_trade(raw)
        assert t.side == "sell"


# ══════════════════════════════════════════════════════════════════════
# ReconnectManager 测试
# ══════════════════════════════════════════════════════════════════════


class TestReconnectManager:
    """断线重连管理器测试"""

    def test_initial_state(self) -> None:
        rm = ReconnectManager()
        assert rm.retry_count == 0
        assert rm.current_delay == 1.0

    def test_custom_params(self) -> None:
        rm = ReconnectManager(initial_delay=2.0, max_delay=30.0, multiplier=3.0)
        assert rm.initial_delay == 2.0
        assert rm.max_delay == 30.0
        assert rm.multiplier == 3.0

    def test_reset(self) -> None:
        rm = ReconnectManager()
        rm._retry_count = 5
        rm._current_delay = 32.0
        rm.reset()
        assert rm.retry_count == 0
        assert rm.current_delay == 1.0

    @pytest.mark.asyncio
    async def test_execute_once_success(self) -> None:
        """连接成功时立即返回"""
        rm = ReconnectManager()
        connect_fn = AsyncMock()
        connected_cb = AsyncMock()

        await rm.execute_once(connect_fn, on_connected=connected_cb)

        connect_fn.assert_awaited_once()
        connected_cb.assert_awaited_once()
        assert rm.retry_count == 0  # 成功后重置

    @pytest.mark.asyncio
    async def test_execute_once_retry_then_success(self) -> None:
        """第一次失败，第二次成功"""
        rm = ReconnectManager(initial_delay=0.01)  # 极小延迟加速测试
        call_count = 0

        async def connect_fn():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("模拟断线")

        await rm.execute_once(connect_fn)
        assert call_count == 2
        assert rm.retry_count == 0  # 成功后重置

    @pytest.mark.asyncio
    async def test_execute_once_should_continue_stops(self) -> None:
        """should_continue 返回 False 时停止重试"""
        rm = ReconnectManager(initial_delay=0.01)
        call_count = 0

        async def connect_fn():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("模拟断线")

        # 只允许重试 2 次
        def should_continue():
            return call_count < 2

        await rm.execute_once(connect_fn, should_continue=should_continue)
        assert call_count == 2  # 初始 + 1 次重试

    @pytest.mark.asyncio
    async def test_run_forever_stops_on_should_continue(self) -> None:
        """run_forever 在 should_continue 返回 False 时正确退出"""
        rm = ReconnectManager(initial_delay=0.01)
        call_count = 0

        async def connect_fn():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("模拟断线")

        def should_continue():
            return call_count < 3

        await rm.run_forever(connect_fn, should_continue=should_continue)
        assert call_count == 3


# ══════════════════════════════════════════════════════════════════════
# EventBus 集成测试
# ══════════════════════════════════════════════════════════════════════


class TestEventBusIntegration:
    """验证归一化数据能正确通过 EventBus 分发"""

    @pytest.mark.asyncio
    async def test_ticker_publish(self) -> None:
        """验证 Ticker 数据能通过 EventBus 发布"""
        from one_quant.infra.event_bus import InMemoryEventBus

        bus = InMemoryEventBus()
        await bus.start()

        received: list[dict] = []

        async def handler(data: dict) -> None:
            received.append(data)

        bus.subscribe("market.ticker", handler)

        # 构造归一化后的 Ticker
        ticker = Ticker(
            symbol="BTC/USDT",
            market=Market.SPOT,
            exchange="binance",
            last_price=Decimal("50000"),
            bid=Decimal("49999"),
            ask=Decimal("50001"),
            volume_24h=Decimal("1000"),
            timestamp_ns=time.time_ns(),
        )
        await bus.publish("market.ticker", ticker.model_dump(mode="json"))

        # 等待消费者处理
        await asyncio.sleep(0.1)

        assert len(received) == 1
        assert received[0]["symbol"] == "BTC/USDT"
        assert received[0]["last_price"] == "50000"

        await bus.stop()

    @pytest.mark.asyncio
    async def test_trade_publish(self) -> None:
        """验证 Trade 数据能通过 EventBus 发布"""
        from one_quant.infra.event_bus import InMemoryEventBus

        bus = InMemoryEventBus()
        await bus.start()

        received: list[dict] = []

        async def handler(data: dict) -> None:
            received.append(data)

        bus.subscribe("market.trade", handler)

        trade = Trade(
            symbol="BTC/USDT",
            exchange="binance",
            price=Decimal("50000"),
            quantity=Decimal("0.5"),
            side="buy",
            trade_id="12345",
            timestamp_ns=time.time_ns(),
        )
        await bus.publish("market.trade", trade.model_dump(mode="json"))

        await asyncio.sleep(0.1)

        assert len(received) == 1
        assert received[0]["side"] == "buy"

        await bus.stop()


# ══════════════════════════════════════════════════════════════════════
# Gateway 基类测试
# ══════════════════════════════════════════════════════════════════════


class TestMarketGatewayBase:
    """MarketGateway 基类行为测试"""

    @pytest.mark.asyncio
    async def test_start_stop(self) -> None:
        """验证 start/stop 状态切换"""
        from one_quant.infra.event_bus import InMemoryEventBus
        from one_quant.marketgw.base import MarketGateway

        bus = InMemoryEventBus()

        class DummyGateway(MarketGateway):
            """用于测试的空实现"""

            async def connect(self) -> None:
                pass

            async def disconnect(self) -> None:
                pass

            async def subscribe_ticker(self, symbols: list[str]) -> None:
                pass

            async def subscribe_kline(self, symbols: list[str], interval: str) -> None:
                pass

            async def subscribe_orderbook(self, symbols: list[str], depth: int = 20) -> None:
                pass

            async def subscribe_trades(self, symbols: list[str]) -> None:
                pass

        gw = DummyGateway(event_bus=bus)
        assert not gw.is_running

        await gw.start()
        assert gw.is_running

        await gw.stop()
        assert not gw.is_running

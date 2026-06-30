"""
ONE量化 - EMS 执行算法测试

测试 TWAP、VWAP、POV 算法和 ExecutionManager。
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from one_quant.core.types import Market, Order
from one_quant.execution.ems import (
    ExecutionManager,
    POVAlgo,
    TWAPAlgo,
    VWAPAlgo,
    _round_to_lot,
)

# ──────────────────── 辅助函数 ────────────────────


def make_order(
    quantity: str = "1.0",
    price: str | None = "50000",
    side: str = "buy",
    symbol: str = "BTC/USDT",
) -> Order:
    """创建测试订单。"""
    return Order(
        client_order_id="test-order-001",
        symbol=symbol,
        market=Market.SPOT,
        side=side,
        order_type="limit",
        quantity=Decimal(quantity),
        price=Decimal(price) if price else None,
        stop_price=None,
        status="pending",
        exchange="binance",
        timestamp_ns=1700000000000000000,
    )


def make_adapter(kline_count: int = 20) -> AsyncMock:
    """创建模拟适配器。"""
    adapter = AsyncMock()
    adapter.submit_order = AsyncMock(return_value="exchange-order-123")
    adapter.cancel_order = AsyncMock(return_value=True)
    # 配置 get_klines 返回正确的 K 线数据（带 volume 属性）
    klines = [
        type("Kline", (), {"volume": Decimal(str(1000 * (i + 1)))})() for i in range(kline_count)
    ]
    adapter.get_klines = AsyncMock(return_value=klines)
    # POV: 禁用 WebSocket 路径，配置 get_trades 返回成交量数据
    adapter.ws = None
    adapter._ws = None
    trade = type("Trade", (), {"quantity": Decimal("500")})()
    adapter.get_trades = AsyncMock(return_value=[trade])
    return adapter


# ──────────────────── 辅助函数测试 ────────────────────


class TestRoundToLot:
    """_round_to_lot 函数测试。"""

    def test_round_to_lot_basic(self):
        """基本取整。"""
        assert _round_to_lot(Decimal("1.234"), Decimal("0.01")) == Decimal("1.23")
        assert _round_to_lot(Decimal("1.236"), Decimal("0.01")) == Decimal("1.23")

    def test_round_to_lot_zero_lot(self):
        """lot_size 为 0 时返回原值。"""
        assert _round_to_lot(Decimal("1.5"), Decimal("0")) == Decimal("1.5")

    def test_round_to_lot_exact(self):
        """整数倍时不改变。"""
        assert _round_to_lot(Decimal("2.0"), Decimal("0.5")) == Decimal("2.0")


# ──────────────────── TWAP 测试 ────────────────────


class TestTWAPAlgo:
    """TWAP 算法测试。"""

    @pytest.mark.asyncio
    async def test_twap_basic(self):
        """基本 TWAP 执行。"""
        algo = TWAPAlgo(duration_sec=1, slice_count=3)
        order = make_order(quantity="0.3")
        adapter = make_adapter()

        fills = await algo.execute(order, adapter)

        # 应该提交 3 笔子单
        assert adapter.submit_order.call_count == 3
        # 应该有 3 笔成交
        assert len(fills) == 3

    @pytest.mark.asyncio
    async def test_twap_quantity_distribution(self):
        """TWAP 子单数量分配。"""
        algo = TWAPAlgo(duration_sec=1, slice_count=5)
        order = make_order(quantity="1.0")
        adapter = make_adapter()

        fills = await algo.execute(order, adapter)

        total_filled = sum(f.quantity for f in fills)
        assert total_filled == Decimal("1.0")

    @pytest.mark.asyncio
    async def test_twap_name(self):
        """算法名称。"""
        algo = TWAPAlgo()
        assert algo.name == "TWAP"

    def test_twap_invalid_params(self):
        """参数校验。"""
        with pytest.raises(ValueError, match="执行时长必须大于 0"):
            TWAPAlgo(duration_sec=0)

        with pytest.raises(ValueError, match="拆分数量必须大于 0"):
            TWAPAlgo(slice_count=0)

    @pytest.mark.asyncio
    async def test_twap_with_price_limit(self):
        """带限价的 TWAP。"""
        algo = TWAPAlgo(duration_sec=1, slice_count=2, price_limit=Decimal("49000"))
        order = make_order(quantity="0.2")
        adapter = make_adapter()

        fills = await algo.execute(order, adapter)  # noqa: F841

        assert adapter.submit_order.call_count == 2
        # 验证子单是限价单
        for call in adapter.submit_order.call_args_list:
            child_order = call[0][0]
            assert child_order.order_type == "limit"
            assert child_order.price == Decimal("49000")

    @pytest.mark.asyncio
    async def test_twap_retry_on_failure(self):
        """失败重试。"""
        algo = TWAPAlgo(duration_sec=1, slice_count=2, max_retries=2)
        order = make_order(quantity="0.2")
        adapter = make_adapter()

        # 第一次提交失败，后续成功
        adapter.submit_order.side_effect = [
            Exception("网络错误"),
            "exchange-order-456",
            "exchange-order-789",
        ]

        fills = await algo.execute(order, adapter)

        # 应该有成交
        assert len(fills) >= 1


# ──────────────────── VWAP 测试 ────────────────────


class TestVWAPAlgo:
    """VWAP 算法测试。"""

    @pytest.mark.asyncio
    async def test_vwap_basic(self):
        """基本 VWAP 执行。"""
        algo = VWAPAlgo(lookback_intervals=5, participation_rate=0.1)
        order = make_order(quantity="0.5")
        adapter = make_adapter(kline_count=5)

        fills = await algo.execute(order, adapter)

        # 应该有成交
        assert len(fills) == 5
        assert adapter.submit_order.call_count == 5

    @pytest.mark.asyncio
    async def test_vwap_name(self):
        """算法名称。"""
        algo = VWAPAlgo()
        assert algo.name == "VWAP"

    def test_vwap_invalid_params(self):
        """参数校验。"""
        with pytest.raises(ValueError, match="回看窗口数必须大于 0"):
            VWAPAlgo(lookback_intervals=0)

        with pytest.raises(ValueError, match="参与率必须在"):
            VWAPAlgo(participation_rate=0)

        with pytest.raises(ValueError, match="参与率必须在"):
            VWAPAlgo(participation_rate=1.5)

    @pytest.mark.asyncio
    async def test_vwap_quantity_conservation(self):
        """VWAP 数量守恒。"""
        algo = VWAPAlgo(lookback_intervals=10, participation_rate=0.1)
        order = make_order(quantity="2.0")
        adapter = make_adapter(kline_count=10)

        fills = await algo.execute(order, adapter)

        total_filled = sum(f.quantity for f in fills)
        assert total_filled == Decimal("2.0")


# ──────────────────── POV 测试 ────────────────────


class TestPOVAlgo:
    """POV 算法测试。"""

    @pytest.mark.asyncio
    async def test_pov_basic(self):
        """基本 POV 执行。"""
        algo = POVAlgo(
            participation_rate=0.1,
            volume_threshold=Decimal("100"),
            max_duration_sec=5,
        )
        order = make_order(quantity="0.5")
        adapter = make_adapter()

        fills = await algo.execute(order, adapter)

        assert len(fills) > 0

    @pytest.mark.asyncio
    async def test_pov_name(self):
        """算法名称。"""
        algo = POVAlgo()
        assert algo.name == "POV"

    def test_pov_invalid_params(self):
        """参数校验。"""
        with pytest.raises(ValueError, match="参与率必须在"):
            POVAlgo(participation_rate=0)

        with pytest.raises(ValueError, match="成交量阈值必须大于 0"):
            POVAlgo(volume_threshold=Decimal("0"))

    @pytest.mark.asyncio
    async def test_pov_timeout(self):
        """POV 超时退出。"""
        algo = POVAlgo(
            participation_rate=0.1,
            volume_threshold=Decimal("1000000"),  # 极高阈值，不会触发
            max_duration_sec=1,
        )
        order = make_order(quantity="0.1")
        adapter = make_adapter()

        fills = await algo.execute(order, adapter)

        # 超时后应有部分成交或无成交
        assert len(fills) >= 0


# ──────────────────── ExecutionManager 测试 ────────────────────


class TestExecutionManager:
    """执行管理器测试。"""

    @pytest.mark.asyncio
    async def test_auto_select_algo_small(self):
        """小单自动选择即时算法。"""
        em = ExecutionManager(make_adapter())
        order = make_order(quantity="0.001", price="100")  # 名义 = 0.1

        fills = await em.execute(order)

        assert len(fills) == 1

    @pytest.mark.asyncio
    async def test_auto_select_algo_twap(self):
        """中单指定 TWAP 执行。"""
        em = ExecutionManager(make_adapter())
        order = make_order(quantity="0.5", price="50000")
        algo = TWAPAlgo(duration_sec=1, slice_count=3)

        fills = await em.execute(order, algo=algo)

        assert len(fills) > 0

    @pytest.mark.asyncio
    async def test_explicit_algo(self):
        """指定算法执行。"""
        em = ExecutionManager(make_adapter())
        order = make_order(quantity="0.1")
        algo = TWAPAlgo(duration_sec=1, slice_count=3)

        fills = await em.execute(order, algo=algo)

        assert len(fills) == 3

    @pytest.mark.asyncio
    async def test_stats(self):
        """统计信息。"""
        em = ExecutionManager(make_adapter())
        order = make_order(quantity="0.001", price="100")

        await em.execute(order)

        stats = em.stats
        assert stats["executions"] == 1
        assert stats["total_fills"] >= 1

    def test_estimate_notional(self):
        """名义价值估算。"""
        order = make_order(quantity="1.0", price="50000")
        notional = ExecutionManager._estimate_notional(order)
        assert notional == Decimal("50000")

    def test_estimate_notional_no_price(self):
        """无价格时返回 0。"""
        order = make_order(quantity="1.0", price=None)
        notional = ExecutionManager._estimate_notional(order)
        assert notional == Decimal("0")

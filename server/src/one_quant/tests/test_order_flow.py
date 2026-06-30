"""
ONE量化 - 订单流测试

覆盖：
  - Delta/CVD 计算
  - 失衡检测
  - 吸收检测
  - 扫单检测
  - OBI 计算
  - 反幌骗过滤
  - 流动性墙检测
"""

import time
from decimal import Decimal

from one_quant.core.types import (
    OrderBook,
    OrderBookLevel,
    Trade,
)
from one_quant.strategy.order_flow import (
    ICEBERG_REFILL_THRESHOLD,
    SWEEP_MIN_COUNT,
    OrderFlowAnalyzer,
)

# ──────────────────────────── 辅助工具 ────────────────────────────


def _make_trade(
    side: str = "buy",
    price: str = "100",
    quantity: str = "1.0",
    timestamp_ns: int | None = None,
) -> Trade:
    """构造逐笔成交记录。"""
    return Trade(
        symbol="BTCUSDT",
        exchange="binance",
        price=Decimal(price),
        quantity=Decimal(quantity),
        side=side,
        trade_id="T001",
        timestamp_ns=timestamp_ns or time.time_ns(),
    )


def _make_orderbook(
    bids: list[tuple[str, str]] | None = None,
    asks: list[tuple[str, str]] | None = None,
) -> OrderBook:
    """构造盘口快照。"""
    if bids is None:
        bids = [("99", "10"), ("98", "20"), ("97", "30")]
    if asks is None:
        asks = [("101", "10"), ("102", "20"), ("103", "30")]
    return OrderBook(
        symbol="BTCUSDT",
        exchange="binance",
        bids=[OrderBookLevel(price=Decimal(p), quantity=Decimal(q)) for p, q in bids],
        asks=[OrderBookLevel(price=Decimal(p), quantity=Decimal(q)) for p, q in asks],
        timestamp_ns=time.time_ns(),
    )


def _make_trades(n: int, side: str = "buy", base_price: float = 100.0) -> list[Trade]:
    """批量构造成交记录。"""
    trades = []
    base_ts = 1_000_000_000_000
    for i in range(n):
        trades.append(
            _make_trade(
                side=side,
                price=str(base_price + i * 0.1),
                quantity="1.0",
                timestamp_ns=base_ts + i * 1_000_000,
            )
        )
    return trades


# ──────────────────────────── Delta/CVD 测试 ────────────────────────────


class TestDeltaCVD:
    """Delta 和 CVD 计算测试"""

    def test_delta_all_buys(self):
        """全部买入时 Delta 等于总成交量。"""
        analyzer = OrderFlowAnalyzer()
        trades = [_make_trade(side="buy", quantity="2.0") for _ in range(5)]
        delta = analyzer.compute_delta(trades)
        assert delta == Decimal("10.0")

    def test_delta_all_sells(self):
        """全部卖出时 Delta 等于负的总成交量。"""
        analyzer = OrderFlowAnalyzer()
        trades = [_make_trade(side="sell", quantity="3.0") for _ in range(5)]
        delta = analyzer.compute_delta(trades)
        assert delta == Decimal("-15.0")

    def test_delta_mixed(self):
        """混合买卖时 Delta = 买量 - 卖量。"""
        analyzer = OrderFlowAnalyzer()
        buys = [_make_trade(side="buy", quantity="2.0") for _ in range(3)]
        sells = [_make_trade(side="sell", quantity="1.0") for _ in range(2)]
        delta = analyzer.compute_delta(buys + sells)
        assert delta == Decimal("4.0")  # 3*2 - 2*1 = 4

    def test_delta_empty_trades(self):
        """空成交列表 Delta 为零。"""
        analyzer = OrderFlowAnalyzer()
        assert analyzer.compute_delta([]) == Decimal("0")

    def test_cvd_cumulative(self):
        """CVD 序列是 Delta 的累计和。"""
        analyzer = OrderFlowAnalyzer()
        trades = [
            _make_trade(side="buy", quantity="3.0"),
            _make_trade(side="sell", quantity="1.0"),
            _make_trade(side="buy", quantity="2.0"),
        ]
        cvd = analyzer.compute_cvd(trades)
        assert len(cvd) == 3
        assert cvd[0] == Decimal("3.0")  # +3
        assert cvd[1] == Decimal("2.0")  # +3-1
        assert cvd[2] == Decimal("4.0")  # +3-1+2

    def test_cvd_window_limit(self):
        """CVD 结果不超过指定窗口大小。"""
        analyzer = OrderFlowAnalyzer()
        trades = [_make_trade(side="buy", quantity="1.0") for _ in range(200)]
        cvd = analyzer.compute_cvd(trades, window=50)
        assert len(cvd) == 50

    def test_cvd_empty_trades(self):
        """空成交列表 CVD 为空。"""
        analyzer = OrderFlowAnalyzer()
        cvd = analyzer.compute_cvd([])
        assert cvd == []


# ──────────────────────────── 失衡检测测试 ────────────────────────────


class TestImbalance:
    """失衡检测测试"""

    def test_buy_imbalance_detected(self):
        """买方挂单量远大于卖方时检测到买方失衡。"""
        analyzer = OrderFlowAnalyzer()
        ob = _make_orderbook(
            bids=[("100", "100")],
            asks=[("100", "10")],
        )
        imbalances = analyzer.detect_imbalance(ob, threshold=3.0)
        assert len(imbalances) > 0
        assert any(i["direction"] == "buy" for i in imbalances)

    def test_sell_imbalance_detected(self):
        """卖方挂单量远大于买方时检测到卖方失衡。"""
        analyzer = OrderFlowAnalyzer()
        ob = _make_orderbook(
            bids=[("100", "5")],
            asks=[("100", "50")],
        )
        imbalances = analyzer.detect_imbalance(ob, threshold=3.0)
        assert len(imbalances) > 0
        assert any(i["direction"] == "sell" for i in imbalances)

    def test_balanced_no_imbalance(self):
        """买卖挂单量均衡时不检测到失衡。"""
        analyzer = OrderFlowAnalyzer()
        ob = _make_orderbook(
            bids=[("100", "10")],
            asks=[("100", "10")],
        )
        imbalances = analyzer.detect_imbalance(ob, threshold=3.0)
        assert len(imbalances) == 0

    def test_empty_orderbook_no_imbalance(self):
        """空盘口不检测到失衡。"""
        analyzer = OrderFlowAnalyzer()
        ob = _make_orderbook(bids=[], asks=[])
        imbalances = analyzer.detect_imbalance(ob)
        assert len(imbalances) == 0

    def test_only_bids_no_ask_imbalance(self):
        """只有买盘没有卖盘时标记为买方强失衡。"""
        analyzer = OrderFlowAnalyzer()
        ob = _make_orderbook(
            bids=[("100", "50")],
            asks=[],
        )
        imbalances = analyzer.detect_imbalance(ob)
        assert len(imbalances) > 0
        assert imbalances[0]["direction"] == "buy"
        assert imbalances[0]["ratio"] == float("inf")

    def test_threshold_boundary(self):
        """失衡阈值边界测试。"""
        analyzer = OrderFlowAnalyzer()
        # 比率恰好 3.0
        ob = _make_orderbook(
            bids=[("100", "30")],
            asks=[("100", "10")],
        )
        imbalances = analyzer.detect_imbalance(ob, threshold=3.0)
        assert len(imbalances) > 0


# ──────────────────────────── 吸收检测测试 ────────────────────────────


class TestAbsorption:
    """吸收检测测试"""

    def test_absorption_detected(self):
        """大量同方向成交但价格不动时检测到吸收。"""
        analyzer = OrderFlowAnalyzer()
        # 20 笔买入成交，价格几乎不变
        trades = [_make_trade(side="buy", price="100.00", quantity="5.0") for _ in range(20)]
        # 添加微小价格变动
        trades_with_variation = []
        for i, t in enumerate(trades):
            p = Decimal("100.00") + Decimal(str(i % 3)) * Decimal("0.001")
            trades_with_variation.append(
                Trade(
                    symbol=t.symbol,
                    exchange=t.exchange,
                    price=p,
                    quantity=t.quantity,
                    side=t.side,
                    trade_id=t.trade_id,
                    timestamp_ns=t.timestamp_ns,
                )
            )

        ob = _make_orderbook(
            bids=[("100", "100"), ("99", "100")],
            asks=[("101", "100"), ("102", "100")],
        )
        assert analyzer.detect_absorption(trades_with_variation, ob) is True

    def test_no_absorption_price_moves(self):
        """价格大幅变动时不检测到吸收。"""
        analyzer = OrderFlowAnalyzer()
        trades = []
        for i in range(20):
            trades.append(_make_trade(side="buy", price=str(100 + i), quantity="1.0"))
        ob = _make_orderbook()
        assert analyzer.detect_absorption(trades, ob) is False

    def test_too_few_trades_no_absorption(self):
        """不足 20 笔成交不检测吸收。"""
        analyzer = OrderFlowAnalyzer()
        trades = [_make_trade(side="buy", quantity="1.0") for _ in range(10)]
        ob = _make_orderbook()
        assert analyzer.detect_absorption(trades, ob) is False

    def test_balanced_volume_no_absorption(self):
        """买卖成交量均衡时不检测到吸收。"""
        analyzer = OrderFlowAnalyzer()
        trades = []
        for i in range(20):
            side = "buy" if i % 2 == 0 else "sell"
            trades.append(_make_trade(side=side, price="100.00", quantity="1.0"))
        ob = _make_orderbook()
        assert analyzer.detect_absorption(trades, ob) is False


# ──────────────────────────── 扫单检测测试 ────────────────────────────


class TestSweep:
    """扫单检测测试"""

    def test_buy_sweep_detected(self):
        """连续买入多价位时检测到扫单。"""
        analyzer = OrderFlowAnalyzer()
        base_ts = 1_000_000_000_000
        trades = []
        for i in range(SWEEP_MIN_COUNT):
            trades.append(
                _make_trade(
                    side="buy",
                    price=str(100 + i),
                    quantity="10.0",
                    timestamp_ns=base_ts + i * 100_000_000,
                )
            )
        ob = _make_orderbook(
            bids=[(str(100 + i), "5") for i in range(10)],
            asks=[(str(100 + i), "5") for i in range(10)],
        )
        result = analyzer.detect_sweep(trades, ob)
        assert result is not None
        assert result["side"] == "buy"
        assert result["levels_swept"] >= 3

    def test_too_few_trades_no_sweep(self):
        """不足最少连续笔数不检测扫单。"""
        analyzer = OrderFlowAnalyzer()
        trades = [_make_trade(side="buy", quantity="1.0") for _ in range(SWEEP_MIN_COUNT - 1)]
        ob = _make_orderbook()
        assert analyzer.detect_sweep(trades, ob) is None

    def test_mixed_sides_no_sweep(self):
        """混合买卖方向不检测扫单。"""
        analyzer = OrderFlowAnalyzer()
        trades = []
        for i in range(10):
            side = "buy" if i % 2 == 0 else "sell"
            trades.append(_make_trade(side=side, price=str(100 + i), quantity="1.0"))
        ob = _make_orderbook()
        assert analyzer.detect_sweep(trades, ob) is None

    def test_single_price_no_sweep(self):
        """同一价位连续成交不检测扫单（未跨越多档）。"""
        analyzer = OrderFlowAnalyzer()
        base_ts = 1_000_000_000_000
        trades = []
        for i in range(SWEEP_MIN_COUNT):
            trades.append(
                _make_trade(
                    side="buy",
                    price="100",
                    quantity="10.0",
                    timestamp_ns=base_ts + i * 100_000_000,
                )
            )
        ob = _make_orderbook()
        result = analyzer.detect_sweep(trades, ob)
        assert result is None


# ──────────────────────────── OBI 测试 ────────────────────────────


class TestOBI:
    """OBI（盘口失衡）计算测试"""

    def test_obi_balanced(self):
        """买卖挂单量均衡时 OBI 接近 0。"""
        analyzer = OrderFlowAnalyzer()
        ob = _make_orderbook(
            bids=[("99", "10"), ("98", "10")],
            asks=[("101", "10"), ("102", "10")],
        )
        obi = analyzer.compute_obi(ob)
        assert abs(obi) < 0.01

    def test_obi_bullish(self):
        """买方挂单量大时 OBI > 0。"""
        analyzer = OrderFlowAnalyzer()
        ob = _make_orderbook(
            bids=[("99", "100"), ("98", "100")],
            asks=[("101", "10"), ("102", "10")],
        )
        obi = analyzer.compute_obi(ob)
        assert obi > 0

    def test_obi_bearish(self):
        """卖方挂单量大时 OBI < 0。"""
        analyzer = OrderFlowAnalyzer()
        ob = _make_orderbook(
            bids=[("99", "10"), ("98", "10")],
            asks=[("101", "100"), ("102", "100")],
        )
        obi = analyzer.compute_obi(ob)
        assert obi < 0

    def test_obi_range(self):
        """OBI 取值范围 [-1, 1]。"""
        analyzer = OrderFlowAnalyzer()
        # 极端买方
        ob_bull = _make_orderbook(
            bids=[("99", "1000")],
            asks=[("101", "1")],
        )
        obi_bull = analyzer.compute_obi(ob_bull)
        assert -1.0 <= obi_bull <= 1.0

        # 极端卖方
        ob_bear = _make_orderbook(
            bids=[("99", "1")],
            asks=[("101", "1000")],
        )
        obi_bear = analyzer.compute_obi(ob_bear)
        assert -1.0 <= obi_bear <= 1.0

    def test_obi_empty_orderbook(self):
        """空盘口 OBI 为 0。"""
        analyzer = OrderFlowAnalyzer()
        ob = _make_orderbook(bids=[], asks=[])
        obi = analyzer.compute_obi(ob)
        assert obi == 0.0


# ──────────────────────────── 流动性墙检测测试 ────────────────────────────


class TestLiquidityWall:
    """流动性墙检测测试"""

    def test_liquidity_wall_detected(self):
        """单档挂单量远超平均值时检测到流动性墙。"""
        analyzer = OrderFlowAnalyzer()
        # 平均值 = (200+5+5+5+5+5)/6 ≈ 37.5, 200/37.5 ≈ 5.33 > 5.0
        ob = _make_orderbook(
            bids=[("99", "200"), ("98", "5"), ("97", "5")],
            asks=[("101", "5"), ("102", "5"), ("103", "5")],
        )
        wall = analyzer.detect_liquidity_wall(ob)
        assert wall is not None
        assert wall["side"] == "bid"

    def test_no_wall_when_balanced(self):
        """挂单量均匀时无流动性墙。"""
        analyzer = OrderFlowAnalyzer()
        ob = _make_orderbook(
            bids=[("99", "10"), ("98", "10"), ("97", "10")],
            asks=[("101", "10"), ("102", "10"), ("103", "10")],
        )
        wall = analyzer.detect_liquidity_wall(ob)
        assert wall is None

    def test_empty_orderbook_no_wall(self):
        """空盘口无流动性墙。"""
        analyzer = OrderFlowAnalyzer()
        ob = _make_orderbook(bids=[], asks=[])
        wall = analyzer.detect_liquidity_wall(ob)
        assert wall is None


# ──────────────────────────── 冰山单检测测试 ────────────────────────────


class TestIceberg:
    """冰山单检测测试"""

    def test_iceberg_detected_repeated_price(self):
        """同一价位反复成交时检测到冰山单。"""
        analyzer = OrderFlowAnalyzer()
        # 在同一价位多次买入成交（价格与 ask 侧接近以触发冰山检测）
        trades = [_make_trade(side="buy", price="101.00", quantity="5.0") for _ in range(10)]
        ob = _make_orderbook(
            bids=[("100", "50"), ("99", "10")],
            asks=[("101", "50"), ("102", "10")],
        )
        result = analyzer.detect_iceberg(trades, ob)
        assert result is not None
        assert result["refill_count"] >= ICEBERG_REFILL_THRESHOLD

    def test_too_few_trades_no_iceberg(self):
        """不足 10 笔成交不检测冰山单。"""
        analyzer = OrderFlowAnalyzer()
        trades = [_make_trade(side="buy", quantity="1.0") for _ in range(5)]
        ob = _make_orderbook()
        assert analyzer.detect_iceberg(trades, ob) is None

    def test_varied_prices_no_iceberg(self):
        """分散价位成交不检测冰山单。"""
        analyzer = OrderFlowAnalyzer()
        trades = [_make_trade(side="buy", price=str(100 + i), quantity="1.0") for i in range(10)]
        ob = _make_orderbook()
        assert analyzer.detect_iceberg(trades, ob) is None

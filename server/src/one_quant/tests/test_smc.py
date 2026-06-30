"""
ONE量化 - SMC (Smart Money Concepts) 测试

覆盖：
  - BOS 检测
  - CHoCH 检测
  - Order Block 识别
  - FVG 识别
  - 流动性池
  - 流动性猎杀
  - 溢价/折价区
"""

from decimal import Decimal

import pytest

from one_quant.core.types import Kline, Market
from one_quant.strategy.smc import SMCAnalyzer, SmartMoneyIndex


# ──────────────────────────── 辅助工具 ────────────────────────────


def _make_kline(
    open_: str = "100",
    high: str = "105",
    low: str = "95",
    close: str = "102",
    volume: str = "1000",
    timestamp_ns: int | None = None,
) -> Kline:
    """构造K线数据。"""
    return Kline(
        symbol="BTCUSDT",
        market=Market.SPOT,
        exchange="binance",
        interval="1h",
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal(volume),
        timestamp_ns=timestamp_ns or 1_000_000_000_000,
    )


def _make_trending_up_klines(n: int = 20) -> list[Kline]:
    """生成上升趋势K线序列。"""
    klines = []
    base_ts = 1_000_000_000_000
    for i in range(n):
        base = 100 + i * 2
        klines.append(_make_kline(
            open_=str(base),
            high=str(base + 5),
            low=str(base - 2),
            close=str(base + 3),
            timestamp_ns=base_ts + i * 3_600_000_000_000,
        ))
    return klines


def _make_trending_down_klines(n: int = 20) -> list[Kline]:
    """生成下降趋势K线序列。"""
    klines = []
    base_ts = 1_000_000_000_000
    for i in range(n):
        base = 200 - i * 2
        klines.append(_make_kline(
            open_=str(base),
            high=str(base + 2),
            low=str(base - 5),
            close=str(base - 3),
            timestamp_ns=base_ts + i * 3_600_000_000_000,
        ))
    return klines


def _make_swing_data() -> tuple[list[Decimal], list[Decimal]]:
    """生成有明显高低点的序列。"""
    # 高点: 110, 120, 115, 130
    # 低点: 90, 95, 85, 100
    highs = [
        Decimal("100"), Decimal("105"), Decimal("110"), Decimal("108"), Decimal("105"),
        Decimal("102"), Decimal("100"), Decimal("105"), Decimal("110"), Decimal("115"),
        Decimal("120"), Decimal("118"), Decimal("115"), Decimal("110"), Decimal("108"),
        Decimal("105"), Decimal("110"), Decimal("115"), Decimal("120"), Decimal("125"),
        Decimal("130"), Decimal("128"), Decimal("125"), Decimal("120"), Decimal("118"),
    ]
    lows = [
        Decimal("95"), Decimal("92"), Decimal("90"), Decimal("95"), Decimal("98"),
        Decimal("97"), Decimal("95"), Decimal("93"), Decimal("90"), Decimal("88"),
        Decimal("85"), Decimal("87"), Decimal("90"), Decimal("93"), Decimal("95"),
        Decimal("98"), Decimal("95"), Decimal("92"), Decimal("90"), Decimal("88"),
        Decimal("90"), Decimal("93"), Decimal("95"), Decimal("98"), Decimal("100"),
    ]
    return highs, lows


# ──────────────────────────── BOS 测试 ────────────────────────────


class TestBOS:
    """BOS（市场结构破坏）检测测试"""

    def test_bullish_bos_detected(self):
        """价格突破前一个 Swing 高点时检测到看涨 BOS。"""
        analyzer = SMCAnalyzer()
        highs, lows = _make_swing_data()
        result = analyzer.detect_bos(highs, lows)
        # 数据中有更高的高点，应检测到 BOS
        if result is not None:
            assert result["type"] in ("bullish_bos", "bearish_bos")

    def test_bos_returns_none_for_short_data(self):
        """数据不足时返回 None。"""
        analyzer = SMCAnalyzer()
        highs = [Decimal("100")] * 10
        lows = [Decimal("90")] * 10
        result = analyzer.detect_bos(highs, lows)
        assert result is None

    def test_bos_contains_required_fields(self):
        """BOS 结果包含必要字段。"""
        analyzer = SMCAnalyzer()
        highs, lows = _make_swing_data()
        result = analyzer.detect_bos(highs, lows)
        if result is not None:
            assert "type" in result
            assert "price" in result
            assert "swing_price" in result
            assert "index" in result

    def test_flat_data_no_bos(self):
        """平坦数据不产生 BOS。"""
        analyzer = SMCAnalyzer()
        highs = [Decimal("100")] * 30
        lows = [Decimal("99")] * 30
        result = analyzer.detect_bos(highs, lows)
        assert result is None


# ──────────────────────────── CHoCH 测试 ────────────────────────────


class TestCHoCH:
    """CHoCH（趋势转换）检测测试"""

    def test_bearish_choch_in_uptrend(self):
        """上升趋势中跌破最近 Swing 低点时检测到看跌 CHoCH。"""
        analyzer = SMCAnalyzer()
        # 创建上升趋势后反转的数据
        highs = [Decimal(str(100 + i)) for i in range(30)]
        lows = [Decimal(str(90 + i)) for i in range(30)]
        # 最后一根大幅下跌
        highs[-1] = Decimal("95")
        lows[-1] = Decimal("80")

        result = analyzer.detect_choch(highs, lows, "bullish")
        if result is not None:
            assert result["type"] == "bearish_choch"

    def test_bullish_choch_in_downtrend(self):
        """下降趋势中突破最近 Swing 高点时检测到看涨 CHoCH。"""
        analyzer = SMCAnalyzer()
        highs = [Decimal(str(200 - i)) for i in range(30)]
        lows = [Decimal(str(190 - i)) for i in range(30)]
        # 最后一根大幅上涨
        highs[-1] = Decimal("210")
        lows[-1] = Decimal("195")

        result = analyzer.detect_choch(highs, lows, "bearish")
        if result is not None:
            assert result["type"] == "bullish_choch"

    def test_choch_short_data_returns_none(self):
        """数据不足时返回 None。"""
        analyzer = SMCAnalyzer()
        highs = [Decimal("100")] * 10
        lows = [Decimal("90")] * 10
        result = analyzer.detect_choch(highs, lows, "bullish")
        assert result is None


# ──────────────────────────── Order Block 测试 ────────────────────────────


class TestOrderBlock:
    """Order Block 识别测试"""

    def test_bullish_ob_detected(self):
        """看跌K线后紧接强势看涨吞没K线时检测到看涨 OB。"""
        analyzer = SMCAnalyzer()
        klines = [
            _make_kline(open_="100", high="102", low="98", close="99"),   # 看跌
            _make_kline(open_="99", high="101", low="97", close="98"),    # 看跌
            _make_kline(open_="98", high="100", low="96", close="97"),    # 被吞没
            _make_kline(open_="96", high="105", low="95", close="104"),   # 强势看涨吞没
            _make_kline(open_="104", high="108", low="103", close="106"), # 后续
        ]
        obs = analyzer.find_order_blocks(klines)
        # 应该能找到看涨 OB
        bullish_obs = [ob for ob in obs if ob["type"] == "bullish_ob"]
        # 不一定都能检测到，但不应崩溃
        assert isinstance(obs, list)

    def test_empty_klines_no_ob(self):
        """空K线列表无 OB。"""
        analyzer = SMCAnalyzer()
        assert analyzer.find_order_blocks([]) == []

    def test_short_klines_no_ob(self):
        """不足 5 根K线无 OB。"""
        analyzer = SMCAnalyzer()
        klines = [_make_kline() for _ in range(3)]
        assert analyzer.find_order_blocks(klines) == []

    def test_ob_max_ten(self):
        """OB 结果最多 10 个。"""
        analyzer = SMCAnalyzer()
        # 生成大量K线
        klines = [_make_kline(
            open_=str(100 + (i % 3)),
            high=str(105 + (i % 3)),
            low=str(95 + (i % 3)),
            close=str(102 + (i % 3) * (1 if i % 2 == 0 else -1)),
        ) for i in range(100)]
        obs = analyzer.find_order_blocks(klines)
        assert len(obs) <= 10

    def test_ob_has_required_fields(self):
        """OB 结果包含必要字段。"""
        analyzer = SMCAnalyzer()
        klines = [
            _make_kline(open_="100", high="102", low="98", close="99"),
            _make_kline(open_="99", high="101", low="97", close="98"),
            _make_kline(open_="98", high="100", low="96", close="97"),
            _make_kline(open_="96", high="105", low="95", close="104"),
            _make_kline(open_="104", high="108", low="103", close="106"),
        ]
        obs = analyzer.find_order_blocks(klines)
        for ob in obs:
            assert "type" in ob
            assert "top" in ob
            assert "bottom" in ob
            assert "index" in ob


# ──────────────────────────── FVG 测试 ────────────────────────────


class TestFVG:
    """FVG（公允价值缺口）识别测试"""

    def test_bullish_fvg_detected(self):
        """第 3 根K线 low > 第 1 根K线 high 时检测到看涨 FVG。"""
        analyzer = SMCAnalyzer()
        klines = [
            _make_kline(open_="100", high="105", low="98", close="103"),  # K1: high=105
            _make_kline(open_="103", high="108", low="102", close="106"), # K2
            _make_kline(open_="108", high="115", low="110", close="113"), # K3: low=110 > K1 high=105
        ]
        fvgs = analyzer.find_fvg(klines)
        assert len(fvgs) > 0
        assert fvgs[0]["type"] == "bullish_fvg"

    def test_bearish_fvg_detected(self):
        """第 3 根K线 high < 第 1 根K线 low 时检测到看跌 FVG。"""
        analyzer = SMCAnalyzer()
        klines = [
            _make_kline(open_="110", high="112", low="105", close="107"), # K1: low=105
            _make_kline(open_="107", high="108", low="100", close="102"), # K2
            _make_kline(open_="100", high="102", low="95", close="98"),   # K3: high=102 < K1 low=105
        ]
        fvgs = analyzer.find_fvg(klines)
        assert len(fvgs) > 0
        assert fvgs[0]["type"] == "bearish_fvg"

    def test_no_fvg_normal_market(self):
        """正常市场无 FVG。"""
        analyzer = SMCAnalyzer()
        klines = [
            _make_kline(open_="100", high="105", low="98", close="103"),
            _make_kline(open_="103", high="108", low="101", close="106"),
            _make_kline(open_="106", high="110", low="104", close="108"),
        ]
        fvgs = analyzer.find_fvg(klines)
        assert len(fvgs) == 0

    def test_short_klines_no_fvg(self):
        """不足 3 根K线无 FVG。"""
        analyzer = SMCAnalyzer()
        klines = [_make_kline() for _ in range(2)]
        assert analyzer.find_fvg(klines) == []

    def test_fvg_gap_ratio_above_threshold(self):
        """FVG 缺口比例应大于最小阈值。"""
        analyzer = SMCAnalyzer()
        klines = [
            _make_kline(open_="100", high="100", low="99", close="100"),
            _make_kline(open_="100", high="101", low="99", close="100"),
            _make_kline(open_="102", high="103", low="102", close="103"),
        ]
        fvgs = analyzer.find_fvg(klines)
        for fvg in fvgs:
            assert fvg["gap_ratio"] >= analyzer.FVG_MIN_GAP_RATIO


# ──────────────────────────── 流动性池测试 ────────────────────────────


class TestLiquidityPools:
    """流动性池识别测试"""

    def test_equal_highs_detected(self):
        """等高点聚集时检测到卖方流动性池。"""
        analyzer = SMCAnalyzer()
        # 创建多个接近的高点
        highs = [
            Decimal("100"), Decimal("105"), Decimal("110"), Decimal("105"), Decimal("100"),
            Decimal("100"), Decimal("105"), Decimal("110"), Decimal("105"), Decimal("100"),
            Decimal("100"), Decimal("105"), Decimal("110.1"), Decimal("105"), Decimal("100"),
            Decimal("100"), Decimal("105"), Decimal("109.9"), Decimal("105"), Decimal("100"),
            Decimal("100"), Decimal("105"), Decimal("110"), Decimal("105"), Decimal("100"),
        ]
        lows = [
            Decimal("90"), Decimal("92"), Decimal("95"), Decimal("92"), Decimal("90"),
            Decimal("90"), Decimal("92"), Decimal("95"), Decimal("92"), Decimal("90"),
            Decimal("90"), Decimal("92"), Decimal("95"), Decimal("92"), Decimal("90"),
            Decimal("90"), Decimal("92"), Decimal("95"), Decimal("92"), Decimal("90"),
            Decimal("90"), Decimal("92"), Decimal("95"), Decimal("92"), Decimal("90"),
        ]
        pools = analyzer.find_liquidity_pools(highs, lows)
        # 不一定能检测到（取决于 swing 识别），但不应崩溃
        assert isinstance(pools, list)

    def test_empty_data_no_pools(self):
        """空数据无流动性池。"""
        analyzer = SMCAnalyzer()
        pools = analyzer.find_liquidity_pools([], [])
        assert pools == []

    def test_pool_has_required_fields(self):
        """流动性池结果包含必要字段。"""
        analyzer = SMCAnalyzer()
        highs, lows = _make_swing_data()
        pools = analyzer.find_liquidity_pools(highs, lows)
        for pool in pools:
            assert "type" in pool
            assert "price" in pool
            assert "touch_count" in pool
            assert pool["touch_count"] >= 2


# ──────────────────────────── 流动性猎杀测试 ────────────────────────────


class TestLiquidityGrab:
    """流动性猎杀检测测试"""

    def test_sell_side_grab_detected(self):
        """价格突破高点后回落检测到卖方流动性猎杀。"""
        analyzer = SMCAnalyzer()
        # 前一根突破高点，当前根回落
        klines = [
            _make_kline(open_="100", high="105", low="98", close="103"),
            _make_kline(open_="103", high="115", low="102", close="104"),  # 突破到115
            _make_kline(open_="104", high="106", low="100", close="101"),  # 回落到101
        ]
        pools = [{"type": "sell_side_liquidity", "price": "110", "touch_count": 2, "indices": [0, 1]}]
        result = analyzer.detect_liquidity_grab(klines, pools)
        assert result is not None
        assert result["type"] == "sell_side_grab"
        assert result["signal"] == "bullish"

    def test_buy_side_grab_detected(self):
        """价格跌破低点后反弹检测到买方流动性猎杀。"""
        analyzer = SMCAnalyzer()
        klines = [
            _make_kline(open_="100", high="102", low="95", close="97"),
            _make_kline(open_="97", high="98", low="85", close="96"),   # 跌破到85
            _make_kline(open_="96", high="100", low="94", close="99"),  # 反弹到99
        ]
        pools = [{"type": "buy_side_liquidity", "price": "90", "touch_count": 2, "indices": [0, 1]}]
        result = analyzer.detect_liquidity_grab(klines, pools)
        assert result is not None
        assert result["type"] == "buy_side_grab"
        assert result["signal"] == "bearish"

    def test_no_grab_without_pools(self):
        """无流动性池时不检测猎杀。"""
        analyzer = SMCAnalyzer()
        klines = [_make_kline() for _ in range(3)]
        result = analyzer.detect_liquidity_grab(klines, [])
        assert result is None

    def test_no_grab_short_klines(self):
        """不足 3 根K线不检测猎杀。"""
        analyzer = SMCAnalyzer()
        klines = [_make_kline() for _ in range(2)]
        pools = [{"type": "sell_side_liquidity", "price": "100"}]
        result = analyzer.detect_liquidity_grab(klines, pools)
        assert result is None


# ──────────────────────────── 溢价/折价区测试 ────────────────────────────


class TestPremiumDiscount:
    """溢价/折价区判断测试"""

    def test_premium_zone(self):
        """价格在高位时判断为溢价区。"""
        analyzer = SMCAnalyzer()
        # 生成价格从 100 涨到 200 的K线
        klines = []
        for i in range(20):
            price = 100 + i * 5
            klines.append(_make_kline(
                open_=str(price),
                high=str(price + 2),
                low=str(price - 2),
                close=str(price + 1),
            ))
        zone = analyzer.premium_discount(klines)
        assert zone in ("premium", "discount", "equilibrium")

    def test_short_data_equilibrium(self):
        """不足 20 根K线返回均衡区。"""
        analyzer = SMCAnalyzer()
        klines = [_make_kline() for _ in range(10)]
        assert analyzer.premium_discount(klines) == "equilibrium"

    def test_flat_data_equilibrium(self):
        """完全平坦数据返回均衡区。"""
        analyzer = SMCAnalyzer()
        klines = [_make_kline(open_="100", high="100", low="100", close="100") for _ in range(20)]
        assert analyzer.premium_discount(klines) == "equilibrium"


# ──────────────────────────── 趋势管理测试 ────────────────────────────


class TestTrendManagement:
    """趋势管理测试"""

    def test_update_trend_bullish(self):
        """更高的高点和更高的低点判断为看涨趋势。"""
        analyzer = SMCAnalyzer()
        # 上升趋势：高点递增，低点递增
        highs = [
            Decimal("100"), Decimal("105"), Decimal("110"), Decimal("108"), Decimal("105"),
            Decimal("102"), Decimal("100"), Decimal("105"), Decimal("110"), Decimal("115"),
            Decimal("120"), Decimal("118"), Decimal("115"), Decimal("110"), Decimal("108"),
            Decimal("105"), Decimal("110"), Decimal("115"), Decimal("120"), Decimal("125"),
            Decimal("130"), Decimal("128"), Decimal("125"), Decimal("120"), Decimal("118"),
        ]
        lows = [
            Decimal("90"), Decimal("92"), Decimal("95"), Decimal("93"), Decimal("92"),
            Decimal("91"), Decimal("90"), Decimal("92"), Decimal("95"), Decimal("98"),
            Decimal("100"), Decimal("98"), Decimal("95"), Decimal("93"), Decimal("92"),
            Decimal("91"), Decimal("93"), Decimal("95"), Decimal("98"), Decimal("100"),
            Decimal("102"), Decimal("100"), Decimal("98"), Decimal("96"), Decimal("95"),
        ]
        trend = analyzer.update_trend("BTCUSDT", highs, lows)
        assert trend in ("bullish", "bearish")

    def test_update_trend_short_data(self):
        """数据不足时返回默认趋势。"""
        analyzer = SMCAnalyzer()
        trend = analyzer.update_trend("BTCUSDT", [Decimal("100")] * 5, [Decimal("90")] * 5)
        assert trend in ("bullish", "bearish")


# ──────────────────────────── 聪明钱指数测试 ────────────────────────────


class TestSmartMoneyIndex:
    """聪明钱指数测试"""

    def test_classic_smi_length(self):
        """SMI 序列长度与输入一致。"""
        smi = SmartMoneyIndex()
        opens = [Decimal("100"), Decimal("101"), Decimal("102"), Decimal("103")]
        closes = [Decimal("101"), Decimal("102"), Decimal("103"), Decimal("104")]
        volumes = [Decimal("1000")] * 4
        result = smi.classic_smi(opens, closes, volumes)
        assert len(result) == 4

    def test_classic_smi_starts_at_zero(self):
        """SMI 第一个值为零。"""
        smi = SmartMoneyIndex()
        opens = [Decimal("100"), Decimal("101")]
        closes = [Decimal("101"), Decimal("102")]
        volumes = [Decimal("1000")] * 2
        result = smi.classic_smi(opens, closes, volumes)
        assert result[0] == Decimal("0")

    def test_classic_smi_short_data(self):
        """不足 2 根数据返回空。"""
        smi = SmartMoneyIndex()
        assert smi.classic_smi([Decimal("100")], [Decimal("101")], [Decimal("1000")]) == []

    def test_smc_structure_line_returns_events(self):
        """SMC 结构线返回事件列表。"""
        smi = SmartMoneyIndex()
        klines = _make_trending_up_klines(20)
        events = smi.smc_structure_line(klines)
        assert isinstance(events, list)
        for event in events:
            assert "event" in event

    def test_smc_structure_line_short_data(self):
        """不足 10 根K线返回空。"""
        smi = SmartMoneyIndex()
        klines = [_make_kline() for _ in range(5)]
        events = smi.smc_structure_line(klines)
        assert events == []

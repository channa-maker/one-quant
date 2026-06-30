"""
ONE量化 - 选股选币引擎完整测试

覆盖：过滤器 / 因子计算 / ML 打分 / LLM 复核 / 风险约束 / 端到端流水线
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

import pytest

from one_quant.core.types import Instrument, InstrumentType, Market
from one_quant.screener.constraints import (
    CorrelationConstraint,
    DiversificationConstraint,
    PositionLimitConstraint,
)
from one_quant.screener.filters import (
    LiquidityFilter,
    ListingAgeFilter,
    MarketCapFilter,
    TradabilityFilter,
)
from one_quant.screener.pipeline import CandidateAsset, ScreenerPipeline

# ──────────────────────────── 辅助工具 ────────────────────────────


def _make_instrument(
    symbol: str = "BTC/USDT",
    market: Market = Market.SPOT,
    is_active: bool = True,
) -> Instrument:
    """创建测试用标的。"""
    return Instrument(
        internal_id=f"test-{symbol}",
        symbol=symbol,
        market=market,
        instrument_type=InstrumentType.SPOT,
        exchange="binance",
        base_currency=symbol.split("/")[0],
        quote_currency=symbol.split("/")[1],
        tick_size=Decimal("0.01"),
        lot_size=Decimal("0.001"),
        is_active=is_active,
    )


def _make_ticker(
    symbol: str = "BTC/USDT",
    volume_24h: str = "1000000",
    change_pct: str = "5.0",
    market_cap: str = "100000000",
    is_tradable: bool = True,
    listing_date: str | None = None,
    sector: str = "加密货币",
) -> dict:
    """创建测试用 ticker 数据。"""
    ticker: dict = {
        "symbol": symbol,
        "volume_24h": volume_24h,
        "change_pct": change_pct,
        "market_cap": market_cap,
        "is_tradable": is_tradable,
        "sector": sector,
    }
    if listing_date:
        ticker["listing_date"] = listing_date
    return ticker


def _make_candidate(
    symbol: str = "BTC/USDT",
    market: str = "SPOT",
    score: float = 80.0,
    llm_adjustment: float = 5.0,
    final_score: float = 85.0,
    confidence: float = 0.8,
    reason: str = "测试标的",
    factors: dict[str, Any] | None = None,
) -> CandidateAsset:
    """创建测试用候选标的。"""
    return CandidateAsset(
        symbol=symbol,
        market=market,
        score=score,
        llm_adjustment=llm_adjustment,
        final_score=final_score,
        confidence=confidence,
        reason=reason,
        factors=factors or {"momentum_24h": 5.0},
        timestamp_ns=int(time.time() * 1e9),
    )


# ──────────────────────────── 过滤器测试 ────────────────────────────


class TestLiquidityFilter:
    """流动性过滤器测试"""

    def test_pass_above_threshold(self):
        """成交量高于阈值应通过"""
        f = LiquidityFilter(min_volume_24h=Decimal("100000"))
        data = {"BTC/USDT": _make_ticker(volume_24h="200000")}
        result = f.filter(["BTC/USDT"], data)
        assert result == ["BTC/USDT"]

    def test_reject_below_threshold(self):
        """成交量低于阈值应被过滤"""
        f = LiquidityFilter(min_volume_24h=Decimal("100000"))
        data = {"DOGE/USDT": _make_ticker(volume_24h="50000")}
        result = f.filter(["DOGE/USDT"], data)
        assert result == []

    def test_exact_threshold(self):
        """成交量恰好等于阈值应通过"""
        f = LiquidityFilter(min_volume_24h=Decimal("100000"))
        data = {"ETH/USDT": _make_ticker(volume_24h="100000")}
        result = f.filter(["ETH/USDT"], data)
        assert result == ["ETH/USDT"]

    def test_missing_data_defaults_zero(self):
        """无数据的标的默认成交量为 0，应被过滤"""
        f = LiquidityFilter(min_volume_24h=Decimal("100000"))
        result = f.filter(["UNKNOWN/USDT"], {})
        assert result == []

    def test_empty_input(self):
        """空输入返回空列表"""
        f = LiquidityFilter()
        assert f.filter([], {}) == []

    def test_multiple_symbols(self):
        """批量过滤"""
        f = LiquidityFilter(min_volume_24h=Decimal("100000"))
        data = {
            "BTC/USDT": _make_ticker(volume_24h="500000"),
            "LOW/USDT": _make_ticker(volume_24h="10000"),
            "ETH/USDT": _make_ticker(volume_24h="300000"),
        }
        result = f.filter(["BTC/USDT", "LOW/USDT", "ETH/USDT"], data)
        assert result == ["BTC/USDT", "ETH/USDT"]


class TestMarketCapFilter:
    """市值过滤器测试"""

    def test_pass_above_threshold(self):
        """市值高于阈值应通过"""
        f = MarketCapFilter(min_market_cap=Decimal("10000000"))
        data = {"BTC/USDT": _make_ticker(market_cap="50000000")}
        result = f.filter(["BTC/USDT"], data)
        assert result == ["BTC/USDT"]

    def test_reject_below_threshold(self):
        """市值低于阈值应被过滤"""
        f = MarketCapFilter(min_market_cap=Decimal("10000000"))
        data = {"MEME/USDT": _make_ticker(market_cap="100000")}
        result = f.filter(["MEME/USDT"], data)
        assert result == []

    def test_missing_market_cap(self):
        """无市值数据默认为 0，应被过滤"""
        f = MarketCapFilter(min_market_cap=Decimal("10000000"))
        data = {"NEW/USDT": {"volume_24h": "1000000"}}
        result = f.filter(["NEW/USDT"], data)
        assert result == []


class TestListingAgeFilter:
    """上市时长过滤器测试"""

    def test_pass_old_listing(self):
        """上市超过阈值天数应通过"""
        f = ListingAgeFilter(min_days=30)
        data = {"BTC/USDT": _make_ticker(listing_date="2020-01-01")}
        result = f.filter(["BTC/USDT"], data)
        assert result == ["BTC/USDT"]

    def test_reject_new_listing(self):
        """上市不足阈值天数应被过滤"""
        f = ListingAgeFilter(min_days=30)
        # 使用未来日期确保不足 30 天
        data = {"NEW/USDT": _make_ticker(listing_date="2099-01-01")}
        result = f.filter(["NEW/USDT"], data)
        assert result == []

    def test_no_listing_date_passes(self):
        """无上市日期信息默认通过"""
        f = ListingAgeFilter(min_days=30)
        data = {"BTC/USDT": _make_ticker()}
        result = f.filter(["BTC/USDT"], data)
        assert result == ["BTC/USDT"]

    def test_unix_timestamp(self):
        """支持 Unix 时间戳格式"""
        f = ListingAgeFilter(min_days=30)
        # 2020-01-01 的 Unix 时间戳
        data = {"BTC/USDT": _make_ticker(listing_date=1577836800)}
        result = f.filter(["BTC/USDT"], data)
        assert result == ["BTC/USDT"]

    def test_invalid_date_passes(self):
        """无效日期格式默认通过"""
        f = ListingAgeFilter(min_days=30)
        data = {"WEIRD/USDT": _make_ticker(listing_date="not-a-date")}
        result = f.filter(["WEIRD/USDT"], data)
        assert result == ["WEIRD/USDT"]


class TestTradabilityFilter:
    """可交易性过滤器测试"""

    def test_tradable_passes(self):
        """可交易标的应通过"""
        f = TradabilityFilter()
        data = {"BTC/USDT": _make_ticker(is_tradable=True)}
        result = f.filter(["BTC/USDT"], data)
        assert result == ["BTC/USDT"]

    def test_not_tradable_rejected(self):
        """不可交易标的应被过滤"""
        f = TradabilityFilter()
        data = {"HALT/USDT": _make_ticker(is_tradable=False)}
        result = f.filter(["HALT/USDT"], data)
        assert result == []

    def test_missing_tradability_defaults_true(self):
        """无可交易性字段默认可交易"""
        f = TradabilityFilter()
        data = {"BTC/USDT": {"volume_24h": "1000000"}}
        result = f.filter(["BTC/USDT"], data)
        assert result == ["BTC/USDT"]


# ──────────────────────────── 风险约束测试 ────────────────────────────


class TestDiversificationConstraint:
    """分散化约束测试"""

    def test_sector_limit(self):
        """同行业标的数量不超过上限"""
        c = DiversificationConstraint()
        candidates = [
            _make_candidate(f"COIN{i}/USDT", factors={"sector": "DeFi"}) for i in range(5)
        ]
        result = c.apply(candidates, max_per_sector=2, max_per_market=10)
        assert len(result) == 2

    def test_market_limit(self):
        """同市场标的数量不超过上限"""
        c = DiversificationConstraint()
        candidates = [_make_candidate(f"COIN{i}/USDT", market="SPOT") for i in range(5)]
        result = c.apply(candidates, max_per_sector=10, max_per_market=3)
        assert len(result) == 3

    def test_high_score_priority(self):
        """高分标的优先保留"""
        c = DiversificationConstraint()
        candidates = [
            _make_candidate("LOW/USDT", final_score=50.0, factors={"sector": "DeFi"}),
            _make_candidate("HIGH/USDT", final_score=90.0, factors={"sector": "DeFi"}),
            _make_candidate("MID/USDT", final_score=70.0, factors={"sector": "DeFi"}),
        ]
        result = c.apply(candidates, max_per_sector=1, max_per_market=10)
        assert len(result) == 1
        assert result[0].symbol == "HIGH/USDT"

    def test_multiple_sectors(self):
        """不同行业独立计数"""
        c = DiversificationConstraint()
        candidates = [
            _make_candidate("A/USDT", factors={"sector": "DeFi"}),
            _make_candidate("B/USDT", factors={"sector": "NFT"}),
            _make_candidate("C/USDT", factors={"sector": "DeFi"}),
        ]
        result = c.apply(candidates, max_per_sector=1, max_per_market=10)
        assert len(result) == 2
        sectors = {r.factors["sector"] for r in result}
        assert sectors == {"DeFi", "NFT"}

    def test_unknown_sector(self):
        """无行业信息的标的归入"未知"类别"""
        c = DiversificationConstraint()
        candidates = [
            _make_candidate("A/USDT", factors={}),
            _make_candidate("B/USDT", factors={}),
        ]
        result = c.apply(candidates, max_per_sector=1, max_per_market=10)
        # 两个都归入"未知"，只能保留 1 个
        assert len(result) == 1


class TestCorrelationConstraint:
    """相关性约束测试"""

    def test_no_correlation_data_passes_all(self):
        """无相关性数据时全部通过"""
        c = CorrelationConstraint()
        candidates = [_make_candidate("A/USDT"), _make_candidate("B/USDT")]
        result = c.apply(candidates)
        assert len(result) == 2

    def test_high_correlation_removes_lower(self):
        """高相关标的剔除得分较低的"""
        c = CorrelationConstraint()
        candidates = [
            _make_candidate("A/USDT", final_score=90.0),
            _make_candidate("B/USDT", final_score=70.0),
        ]
        corr_matrix = {("A/USDT", "B/USDT"): 0.85}
        result = c.apply(candidates, max_corr=0.7, correlation_matrix=corr_matrix)
        assert len(result) == 1
        assert result[0].symbol == "A/USDT"

    def test_low_correlation_keeps_both(self):
        """低相关标的全部保留"""
        c = CorrelationConstraint()
        candidates = [
            _make_candidate("A/USDT", final_score=90.0),
            _make_candidate("B/USDT", final_score=70.0),
        ]
        corr_matrix = {("A/USDT", "B/USDT"): 0.3}
        result = c.apply(candidates, max_corr=0.7, correlation_matrix=corr_matrix)
        assert len(result) == 2

    def test_negative_correlation_keeps(self):
        """负相关标的保留（绝对值低于阈值时）"""
        c = CorrelationConstraint()
        candidates = [
            _make_candidate("A/USDT", final_score=90.0),
            _make_candidate("B/USDT", final_score=70.0),
        ]
        # -0.5 的绝对值 0.5 < 0.7，应保留
        corr_matrix = {("A/USDT", "B/USDT"): -0.5}
        result = c.apply(candidates, max_corr=0.7, correlation_matrix=corr_matrix)
        assert len(result) == 2

    def test_strong_negative_correlation_removes(self):
        """强负相关标的剔除（绝对值超过阈值时）"""
        c = CorrelationConstraint()
        candidates = [
            _make_candidate("A/USDT", final_score=90.0),
            _make_candidate("B/USDT", final_score=70.0),
        ]
        # -0.8 的绝对值 0.8 > 0.7，应剔除
        corr_matrix = {("A/USDT", "B/USDT"): -0.8}
        result = c.apply(candidates, max_corr=0.7, correlation_matrix=corr_matrix)
        assert len(result) == 1
        assert result[0].symbol == "A/USDT"

    def test_symmetric_correlation_matrix(self):
        """相关性矩阵对称查询"""
        c = CorrelationConstraint()
        candidates = [
            _make_candidate("A/USDT", final_score=90.0),
            _make_candidate("B/USDT", final_score=70.0),
        ]
        # 只提供反向键
        corr_matrix = {("B/USDT", "A/USDT"): 0.9}
        result = c.apply(candidates, max_corr=0.7, correlation_matrix=corr_matrix)
        assert len(result) == 1
        assert result[0].symbol == "A/USDT"

    def test_chained_removal(self):
        """多对高相关标的链式剔除"""
        c = CorrelationConstraint()
        candidates = [
            _make_candidate("A/USDT", final_score=90.0),
            _make_candidate("B/USDT", final_score=80.0),
            _make_candidate("C/USDT", final_score=70.0),
        ]
        corr_matrix = {
            ("A/USDT", "B/USDT"): 0.9,
            ("A/USDT", "C/USDT"): 0.9,
            ("B/USDT", "C/USDT"): 0.9,
        }
        result = c.apply(candidates, max_corr=0.7, correlation_matrix=corr_matrix)
        assert len(result) == 1
        assert result[0].symbol == "A/USDT"


class TestPositionLimitConstraint:
    """单标的持仓上限约束测试"""

    def test_all_within_limit(self):
        """所有标的权重均在上限内"""
        c = PositionLimitConstraint()
        candidates = [
            _make_candidate("A/USDT", final_score=50.0),
            _make_candidate("B/USDT", final_score=50.0),
        ]
        result = c.apply(candidates, max_weight=Decimal("0.6"))
        assert len(result) == 2

    def test_empty_input(self):
        """空输入返回空列表"""
        c = PositionLimitConstraint()
        assert c.apply([], max_weight=Decimal("0.2")) == []

    def test_zero_total_score(self):
        """总得分为零时返回全部"""
        c = PositionLimitConstraint()
        candidates = [
            _make_candidate("A/USDT", final_score=0.0),
        ]
        result = c.apply(candidates, max_weight=Decimal("0.2"))
        assert len(result) == 1


# ──────────────────────────── 流水线测试 ────────────────────────────


class TestScreenerPipeline:
    """选股选币流水线测试"""

    def _build_pipeline(self) -> ScreenerPipeline:
        """构建测试用流水线。"""
        return ScreenerPipeline(
            factor_lib=None,
            ml_model=None,
            llm_provider=None,
        )

    def _build_market_data(self) -> dict:
        """构建测试用市场数据。"""
        return {
            "BTC/USDT": _make_ticker(
                volume_24h="1000000",
                change_pct="5.0",
                market_cap="50000000000",
                sector="加密货币",
            ),
            "ETH/USDT": _make_ticker(
                volume_24h="500000",
                change_pct="-2.0",
                market_cap="20000000000",
                sector="加密货币",
            ),
            "DOGE/USDT": _make_ticker(
                volume_24h="50000",
                change_pct="10.0",
                market_cap="5000000",
                sector="Meme",
            ),
            "HALT/USDT": _make_ticker(
                volume_24h="1000000",
                change_pct="0.0",
                market_cap="100000000",
                is_tradable=False,
            ),
        }

    @pytest.mark.asyncio
    async def test_full_pipeline_run(self):
        """端到端流水线运行"""
        pipeline = self._build_pipeline()
        market_data = self._build_market_data()

        instruments = [
            _make_instrument("BTC/USDT"),
            _make_instrument("ETH/USDT"),
            _make_instrument("DOGE/USDT"),
            _make_instrument("HALT/USDT"),
        ]

        results = await pipeline.run(instruments, market_data, top_n=10)

        # 至少有结果
        assert len(results) > 0
        # 结果类型正确
        for r in results:
            assert isinstance(r, CandidateAsset)
            assert 0 <= r.score <= 100
            assert 0 <= r.confidence <= 1
            assert r.reason  # 非空
            assert r.factors  # 非空
            assert r.timestamp_ns > 0

    @pytest.mark.asyncio
    async def test_inactive_instruments_filtered(self):
        """不可交易标的被过滤"""
        pipeline = self._build_pipeline()
        market_data = self._build_market_data()

        instruments = [
            _make_instrument("HALT/USDT", is_active=False),
        ]
        results = await pipeline.run(instruments, market_data, top_n=10)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_low_volume_filtered(self):
        """低成交量标的被过滤"""
        pipeline = self._build_pipeline()
        market_data = self._build_market_data()

        # DOGE 成交量 50000 < 默认阈值 100000
        instruments = [_make_instrument("DOGE/USDT")]
        results = await pipeline.run(instruments, market_data, top_n=10)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_results_sorted_by_score(self):
        """结果按得分降序排列"""
        pipeline = self._build_pipeline()
        market_data = self._build_market_data()

        instruments = [
            _make_instrument("BTC/USDT"),
            _make_instrument("ETH/USDT"),
        ]
        results = await pipeline.run(instruments, market_data, top_n=10)

        scores = [r.final_score for r in results]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_top_n_limit(self):
        """候选池大小不超过 top_n"""
        pipeline = self._build_pipeline()
        market_data = self._build_market_data()

        instruments = [
            _make_instrument("BTC/USDT"),
            _make_instrument("ETH/USDT"),
        ]
        results = await pipeline.run(instruments, market_data, top_n=1)
        assert len(results) <= 1

    @pytest.mark.asyncio
    async def test_empty_instruments(self):
        """空标的列表返回空结果"""
        pipeline = self._build_pipeline()
        results = await pipeline.run([], {}, top_n=10)
        assert results == []

    @pytest.mark.asyncio
    async def test_factor_momentum_present(self):
        """因子明细包含动量因子"""
        pipeline = self._build_pipeline()
        market_data = self._build_market_data()

        instruments = [_make_instrument("BTC/USDT")]
        results = await pipeline.run(instruments, market_data, top_n=10)

        if results:
            assert "momentum_24h" in results[0].factors

    @pytest.mark.asyncio
    async def test_llm_review_adds_reason(self):
        """LLM 复核层添加中文理由和调整分"""
        pipeline = self._build_pipeline()
        market_data = self._build_market_data()

        instruments = [_make_instrument("BTC/USDT")]
        results = await pipeline.run(instruments, market_data, top_n=10)

        for r in results:
            assert r.reason  # 非空中文理由
            assert isinstance(r.llm_adjustment, float)
            assert isinstance(r.confidence, float)

    def test_stats(self):
        """统计信息正确"""
        pipeline = self._build_pipeline()
        assert pipeline.stats["run_count"] == 0

    @pytest.mark.asyncio
    async def test_stats_after_run(self):
        """运行后统计计数递增"""
        pipeline = self._build_pipeline()
        market_data = self._build_market_data()

        instruments = [_make_instrument("BTC/USDT")]
        await pipeline.run(instruments, market_data, top_n=10)
        assert pipeline.stats["run_count"] == 1

        await pipeline.run(instruments, market_data, top_n=10)
        assert pipeline.stats["run_count"] == 2


# ──────────────────────────── CandidateAsset 测试 ────────────────────────────


class TestCandidateAsset:
    """候选标的数据模型测试"""

    def test_creation(self):
        """正常创建候选标的"""
        c = _make_candidate()
        assert c.symbol == "BTC/USDT"
        assert c.market == "SPOT"
        assert c.score == 80.0
        assert c.final_score == 85.0

    def test_frozen(self):
        """候选标的不可变"""
        c = _make_candidate()
        with pytest.raises(Exception):
            c.symbol = "ETH/USDT"  # type: ignore

    def test_default_factors(self):
        """默认因子字典"""
        c = _make_candidate(factors=None)
        assert isinstance(c.factors, dict)

    def test_fields_types(self):
        """字段类型正确"""
        c = _make_candidate()
        assert isinstance(c.symbol, str)
        assert isinstance(c.score, float)
        assert isinstance(c.llm_adjustment, float)
        assert isinstance(c.final_score, float)
        assert isinstance(c.confidence, float)
        assert isinstance(c.reason, str)
        assert isinstance(c.factors, dict)
        assert isinstance(c.timestamp_ns, int)


# ──────────────────────────── 集成测试 ────────────────────────────


class TestFilterChain:
    """过滤器链式调用集成测试"""

    def test_chain_filters(self):
        """多个过滤器串联"""
        liquidity = LiquidityFilter(min_volume_24h=Decimal("100000"))
        market_cap = MarketCapFilter(min_market_cap=Decimal("10000000"))
        tradability = TradabilityFilter()

        symbols = ["BTC/USDT", "LOW/USDT", "HALT/USDT"]
        data = {
            "BTC/USDT": _make_ticker(
                volume_24h="1000000",
                market_cap="50000000000",
                is_tradable=True,
            ),
            "LOW/USDT": _make_ticker(
                volume_24h="50000",
                market_cap="50000000000",
                is_tradable=True,
            ),
            "HALT/USDT": _make_ticker(
                volume_24h="1000000",
                market_cap="50000000000",
                is_tradable=False,
            ),
        }

        result = liquidity.filter(symbols, data)
        result = market_cap.filter(result, data)
        result = tradability.filter(result, data)

        assert result == ["BTC/USDT"]


class TestConstraintChain:
    """约束链式调用集成测试"""

    def test_chain_constraints(self):
        """多个约束串联"""
        diversification = DiversificationConstraint()
        correlation = CorrelationConstraint()

        candidates = [
            _make_candidate("A/USDT", final_score=90.0, factors={"sector": "DeFi"}),
            _make_candidate("B/USDT", final_score=80.0, factors={"sector": "DeFi"}),
            _make_candidate("C/USDT", final_score=70.0, factors={"sector": "NFT"}),
        ]

        # 先应用分散化约束
        result = diversification.apply(candidates, max_per_sector=1, max_per_market=10)
        # DeFi 只保留 A，NFT 保留 C
        assert len(result) == 2
        symbols = {r.symbol for r in result}
        assert symbols == {"A/USDT", "C/USDT"}

        # 再应用相关性约束
        corr_matrix = {("A/USDT", "C/USDT"): 0.9}
        result = correlation.apply(result, max_corr=0.7, correlation_matrix=corr_matrix)
        assert len(result) == 1
        assert result[0].symbol == "A/USDT"

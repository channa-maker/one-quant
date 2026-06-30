"""
ONE量化 - 选股过滤器与约束测试

覆盖：LiquidityFilter、MarketCapFilter、ListingAgeFilter、TradabilityFilter、
DiversificationConstraint、CorrelationConstraint、PositionLimitConstraint。
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

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
from one_quant.screener.pipeline import CandidateAsset

# ──────────────── 辅助 ────────────────


def _make_candidate(symbol, market="SPOT", score=50.0, final_score=50.0, factors=None):
    return CandidateAsset(
        symbol=symbol,
        market=market,
        score=score,
        llm_adjustment=0.0,
        final_score=final_score,
        confidence=0.8,
        reason="测试",
        factors=factors or {},
        timestamp_ns=1700000000000000000,
    )


# ════════════════════════════════════════════════════════════════
# 过滤器
# ════════════════════════════════════════════════════════════════


class TestLiquidityFilter:
    """流动性过滤器"""

    def test_pass_high_volume(self):
        f = LiquidityFilter(min_volume_24h=Decimal("100000"))
        market_data = {"BTC/USDT": {"volume_24h": "200000"}}
        result = f.filter(["BTC/USDT"], market_data)
        assert "BTC/USDT" in result

    def test_fail_low_volume(self):
        f = LiquidityFilter(min_volume_24h=Decimal("100000"))
        market_data = {"BTC/USDT": {"volume_24h": "50000"}}
        result = f.filter(["BTC/USDT"], market_data)
        assert "BTC/USDT" not in result

    def test_missing_volume(self):
        f = LiquidityFilter()
        market_data = {"BTC/USDT": {}}
        result = f.filter(["BTC/USDT"], market_data)
        assert "BTC/USDT" not in result  # defaults to 0

    def test_empty_symbols(self):
        f = LiquidityFilter()
        result = f.filter([], {})
        assert result == []

    def test_multiple_symbols(self):
        f = LiquidityFilter(min_volume_24h=Decimal("100000"))
        market_data = {
            "BTC/USDT": {"volume_24h": "200000"},
            "ETH/USDT": {"volume_24h": "50000"},
            "SOL/USDT": {"volume_24h": "150000"},
        }
        result = f.filter(["BTC/USDT", "ETH/USDT", "SOL/USDT"], market_data)
        assert len(result) == 2
        assert "ETH/USDT" not in result


class TestMarketCapFilter:
    """市值过滤器"""

    def test_pass_high_cap(self):
        f = MarketCapFilter(min_market_cap=Decimal("10000000"))
        market_data = {"BTC/USDT": {"market_cap": "50000000"}}
        result = f.filter(["BTC/USDT"], market_data)
        assert "BTC/USDT" in result

    def test_fail_low_cap(self):
        f = MarketCapFilter(min_market_cap=Decimal("10000000"))
        market_data = {"BTC/USDT": {"market_cap": "5000000"}}
        result = f.filter(["BTC/USDT"], market_data)
        assert "BTC/USDT" not in result

    def test_missing_cap(self):
        f = MarketCapFilter()
        market_data = {"BTC/USDT": {}}
        result = f.filter(["BTC/USDT"], market_data)
        assert "BTC/USDT" not in result


class TestListingAgeFilter:
    """上市时长过滤器"""

    def test_old_listing_passes(self):
        f = ListingAgeFilter(min_days=30)
        old_date = (datetime.now(UTC) - timedelta(days=60)).isoformat()
        market_data = {"BTC/USDT": {"listing_date": old_date}}
        result = f.filter(["BTC/USDT"], market_data)
        assert "BTC/USDT" in result

    def test_new_listing_fails(self):
        f = ListingAgeFilter(min_days=30)
        new_date = (datetime.now(UTC) - timedelta(days=5)).isoformat()
        market_data = {"BTC/USDT": {"listing_date": new_date}}
        result = f.filter(["BTC/USDT"], market_data)
        assert "BTC/USDT" not in result

    def test_no_listing_date_passes(self):
        f = ListingAgeFilter(min_days=30)
        market_data = {"BTC/USDT": {}}
        result = f.filter(["BTC/USDT"], market_data)
        assert "BTC/USDT" in result

    def test_unix_timestamp(self):
        f = ListingAgeFilter(min_days=30)
        old_ts = int((datetime.now(UTC) - timedelta(days=60)).timestamp())
        market_data = {"BTC/USDT": {"listing_date": old_ts}}
        result = f.filter(["BTC/USDT"], market_data)
        assert "BTC/USDT" in result

    def test_invalid_date_passes(self):
        f = ListingAgeFilter(min_days=30)
        market_data = {"BTC/USDT": {"listing_date": "not-a-date"}}
        result = f.filter(["BTC/USDT"], market_data)
        assert "BTC/USDT" in result  # invalid → pass


class TestTradabilityFilter:
    """可交易性过滤器"""

    def test_tradable_passes(self):
        f = TradabilityFilter()
        market_data = {"BTC/USDT": {"is_tradable": True}}
        result = f.filter(["BTC/USDT"], market_data)
        assert "BTC/USDT" in result

    def test_not_tradable_fails(self):
        f = TradabilityFilter()
        market_data = {"BTC/USDT": {"is_tradable": False}}
        result = f.filter(["BTC/USDT"], market_data)
        assert "BTC/USDT" not in result

    def test_missing_tradable_defaults_true(self):
        f = TradabilityFilter()
        market_data = {"BTC/USDT": {}}
        result = f.filter(["BTC/USDT"], market_data)
        assert "BTC/USDT" in result


# ════════════════════════════════════════════════════════════════
# 约束
# ════════════════════════════════════════════════════════════════


class TestDiversificationConstraint:
    """分散化约束"""

    def test_sector_limit(self):
        c = DiversificationConstraint()
        candidates = [
            _make_candidate("A", factors={"sector": "tech"}, final_score=90),
            _make_candidate("B", factors={"sector": "tech"}, final_score=80),
            _make_candidate("C", factors={"sector": "tech"}, final_score=70),
            _make_candidate("D", factors={"sector": "tech"}, final_score=60),
        ]
        result = c.apply(candidates, max_per_sector=2)
        assert len(result) == 2

    def test_market_limit(self):
        c = DiversificationConstraint()
        candidates = [
            _make_candidate("A", market="SPOT", final_score=90),
            _make_candidate("B", market="SPOT", final_score=80),
            _make_candidate("C", market="SPOT", final_score=70),
        ]
        result = c.apply(candidates, max_per_market=2)
        assert len(result) == 2

    def test_high_score_kept(self):
        c = DiversificationConstraint()
        candidates = [
            _make_candidate("LOW", factors={"sector": "tech"}, final_score=50),
            _make_candidate("HIGH", factors={"sector": "tech"}, final_score=90),
        ]
        result = c.apply(candidates, max_per_sector=1)
        assert len(result) == 1
        assert result[0].symbol == "HIGH"

    def test_empty_candidates(self):
        c = DiversificationConstraint()
        result = c.apply([])
        assert result == []

    def test_multiple_sectors(self):
        c = DiversificationConstraint()
        candidates = [
            _make_candidate("A", factors={"sector": "tech"}, final_score=90),
            _make_candidate("B", factors={"sector": "finance"}, final_score=80),
            _make_candidate("C", factors={"sector": "tech"}, final_score=70),
        ]
        result = c.apply(candidates, max_per_sector=2)
        assert len(result) == 3


class TestCorrelationConstraint:
    """相关性约束"""

    def test_high_corr_removes_lower_score(self):
        c = CorrelationConstraint()
        candidates = [
            _make_candidate("A", final_score=90),
            _make_candidate("B", final_score=70),
        ]
        corr = {("A", "B"): 0.9}
        result = c.apply(candidates, max_corr=0.7, correlation_matrix=corr)
        assert len(result) == 1
        assert result[0].symbol == "A"

    def test_low_corr_keeps_both(self):
        c = CorrelationConstraint()
        candidates = [
            _make_candidate("A", final_score=90),
            _make_candidate("B", final_score=70),
        ]
        corr = {("A", "B"): 0.3}
        result = c.apply(candidates, max_corr=0.7, correlation_matrix=corr)
        assert len(result) == 2

    def test_no_correlation_data(self):
        c = CorrelationConstraint()
        candidates = [_make_candidate("A"), _make_candidate("B")]
        result = c.apply(candidates, max_corr=0.7, correlation_matrix=None)
        assert len(result) == 2

    def test_reverse_corr_key(self):
        c = CorrelationConstraint()
        candidates = [
            _make_candidate("A", final_score=90),
            _make_candidate("B", final_score=70),
        ]
        corr = {("B", "A"): 0.9}  # reversed key
        result = c.apply(candidates, max_corr=0.7, correlation_matrix=corr)
        assert len(result) == 1

    def test_empty_candidates(self):
        c = CorrelationConstraint()
        result = c.apply([], max_corr=0.7, correlation_matrix={})
        assert result == []


class TestPositionLimitConstraint:
    """持仓上限约束"""

    def test_within_limit(self):
        c = PositionLimitConstraint()
        candidates = [
            _make_candidate("A", final_score=50),
            _make_candidate("B", final_score=50),
        ]
        result = c.apply(candidates, max_weight=Decimal("0.6"))
        assert len(result) == 2

    def test_exceeds_limit_filtered(self):
        c = PositionLimitConstraint()
        candidates = [
            _make_candidate("A", final_score=90),
            _make_candidate("B", final_score=10),
        ]
        result = c.apply(candidates, max_weight=Decimal("0.8"))
        # A has weight 0.9 > 0.8, so it's filtered out
        assert len(result) == 1
        assert result[0].symbol == "B"

    def test_empty_candidates(self):
        c = PositionLimitConstraint()
        result = c.apply([])
        assert result == []

    def test_zero_total_score(self):
        c = PositionLimitConstraint()
        candidates = [
            _make_candidate("A", final_score=0),
        ]
        result = c.apply(candidates)
        assert len(result) == 1

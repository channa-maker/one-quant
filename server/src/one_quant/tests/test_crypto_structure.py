"""加密结构测试 — OnChainAnalyzer, DerivativesStructure, OptionStructure, StrategyFusion"""

from __future__ import annotations

from decimal import Decimal

from one_quant.strategy.crypto_structure import (
    DerivativesStructure,
    OnChainAnalyzer,
    OptionStructure,
    StrategyFusion,
)

# ──────────────────────────── OnChainAnalyzer 测试 ────────────────────────────


class TestOnChainAnalyzer:
    def test_exchange_netflow_empty(self):
        a = OnChainAnalyzer()
        result = a.exchange_netflow([], [])
        assert result["trend"] == "neutral"
        assert result["signal"] == "neutral"
        assert result["intensity"] == 0.0

    def test_exchange_netflow_inflow(self):
        a = OnChainAnalyzer()
        inflows = [Decimal("100")] * 24
        outflows = [Decimal("50")] * 24
        result = a.exchange_netflow(inflows, outflows)
        assert result["trend"] == "inflow"
        assert result["signal"] == "bearish"
        assert Decimal(result["cumulative"]) > 0

    def test_exchange_netflow_outflow(self):
        a = OnChainAnalyzer()
        inflows = [Decimal("30")] * 24
        outflows = [Decimal("80")] * 24
        result = a.exchange_netflow(inflows, outflows)
        assert result["trend"] == "outflow"
        assert result["signal"] == "bullish"
        assert Decimal(result["cumulative"]) < 0

    def test_exchange_netflow_neutral(self):
        a = OnChainAnalyzer()
        inflows = [Decimal("100")] * 24
        outflows = [Decimal("100")] * 24
        result = a.exchange_netflow(inflows, outflows)
        assert result["trend"] == "neutral"
        assert result["signal"] == "neutral"

    def test_exchange_netflow_window(self):
        a = OnChainAnalyzer()
        inflows = [Decimal("100")] * 48
        outflows = [Decimal("50")] * 48
        result = a.exchange_netflow(inflows, outflows, window=10)
        # Only last 10 used
        assert Decimal(result["cumulative"]) == Decimal("500.00")

    def test_whale_activity_empty(self):
        a = OnChainAnalyzer()
        result = a.whale_activity([])
        assert result["whale_count"] == 0
        assert result["signal"] == "neutral"

    def test_whale_activity_to_exchange(self):
        a = OnChainAnalyzer()
        transfers = [
            {"from": "wallet_a", "to": "binance", "amount": 200, "timestamp": 1},
        ]
        result = a.whale_activity(transfers)
        assert result["whale_count"] == 1
        assert result["net_direction"] == "to_exchange"
        assert result["signal"] == "bearish"

    def test_whale_activity_from_exchange(self):
        a = OnChainAnalyzer()
        transfers = [
            {"from": "binance", "to": "wallet_a", "amount": 150, "timestamp": 1},
        ]
        result = a.whale_activity(transfers)
        assert result["net_direction"] == "from_exchange"
        assert result["signal"] == "bullish"

    def test_whale_activity_below_threshold(self):
        a = OnChainAnalyzer()
        transfers = [{"from": "a", "to": "b", "amount": 10, "timestamp": 1}]
        result = a.whale_activity(transfers, threshold=Decimal("100"))
        assert result["whale_count"] == 0

    def test_whale_activity_largest_tx(self):
        a = OnChainAnalyzer()
        transfers = [
            {"from": "wallet_a", "to": "binance", "amount": 100, "timestamp": 1},
            {"from": "wallet_b", "to": "binance", "amount": 500, "timestamp": 2},
        ]
        result = a.whale_activity(transfers)
        assert result["largest_tx"]["amount"] == "500"

    def test_stablecoin_flow_empty(self):
        a = OnChainAnalyzer()
        result = a.stablecoin_flow([], [])
        assert result["trend"] == "stable"
        assert result["signal"] == "neutral"

    def test_stablecoin_flow_increasing(self):
        a = OnChainAnalyzer()
        usdt = [Decimal("100")] * 3 + [Decimal("200")] * 4
        usdc = [Decimal("50")] * 3 + [Decimal("100")] * 4
        result = a.stablecoin_flow(usdt, usdc, window=7)
        assert result["trend"] == "increasing"
        assert result["signal"] == "bullish"

    def test_stablecoin_flow_decreasing(self):
        a = OnChainAnalyzer()
        usdt = [Decimal("200")] * 3 + [Decimal("50")] * 4
        usdc = [Decimal("100")] * 3 + [Decimal("20")] * 4
        result = a.stablecoin_flow(usdt, usdc, window=7)
        assert result["trend"] == "decreasing"
        assert result["signal"] == "bearish"

    def test_stablecoin_flow_usdt_share(self):
        a = OnChainAnalyzer()
        usdt = [Decimal("100")] * 7
        usdc = [Decimal("100")] * 7
        result = a.stablecoin_flow(usdt, usdc)
        assert abs(result["usdt_share"] - 0.5) < 0.01

    def test_stablecoin_flow_short_data(self):
        a = OnChainAnalyzer()
        result = a.stablecoin_flow([Decimal("100")], [Decimal("50")], window=7)
        assert result["trend"] == "stable"


# ──────────────────────────── DerivativesStructure 测试 ────────────────────────────


class TestDerivativesStructure:
    def test_funding_rate_extreme_high(self):
        d = DerivativesStructure()
        result = d.funding_rate_extreme(Decimal("0.002"))
        assert result["level"] == "extreme_high"
        assert result["signal"] == "bearish"

    def test_funding_rate_extreme_low(self):
        d = DerivativesStructure()
        result = d.funding_rate_extreme(Decimal("-0.002"))
        assert result["level"] == "extreme_low"
        assert result["signal"] == "bullish"

    def test_funding_rate_normal(self):
        d = DerivativesStructure()
        result = d.funding_rate_extreme(Decimal("0.0001"))
        assert result["level"] == "normal"
        assert result["signal"] == "neutral"

    def test_funding_rate_high(self):
        d = DerivativesStructure()
        result = d.funding_rate_extreme(Decimal("0.0006"))
        assert result["level"] == "high"

    def test_funding_rate_low(self):
        d = DerivativesStructure()
        result = d.funding_rate_extreme(Decimal("-0.0006"))
        assert result["level"] == "low"

    def test_funding_rate_annualized(self):
        d = DerivativesStructure()
        result = d.funding_rate_extreme(Decimal("0.001"))
        annualized = Decimal(result["annualized"])
        assert annualized > 0

    def test_oi_change_insufficient_data(self):
        d = DerivativesStructure()
        result = d.oi_change([{"oi": 100, "price": 50000}])
        assert result["signal"] == "neutral"
        assert result["interpretation"] == "数据不足"

    def test_oi_change_bullish(self):
        d = DerivativesStructure()
        result = d.oi_change(
            [
                {"oi": 1000, "price": 50000},
                {"oi": 1200, "price": 51000},
            ]
        )
        assert result["signal"] == "bullish"
        assert result["price_direction"] == "up"

    def test_oi_change_bearish(self):
        d = DerivativesStructure()
        result = d.oi_change(
            [
                {"oi": 1000, "price": 50000},
                {"oi": 1200, "price": 49000},
            ]
        )
        assert result["signal"] == "bearish"
        assert result["price_direction"] == "down"

    def test_oi_change_bullish_weak(self):
        d = DerivativesStructure()
        result = d.oi_change(
            [
                {"oi": 1000, "price": 50000},
                {"oi": 800, "price": 51000},
            ]
        )
        assert result["signal"] == "bullish_weak"

    def test_oi_change_bearish_weak(self):
        d = DerivativesStructure()
        result = d.oi_change(
            [
                {"oi": 1000, "price": 50000},
                {"oi": 800, "price": 49000},
            ]
        )
        assert result["signal"] == "bearish_weak"

    def test_liquidation_heatmap_empty(self):
        d = DerivativesStructure()
        result = d.liquidation_heatmap([])
        assert result["signal"] == "neutral"
        assert result["heatmap"] == {}

    def test_liquidation_heatmap_single_price(self):
        d = DerivativesStructure()
        positions = [
            {"side": "long", "size": 10, "liquidation_price": 45000, "entry_price": 50000},
            {"side": "long", "size": 5, "liquidation_price": 45000, "entry_price": 50000},
        ]
        result = d.liquidation_heatmap(positions)
        assert len(result["heatmap"]) == 1
        assert len(result["high_density_zones"]) == 1

    def test_liquidation_heatmap_with_zones(self):
        d = DerivativesStructure()
        positions = [
            {"side": "long", "size": 10, "liquidation_price": 45000, "entry_price": 50000},
            {"side": "long", "size": 5, "liquidation_price": 44000, "entry_price": 50000},
            {"side": "short", "size": 8, "liquidation_price": 55000, "entry_price": 50000},
            {"side": "short", "size": 3, "liquidation_price": 56000, "entry_price": 50000},
        ]
        result = d.liquidation_heatmap(positions)
        assert len(result["high_density_zones"]) > 0
        assert result["signal"] in ("bullish", "bearish", "neutral")


# ──────────────────────────── OptionStructure 测试 ────────────────────────────


class TestOptionStructure:
    def test_max_pain_empty(self):
        os = OptionStructure()
        assert os.max_pain([]) == Decimal("0")

    def test_max_pain_single_strike(self):
        os = OptionStructure()
        chain = [{"strike": 100, "type": "call", "open_interest": 100}]
        assert os.max_pain(chain) == Decimal("100")

    def test_max_pain_calculation(self):
        os = OptionStructure()
        chain = [
            {"strike": 90, "type": "put", "open_interest": 100},
            {"strike": 100, "type": "call", "open_interest": 100},
            {"strike": 100, "type": "put", "open_interest": 100},
            {"strike": 110, "type": "call", "open_interest": 100},
        ]
        result = os.max_pain(chain)
        assert result in (Decimal("90"), Decimal("100"), Decimal("110"))

    def test_gex_exposure_empty(self):
        os = OptionStructure()
        result = os.gex_exposure([], Decimal("100"))
        assert result["regime"] == "neutral"
        assert result["total_gex"] == "0"

    def test_gex_exposure_stabilizing(self):
        os = OptionStructure()
        chain = [
            {"strike": 100, "type": "call", "open_interest": 100, "gamma": 0.05},
        ]
        result = os.gex_exposure(chain, Decimal("100"))
        assert result["regime"] == "stabilizing"

    def test_gex_exposure_amplifying(self):
        os = OptionStructure()
        chain = [
            {"strike": 100, "type": "put", "open_interest": 100, "gamma": 0.05},
        ]
        result = os.gex_exposure(chain, Decimal("100"))
        assert result["regime"] == "amplifying"

    def test_put_call_ratio_balanced(self):
        os = OptionStructure()
        chain = [
            {"type": "call", "open_interest": 100, "volume": 50},
            {"type": "put", "open_interest": 100, "volume": 50},
        ]
        result = os.put_call_ratio(chain)
        assert abs(result["oi_ratio"] - 1.0) < 0.01
        assert result["sentiment"] == "neutral"
        assert result["extreme"] is False

    def test_put_call_ratio_fear(self):
        os = OptionStructure()
        chain = [
            {"type": "call", "open_interest": 100},
            {"type": "put", "open_interest": 200},
        ]
        result = os.put_call_ratio(chain)
        assert result["oi_ratio"] > 1.0
        assert result["sentiment"] == "fear"

    def test_put_call_ratio_greed(self):
        os = OptionStructure()
        chain = [
            {"type": "call", "open_interest": 300},
            {"type": "put", "open_interest": 100},
        ]
        result = os.put_call_ratio(chain)
        assert result["oi_ratio"] < 1.0
        assert result["sentiment"] == "greed"

    def test_put_call_ratio_extreme_fear(self):
        os = OptionStructure()
        chain = [
            {"type": "call", "open_interest": 100},
            {"type": "put", "open_interest": 200},
        ]
        result = os.put_call_ratio(chain)
        assert result["extreme"] is True

    def test_iv_skew_empty(self):
        os = OptionStructure()
        result = os.iv_skew([])
        assert result["skew"] == 0.0
        assert result["interpretation"] == "数据不足"

    def test_iv_skew_positive(self):
        os = OptionStructure()
        chain = [
            {"strike": 80, "type": "put", "iv": 0.5},
            {"strike": 100, "type": "call", "iv": 0.3},
            {"strike": 120, "type": "call", "iv": 0.25},
        ]
        result = os.iv_skew(chain)
        assert result["skew"] > 0.05
        assert "恐慌" in result["interpretation"]

    def test_iv_skew_negative(self):
        os = OptionStructure()
        chain = [
            {"strike": 80, "type": "put", "iv": 0.1},
            {"strike": 100, "type": "call", "iv": 0.3},
            {"strike": 120, "type": "call", "iv": 0.5},
        ]
        result = os.iv_skew(chain)
        assert result["skew"] < -0.05
        assert "贪婪" in result["interpretation"]


# ──────────────────────────── StrategyFusion 测试 ────────────────────────────


class TestStrategyFusion:
    def test_all_buy_signals(self):
        f = StrategyFusion()
        result = f.fuse(
            order_flow={"side": "buy", "strength": 0.8},
            smc={"side": "buy", "strength": 0.7},
            ml_score=0.5,
            llm_signal={"side": "buy", "confidence": 0.9},
        )
        assert result["side"] == "buy"
        assert result["layers_agreed"] >= 3
        assert result["confidence"] == "high"
        assert result["llm_veto"] is False

    def test_all_sell_signals(self):
        f = StrategyFusion()
        result = f.fuse(
            order_flow={"side": "sell", "strength": 0.8},
            smc={"side": "sell", "strength": 0.7},
            ml_score=-0.5,
            llm_signal={"side": "sell", "confidence": 0.9},
        )
        assert result["side"] == "sell"
        assert result["layers_agreed"] >= 3

    def test_neutral_signals(self):
        f = StrategyFusion()
        result = f.fuse(
            order_flow={"side": "neutral", "strength": 0.0},
            smc={"side": "neutral", "strength": 0.0},
            ml_score=0.0,
            llm_signal={"side": "neutral", "confidence": 0.0},
        )
        assert result["side"] == "neutral"
        assert result["layers_agreed"] == 0

    def test_llm_veto(self):
        f = StrategyFusion()
        # Only 2 layers buy (order_flow + smc), ml is neutral → agreeing=2 ≤ 2 → veto
        result = f.fuse(
            order_flow={"side": "buy", "strength": 0.5},
            smc={"side": "buy", "strength": 0.5},
            ml_score=0.05,  # below 0.1 threshold → neutral
            llm_signal={"side": "sell", "confidence": 0.9},
        )
        assert result["llm_veto"] is True
        assert result["side"] == "neutral"

    def test_no_llm_veto_when_strong_consensus(self):
        f = StrategyFusion()
        result = f.fuse(
            order_flow={"side": "buy", "strength": 0.9},
            smc={"side": "buy", "strength": 0.9},
            ml_score=0.8,
            llm_signal={"side": "sell", "confidence": 0.9},
        )
        # 3 layers agree → no veto even with strong LLM
        assert result["llm_veto"] is False

    def test_mixed_signals(self):
        f = StrategyFusion()
        result = f.fuse(
            order_flow={"side": "buy", "strength": 0.8},
            smc={"side": "sell", "strength": 0.6},
            ml_score=0.1,
            llm_signal={"side": "neutral", "confidence": 0.3},
        )
        assert result["side"] in ("buy", "sell", "neutral")
        assert 0 <= result["strength"] <= 1

    def test_strength_capped_at_one(self):
        f = StrategyFusion()
        result = f.fuse(
            order_flow={"side": "buy", "strength": 1.0},
            smc={"side": "buy", "strength": 1.0},
            ml_score=1.0,
            llm_signal={"side": "buy", "confidence": 1.0},
        )
        assert result["strength"] <= 1.0

    def test_detail_structure(self):
        f = StrategyFusion()
        result = f.fuse(
            order_flow={"side": "buy", "strength": 0.5},
            smc={"side": "neutral", "strength": 0.0},
            ml_score=0.3,
            llm_signal={"side": "buy", "confidence": 0.7},
        )
        assert "buy_score" in result["detail"]
        assert "sell_score" in result["detail"]
        assert "layers" in result["detail"]
        assert "order_flow" in result["detail"]["layers"]

    def test_ml_score_threshold(self):
        f = StrategyFusion()
        # ml_score = 0.05 → below 0.1 threshold → neutral
        result = f.fuse(
            order_flow={"side": "neutral", "strength": 0},
            smc={"side": "neutral", "strength": 0},
            ml_score=0.05,
            llm_signal={"side": "neutral", "confidence": 0},
        )
        assert result["detail"]["layers"]["ml"]["side"] == "neutral"

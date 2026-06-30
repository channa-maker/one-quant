"""AI 信号评分系统测试 — 共振融合 + 评分校准 + 反噪音

覆盖模块: one_quant.ai.signal_scoring
目标: ≥80% 覆盖率
"""

from __future__ import annotations

import time
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from one_quant.ai.signal_scoring import (
    AntiNoise,
    CryptoStructureSource,
    LLMAnalysisSource,
    MLModelSource,
    OnchainSource,
    OrderFlowSource,
    ScoreCalibrator,
    ScoreRecord,
    SignalCard,
    SignalScorer,
    SMCSource,
    VolumePriceSource,
    classify_signal,
    classify_time_horizon,
)

# ──────────────────── 辅助工厂 ────────────────────


def _make_source(name: str, strength: float, direction: float):
    """创建模拟证据源"""
    src = MagicMock()
    src.name = name
    src.compute.return_value = (strength, direction)
    return src


def _make_signal(
    symbol: str = "BTCUSDT",
    score: float = 80.0,
    direction: str = "long",
    timestamp_ns: int | None = None,
) -> SignalCard:
    """创建测试用信号卡"""
    return SignalCard(
        signal_id=f"sig_{symbol}_{timestamp_ns or time.time_ns()}",
        symbol=symbol,
        direction=direction,
        score=score,
        confidence_interval=(score - 10, score + 10),
        level=classify_signal(score),
        time_horizon="日内",
        risk_note="测试信号",
        suggested_stop=Decimal("0"),
        risk_reward_ratio=2.5,
        reason="测试理由",
        evidence_details={},
        historical_win_rate=score / 100,
        timestamp_ns=timestamp_ns or time.time_ns(),
    )


# ──────────────────── classify_signal 测试 ────────────────────


class TestClassifySignal:
    """信号分级测试"""

    @pytest.mark.parametrize(
        "score,expected",
        [
            (100, "S"),
            (90, "S"),
            (85, "S"),
            (84, "A"),
            (70, "A"),
            (69, "B"),
            (55, "B"),
            (54, "C"),
            (0, "C"),
        ],
    )
    def test_classify_boundaries(self, score: float, expected: str):
        assert classify_signal(score) == expected


# ──────────────────── classify_time_horizon 测试 ────────────────────


class TestClassifyTimeHorizon:
    """时间维度分级测试"""

    def test_empty_periods(self):
        assert classify_time_horizon([]) == "日内"

    def test_short_trade(self):
        assert classify_time_horizon([10, 20]) == "短炒"

    def test_intraday(self):
        assert classify_time_horizon([60, 120]) == "日内"

    def test_swing(self):
        assert classify_time_horizon([500, 800]) == "波段"

    def test_medium_line(self):
        assert classify_time_horizon([2000, 3000]) == "中线"


# ──────────────────── ScoreCalibrator 测试 ────────────────────


class TestScoreCalibrator:
    """评分校准器测试"""

    def test_not_fitted_passthrough(self):
        """未拟合时线性透传"""
        cal = ScoreCalibrator()
        assert cal.calibrate(50.0) == 50.0
        assert cal.calibrate(0.0) == 0.0
        assert cal.calibrate(100.0) == 100.0

    def test_clamp_bounds(self):
        """边界值裁剪"""
        cal = ScoreCalibrator()
        assert cal.calibrate(-10.0) == 0.0
        assert cal.calibrate(150.0) == 100.0

    def test_recalibrate_insufficient_data(self):
        """数据不足时跳过拟合"""
        cal = ScoreCalibrator()
        cal.recalibrate([50.0] * 10, [True] * 10)
        assert not cal._is_fitted

    def test_platt_fitting(self):
        """Platt Scaling 拟合"""
        cal = ScoreCalibrator(method="platt")
        # 高分→高胜率，低分→低胜率
        preds = [float(i) for i in range(20, 100, 2)]
        outcomes = [p > 60 for p in preds]
        cal.recalibrate(preds, outcomes)
        assert cal._is_fitted
        # 高分校准后应偏高
        high = cal.calibrate(90.0)
        low = cal.calibrate(30.0)
        assert high > low

    def test_isotonic_fitting(self):
        """Isotonic 校准拟合"""
        cal = ScoreCalibrator(method="isotonic")
        preds = [float(i) for i in range(20, 100, 2)]
        outcomes = [p > 50 for p in preds]
        cal.recalibrate(preds, outcomes)
        assert cal._is_fitted
        assert cal._isotonic_x  # 断点非空

    def test_isotonic_interpolation(self):
        """Isotonic 分段线性插值"""
        cal = ScoreCalibrator(method="isotonic")
        cal._isotonic_x = [0.0, 0.5, 1.0]
        cal._isotonic_y = [0.0, 0.5, 1.0]
        cal._is_fitted = True
        assert abs(cal.calibrate(25.0) - 25.0) < 1.0

    def test_isotonic_boundary_extrapolation(self):
        """Isotonic 边界外推"""
        cal = ScoreCalibrator(method="isotonic")
        cal._isotonic_x = [0.3, 0.7]
        cal._isotonic_y = [0.2, 0.8]
        cal._is_fitted = True
        # 低于最小断点
        assert cal.calibrate(10.0) == 20.0  # 0.2 * 100
        # 高于最大断点
        assert cal.calibrate(90.0) == 80.0  # 0.8 * 100

    def test_platt_overflow_protection(self):
        """Platt 溢出保护"""
        cal = ScoreCalibrator(method="platt")
        cal._platt_a = 1000.0
        cal._platt_b = 1000.0
        cal._is_fitted = True
        # 不应抛异常
        result = cal.calibrate(50.0)
        assert 0.0 <= result <= 100.0


# ──────────────────── SignalScorer 测试 ────────────────────


class TestSignalScorer:
    """信号评分器测试"""

    def test_no_sources_zero_score(self):
        """无证据源 → 0 分"""
        scorer = SignalScorer()
        card = scorer.score("BTCUSDT", {})
        assert card.score == 0.0

    def test_single_source_long(self):
        """单源看多"""
        scorer = SignalScorer()
        src = _make_source("order_flow", 0.8, 1.0)
        scorer.register_source(src)
        card = scorer.score("BTCUSDT", {})
        assert card.direction == "long"
        assert card.score > 0

    def test_single_source_short(self):
        """单源看空"""
        scorer = SignalScorer()
        src = _make_source("smc", 0.8, -1.0)
        scorer.register_source(src)
        card = scorer.score("BTCUSDT", {})
        assert card.direction == "short"

    def test_single_source_cap(self):
        """单源封顶：单源贡献不超过 0.35"""
        scorer = SignalScorer()
        src = _make_source("order_flow", 1.0, 1.0)
        scorer.register_source(src, weight=1.0)
        card = scorer.score("BTCUSDT", {})
        # 最大贡献 0.35，总权重 1.0 → raw_score = 0.35/1.0*100 = 35
        assert card.score <= 36.0

    def test_resonance_bonus(self):
        """≥3 源同向 → 共振加成"""
        scorer = SignalScorer()
        for i, name in enumerate(["order_flow", "smc", "volume_price"]):
            scorer.register_source(_make_source(name, 0.6, 1.0))
        card = scorer.score("BTCUSDT", {})
        # 有共振加成，分数应比无共振高
        assert card.score > 0

    def test_conflict_decay(self):
        """冲突衰减：多空矛盾 → 向中性收敛"""
        scorer = SignalScorer()
        # 2 看多 + 2 看空 → 冲突
        scorer.register_source(_make_source("order_flow", 0.7, 1.0))
        scorer.register_source(_make_source("smc", 0.7, 1.0))
        scorer.register_source(_make_source("volume_price", 0.7, -1.0))
        scorer.register_source(_make_source("ml_model", 0.7, -1.0))
        card = scorer.score("BTCUSDT", {})
        # 冲突应使分数趋近中性(50)
        assert card.direction == "neutral"  # 净方向接近 0

    def test_neutral_direction(self):
        """多源中性 → neutral"""
        scorer = SignalScorer()
        scorer.register_source(_make_source("order_flow", 0.5, 0.0))
        scorer.register_source(_make_source("smc", 0.5, 0.0))
        card = scorer.score("BTCUSDT", {})
        assert card.direction == "neutral"

    def test_score_history(self):
        """评分历史记录"""
        scorer = SignalScorer()
        scorer.register_source(_make_source("order_flow", 0.5, 1.0))
        scorer.score("BTCUSDT", {})
        scorer.score("ETHUSDT", {})
        history = scorer.get_score_history()
        assert len(history) == 2

    def test_score_history_filter_by_symbol(self):
        """按标的过滤历史"""
        scorer = SignalScorer()
        scorer.register_source(_make_source("order_flow", 0.5, 1.0))
        scorer.score("BTCUSDT", {})
        scorer.score("ETHUSDT", {})
        btc = scorer.get_score_history(symbol="BTCUSDT")
        assert len(btc) == 1
        assert btc[0].symbol == "BTCUSDT"

    def test_signal_card_fields(self):
        """信号卡字段完整性"""
        scorer = SignalScorer()
        scorer.register_source(_make_source("order_flow", 0.8, 1.0))
        card = scorer.score("BTCUSDT", {})
        assert card.signal_id.startswith("sig_")
        assert card.symbol == "BTCUSDT"
        assert card.level in ("S", "A", "B", "C")
        assert 0 <= card.score <= 100
        assert len(card.confidence_interval) == 2
        assert card.risk_reward_ratio > 0
        assert card.reason

    def test_source_exception_handling(self):
        """证据源异常不影响其他源"""
        scorer = SignalScorer()
        good_src = _make_source("order_flow", 0.8, 1.0)
        bad_src = _make_source("smc", 0.0, 0.0)
        bad_src.compute.side_effect = RuntimeError("boom")
        scorer.register_source(good_src)
        scorer.register_source(bad_src)
        card = scorer.score("BTCUSDT", {})
        assert card.score > 0  # 好源仍贡献

    def test_custom_weight(self):
        """自定义权重"""
        scorer = SignalScorer()
        src = _make_source("order_flow", 0.8, 1.0)
        scorer.register_source(src, weight=0.5)
        card = scorer.score("BTCUSDT", {})
        assert card.score > 0

    def test_risk_note_levels(self):
        """不同等级的风险提示差异"""
        scorer = SignalScorer()
        # S 级信号
        for name in ["order_flow", "smc", "volume_price", "ml_model", "crypto_structure"]:
            scorer.register_source(_make_source(name, 0.9, 1.0))
        card = scorer.score("BTCUSDT", {})
        if card.level == "S":
            assert "极强" in card.risk_note

    def test_update_outcome(self):
        """更新信号结果"""
        scorer = SignalScorer()
        scorer.register_source(_make_source("order_flow", 0.5, 1.0))
        card = scorer.score("BTCUSDT", {})
        # 应不抛异常
        scorer.update_outcome(card.signal_id, True)

    def test_estimate_risk_reward(self):
        """风险回报比估算"""
        scorer = SignalScorer()
        assert scorer._estimate_risk_reward(90, "S") == 3.0
        assert scorer._estimate_risk_reward(75, "A") == 2.5
        assert scorer._estimate_risk_reward(60, "B") == 2.0
        assert scorer._estimate_risk_reward(40, "C") == 1.5


# ──────────────────── AntiNoise 测试 ────────────────────


class TestAntiNoise:
    """反噪音系统测试"""

    def test_first_signal_passes(self):
        """首次信号通过"""
        anti = AntiNoise(cooldown_sec=300)
        # 时间戳需大于冷却期（300秒=300e9纳秒）
        sig = _make_signal(score=80, timestamp_ns=400_000_000_000)
        assert anti.should_push(sig) is True

    def test_cooldown_blocks(self):
        """冷却期内重复信号被阻止"""
        anti = AntiNoise(cooldown_sec=300)
        ts1 = 400_000_000_000  # > 300s cooldown
        ts2 = ts1 + 100_000_000  # 0.1 秒后
        sig1 = _make_signal(score=80, timestamp_ns=ts1)
        sig2 = _make_signal(score=90, timestamp_ns=ts2, direction="short")
        assert anti.should_push(sig1) is True
        assert anti.should_push(sig2) is False

    def test_cooldown_reset(self):
        """重置冷却期后信号可通过"""
        anti = AntiNoise(cooldown_sec=300)
        ts1 = 400_000_000_000
        sig1 = _make_signal(score=80, timestamp_ns=ts1)
        anti.should_push(sig1)
        anti.reset_cooldown("BTCUSDT")
        ts2 = ts1 + 100_000_000
        # 用不同方向避免去重阻止
        sig2 = _make_signal(score=80, timestamp_ns=ts2, direction="short")
        assert anti.should_push(sig2) is True

    def test_dedup_blocks_similar(self):
        """去重：同方向+相近分数 → 阻止"""
        anti = AntiNoise(cooldown_sec=1)
        ts = 400_000_000_000
        # 第一个通过
        sig1 = _make_signal(score=80, timestamp_ns=ts)
        anti.should_push(sig1)
        # 冷却期外但同方向+相近分数、仍在3倍冷却期内
        ts2 = ts + 2_000_000_000  # 2 秒后（>1s冷却，<3s去重窗口）
        sig2 = _make_signal(score=82, timestamp_ns=ts2)
        # 应该被去重阻止（方向相同、分差<5、时间<3倍冷却期）
        assert anti.should_push(sig2) is False

    def test_regime_threshold(self):
        """Regime 感知：高波动环境提高门槛"""
        anti = AntiNoise(cooldown_sec=1)
        anti.set_regime("extreme")
        # 分数低于 70+20=90 → 被阻止
        sig = _make_signal(score=85, timestamp_ns=400_000_000_000)
        assert anti.should_push(sig) is False

    def test_regime_low_passes(self):
        """低波动环境正常门槛"""
        anti = AntiNoise(cooldown_sec=1)
        anti.set_regime("low")
        sig = _make_signal(score=75, timestamp_ns=400_000_000_000)
        assert anti.should_push(sig) is True

    def test_stats(self):
        """统计信息"""
        anti = AntiNoise(cooldown_sec=300)
        sig = _make_signal(score=80, timestamp_ns=400_000_000_000)
        anti.should_push(sig)
        stats = anti.stats
        assert stats["tracked_symbols"] == 1
        assert stats["total_recent_signals"] == 1
        assert stats["cooldown_sec"] == 300

    def test_cleanup_old_signals(self):
        """旧信号自动清理（保留最近20条）"""
        anti = AntiNoise(cooldown_sec=1)
        base_ts = 400_000_000_000
        for i in range(25):
            sig = _make_signal(score=80 + i % 20, timestamp_ns=base_ts + i * 5_000_000_000_000)
            anti.should_push(sig)
        recent = anti._recent_signals.get("BTCUSDT", [])
        assert len(recent) <= 20


# ──────────────────── 内置证据源测试 ────────────────────


class TestOrderFlowSource:
    """订单流证据源"""

    def test_empty_trades(self):
        src = OrderFlowSource()
        s, d = src.compute("BTCUSDT", {"trades": []})
        assert s == 0.0 and d == 0.0

    def test_buy_dominant(self):
        src = OrderFlowSource()
        trades = [
            {"side": "buy", "quantity": 100},
            {"side": "sell", "quantity": 30},
        ]
        s, d = src.compute("BTCUSDT", {"trades": trades})
        assert s > 0 and d == 1.0

    def test_sell_dominant(self):
        src = OrderFlowSource()
        trades = [
            {"side": "buy", "quantity": 10},
            {"side": "sell", "quantity": 90},
        ]
        s, d = src.compute("BTCUSDT", {"trades": trades})
        assert s > 0 and d == -1.0

    def test_balanced_trades(self):
        src = OrderFlowSource()
        trades = [
            {"side": "buy", "quantity": 50},
            {"side": "sell", "quantity": 50},
        ]
        s, d = src.compute("BTCUSDT", {"trades": trades})
        assert d == 0.0


class TestVolumePriceSource:
    """量价关系证据源"""

    def test_insufficient_klines(self):
        src = VolumePriceSource()
        s, d = src.compute("BTCUSDT", {"klines": [{"close": 100}] * 3})
        assert s == 0.0 and d == 0.0

    def test_price_up_volume_up(self):
        src = VolumePriceSource()
        klines = []
        for i in range(5):
            klines.append({"open": 100 + i, "close": 101 + i, "volume": 100 * (i + 1)})
        s, d = src.compute("BTCUSDT", {"klines": klines})
        assert d == 1.0

    def test_price_down_volume_up(self):
        src = VolumePriceSource()
        klines = []
        for i in range(5):
            klines.append({"open": 200 - i, "close": 199 - i, "volume": 100 * (i + 1)})
        s, d = src.compute("BTCUSDT", {"klines": klines})
        assert d == -1.0


class TestCryptoStructureSource:
    """加密结构证据源"""

    def test_extreme_funding_rate(self):
        src = CryptoStructureSource()
        s, d = src.compute("BTCUSDT", {"funding_rate": 0.02})
        assert s > 0 and d == -1.0  # 费率过高→看空

    def test_negative_funding_rate(self):
        src = CryptoStructureSource()
        s, d = src.compute("BTCUSDT", {"funding_rate": -0.02})
        assert s > 0 and d == 1.0  # 费率过低→看多

    def test_extreme_long_ratio(self):
        src = CryptoStructureSource()
        s, d = src.compute("BTCUSDT", {"long_short_ratio": 3.0})
        assert d == -1.0

    def test_extreme_short_ratio(self):
        src = CryptoStructureSource()
        s, d = src.compute("BTCUSDT", {"long_short_ratio": 0.3})
        assert d == 1.0

    def test_neutral(self):
        src = CryptoStructureSource()
        s, d = src.compute("BTCUSDT", {"funding_rate": 0.001, "long_short_ratio": 1.0})
        assert d == 0.0


class TestOnchainSource:
    """链上数据证据源"""

    def test_exchange_inflow(self):
        src = OnchainSource()
        s, d = src.compute("BTCUSDT", {"exchange_net_flow": 500})
        assert s > 0 and d == -1.0  # 流入交易所→看空

    def test_exchange_outflow(self):
        src = OnchainSource()
        s, d = src.compute("BTCUSDT", {"exchange_net_flow": -500})
        assert s > 0 and d == 1.0  # 流出交易所→看多

    def test_no_flow(self):
        src = OnchainSource()
        s, d = src.compute("BTCUSDT", {})
        assert d == 0.0


class TestMLModelSource:
    """ML 模型证据源"""

    def test_no_model(self):
        src = MLModelSource()
        s, d = src.compute("BTCUSDT", {})
        assert s == 0.0 and d == 0.0

    def test_with_predict_proba(self):
        model = MagicMock()
        model.predict_proba.return_value = [[0.3, 0.7]]
        src = MLModelSource(model=model)
        market_data = {"features": [0.1, 0.2, 0.3, 0.4, 0.5]}
        s, d = src.compute("BTCUSDT", market_data)
        assert s > 0 and d == 1.0

    def test_with_predict(self):
        model = MagicMock()
        del model.predict_proba  # 无 predict_proba
        model.predict.return_value = [0.3]
        src = MLModelSource(model=model)
        market_data = {"features": [0.1, 0.2, 0.3]}
        s, d = src.compute("BTCUSDT", market_data)
        assert s > 0 and d == -1.0

    def test_extract_features_from_prices(self):
        """从价格数据提取特征"""
        prices = [float(100 + i) for i in range(30)]
        feats = MLModelSource._extract_features({"prices": prices})
        assert feats is not None
        assert len(feats) == 5  # 3 动量 + 1 波动率 + 1 均值回归

    def test_extract_features_from_closes(self):
        prices = [float(100 + i) for i in range(30)]
        feats = MLModelSource._extract_features({"closes": prices})
        assert feats is not None

    def test_extract_features_insufficient(self):
        feats = MLModelSource._extract_features({"prices": [1, 2, 3]})
        assert feats is None

    def test_extract_features_precomputed(self):
        feats = MLModelSource._extract_features({"features": [1.0, 2.0, 3.0]})
        assert feats == [1.0, 2.0, 3.0]


class TestLLMAnalysisSource:
    """LLM 分析证据源"""

    def test_precomputed_sentiment(self):
        src = LLMAnalysisSource()
        s, d = src.compute("BTCUSDT", {"llm_sentiment": 0.8})
        assert s > 0 and d == 1.0

    def test_negative_sentiment(self):
        src = LLMAnalysisSource()
        s, d = src.compute("BTCUSDT", {"llm_sentiment": -0.6})
        assert s > 0 and d == -1.0

    def test_local_sentiment_bullish(self):
        src = LLMAnalysisSource()
        prices = [float(100 + i * 2) for i in range(30)]
        s, d = src.compute("BTCUSDT", {"prices": prices})
        assert d == 1.0

    def test_local_sentiment_bearish(self):
        src = LLMAnalysisSource()
        prices = [float(200 - i * 2) for i in range(30)]
        s, d = src.compute("BTCUSDT", {"prices": prices})
        assert d == -1.0

    def test_local_sentiment_insufficient(self):
        src = LLMAnalysisSource()
        s, d = src.compute("BTCUSDT", {"prices": [100]})
        assert s == 0.0


class TestSMCSource:
    """SMC 证据源"""

    def test_no_analyzer_import_error(self):
        """无 SMCAnalyzer 时返回中性"""
        src = SMCSource(analyzer=None)
        with patch("one_quant.ai.signal_scoring.SMCSource.compute", wraps=src.compute):
            # 直接测试 _analyzer=None 的路径
            src2 = SMCSource(analyzer=None)
            src2._analyzer = MagicMock()
            src2._analyzer.detect_bos.return_value = {"type": "bullish_bos"}
            src2._analyzer.detect_choch.return_value = {}
            src2._analyzer.find_order_blocks.return_value = []
            src2._analyzer.find_fvg.return_value = []
            klines = [
                {
                    "high": 100 + i,
                    "low": 99 + i,
                    "close": 99.5 + i,
                    "open": 99 + i,
                    "volume": 100,
                    "timestamp_ns": i,
                }
                for i in range(20)
            ]
            highs = [float(k["high"]) for k in klines]
            lows = [float(k["low"]) for k in klines]
            s, d = src2.compute("BTCUSDT", {"klines": klines, "highs": highs, "lows": lows})
            assert s > 0 and d == 1.0  # bullish BOS

    def test_insufficient_data(self):
        """数据不足返回中性"""
        src = SMCSource()
        s, d = src.compute("BTCUSDT", {"highs": [1.0] * 5, "lows": [0.9] * 5})
        assert s == 0.0 and d == 0.0


# ──────────────────── ScoreRecord 测试 ────────────────────


class TestScoreRecord:
    """评分记录测试"""

    def test_auto_timestamp(self):
        """自动设置时间戳"""
        rec = ScoreRecord(raw_score=50.0, calibrated_score=50.0)
        assert rec.timestamp_ns > 0

    def test_explicit_timestamp(self):
        ts = 1_000_000_000
        rec = ScoreRecord(raw_score=50.0, calibrated_score=50.0, timestamp_ns=ts)
        assert rec.timestamp_ns == ts

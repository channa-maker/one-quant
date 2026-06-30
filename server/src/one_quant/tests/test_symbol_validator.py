"""Tests for data/symbol_validator.py — 标的上线校验"""

from decimal import Decimal

import pytest

from one_quant.core.types import Instrument, InstrumentType, Market
from one_quant.data.symbol_validator import SymbolValidator, ValidationResult


@pytest.fixture
def validator():
    return SymbolValidator(
        min_daily_volume_usd=Decimal("100000"),
        max_spread_pct=Decimal("0.02"),
        min_history_days=30,
    )


@pytest.fixture
def good_instrument():
    return Instrument(
        internal_id="btc-binance",
        symbol="BTC/USDT",
        market=Market.SPOT,
        instrument_type=InstrumentType.SPOT,
        exchange="binance",
        base_currency="BTC",
        quote_currency="USDT",
        tick_size=Decimal("0.01"),
        lot_size=Decimal("0.001"),
        is_active=True,
    )


@pytest.fixture
def good_market_data():
    return {
        "daily_volume_usd": 5000000,
        "spread_pct": 0.001,
        "history_days": 90,
    }


# ── All checks pass ────────────────────────────────────────────


class TestValidationPass:
    def test_all_checks_pass(self, validator, good_instrument, good_market_data):
        result = validator.validate(good_instrument, good_market_data)
        assert result.passed is True
        assert all(result.checks.values())
        assert result.reasons == []

    def test_timestamp_auto_populated(self, validator, good_instrument, good_market_data):
        result = validator.validate(good_instrument, good_market_data)
        assert result.timestamp_ns > 0


# ── Liquidity checks ───────────────────────────────────────────


class TestLiquidityChecks:
    def test_low_volume_fails(self, validator, good_instrument):
        data = {"daily_volume_usd": 1000, "spread_pct": 0.001, "history_days": 90}
        result = validator.validate(good_instrument, data)
        assert result.passed is False
        assert result.checks["liquidity_volume"] is False
        assert any("成交额" in r for r in result.reasons)

    def test_high_spread_fails(self, validator, good_instrument):
        data = {"daily_volume_usd": 5000000, "spread_pct": 0.1, "history_days": 90}
        result = validator.validate(good_instrument, data)
        assert result.passed is False
        assert result.checks["liquidity_spread"] is False
        assert any("价差" in r for r in result.reasons)

    def test_no_market_data_fails_liquidity(self, validator, good_instrument):
        result = validator.validate(good_instrument, None)
        assert result.passed is False
        assert result.checks["liquidity_volume"] is False
        assert result.checks["liquidity_spread"] is False
        assert any("缺少市场数据" in r for r in result.reasons)


# ── Data checks ────────────────────────────────────────────────


class TestDataChecks:
    def test_insufficient_history(self, validator, good_instrument):
        data = {"daily_volume_usd": 5000000, "spread_pct": 0.001, "history_days": 5}
        result = validator.validate(good_instrument, data)
        assert result.checks["data_history"] is False
        assert any("历史数据" in r for r in result.reasons)

    def test_no_market_data_fails_history(self, validator, good_instrument):
        result = validator.validate(good_instrument, None)
        assert result.checks["data_history"] is False


# ── Risk checks ────────────────────────────────────────────────


class TestRiskChecks:
    def test_blacklisted_instrument_fails(self, validator, good_instrument, good_market_data):
        validator.add_to_blacklist("btc-binance")
        result = validator.validate(good_instrument, good_market_data)
        assert result.passed is False
        assert result.checks["risk_blacklist"] is False
        assert any("黑名单" in r for r in result.reasons)

    def test_remove_from_blacklist(self, validator, good_instrument, good_market_data):
        validator.add_to_blacklist("btc-binance")
        validator.remove_from_blacklist("btc-binance")
        result = validator.validate(good_instrument, good_market_data)
        assert result.checks["risk_blacklist"] is True


# ── Compliance checks ──────────────────────────────────────────


class TestComplianceChecks:
    def test_inactive_instrument_fails(self, validator, good_market_data):
        inactive = Instrument(
            internal_id="dead-coin",
            symbol="DEAD/USDT",
            market=Market.SPOT,
            instrument_type=InstrumentType.SPOT,
            exchange="binance",
            base_currency="DEAD",
            quote_currency="USDT",
            tick_size=Decimal("0.01"),
            lot_size=Decimal("1"),
            is_active=False,
        )
        result = validator.validate(inactive, good_market_data)
        assert result.passed is False
        assert result.checks["compliance_active"] is False
        assert any("下架" in r for r in result.reasons)


# ── Blacklist management ───────────────────────────────────────


class TestBlacklistManagement:
    def test_add_and_check(self, validator):
        validator.add_to_blacklist("scam-token")
        assert "scam-token" in validator._blacklist

    def test_remove_nonexistent_is_safe(self, validator):
        # discard doesn't raise
        validator.remove_from_blacklist("nonexistent")

    def test_add_idempotent(self, validator):
        validator.add_to_blacklist("x")
        validator.add_to_blacklist("x")
        assert len(validator._blacklist) == 1


# ── ValidationResult ───────────────────────────────────────────


class TestValidationResult:
    def test_defaults(self):
        r = ValidationResult(passed=True)
        assert r.checks == {}
        assert r.reasons == []
        assert r.timestamp_ns > 0

    def test_custom_timestamp(self):
        r = ValidationResult(passed=False, timestamp_ns=12345)
        assert r.timestamp_ns == 12345

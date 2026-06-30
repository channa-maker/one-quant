"""配置体系单元测试"""

from __future__ import annotations

import pytest

from one_quant.infra.config import (
    AISettings,
    DatabaseSettings,
    ExchangeSettings,
    RedisSettings,
    RiskSettings,
    Settings,
)


class TestDatabaseSettings:
    def test_defaults(self) -> None:
        settings = DatabaseSettings()
        assert "postgresql" in settings.DATABASE_URL
        assert "localhost" in settings.DATABASE_URL


class TestRedisSettings:
    def test_defaults(self) -> None:
        settings = RedisSettings()
        assert "redis://" in settings.REDIS_URL


class TestAISettings:
    def test_default_budget(self) -> None:
        settings = AISettings()
        assert settings.LLM_DAILY_BUDGET_USD == 50.0

    def test_negative_budget_raises(self) -> None:
        with pytest.raises(Exception):
            AISettings(LLM_DAILY_BUDGET_USD=-1)

    def test_default_provider(self) -> None:
        settings = AISettings()
        assert settings.AGENT_PROVIDER == "deepseek"


class TestRiskSettings:
    def test_hardcoded_values(self) -> None:
        settings = RiskSettings()
        assert settings.MAX_DRAWDOWN_PCT == 0.15
        assert settings.MAX_LEVERAGE_CRYPTO == 20
        assert settings.MAX_LEVERAGE_STOCKS == 4
        assert settings.MAX_SINGLE_POSITION_PCT == 0.10


class TestExchangeSettings:
    def test_defaults_none(self) -> None:
        settings = ExchangeSettings()
        assert settings.BINANCE_API_KEY is None
        assert settings.OKX_API_KEY is None


class TestSettings:
    def test_default_env(self) -> None:
        settings = Settings()
        assert settings.ENV == "dev"

    def test_sub_configs(self) -> None:
        settings = Settings()
        assert isinstance(settings.database, DatabaseSettings)
        assert isinstance(settings.redis, RedisSettings)
        assert isinstance(settings.exchange, ExchangeSettings)
        assert isinstance(settings.ai, AISettings)
        assert isinstance(settings.risk, RiskSettings)

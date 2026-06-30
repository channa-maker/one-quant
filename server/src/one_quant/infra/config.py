"""
ONE量化 - 配置体系

使用 pydantic-settings 实现基于环境变量的分层配置。
环境变量前缀: SMARTQUANT_ / ONE_
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """数据库连接配置"""

    model_config = SettingsConfigDict(
        env_prefix="SMARTQUANT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str = "postgresql+asyncpg://localhost:5432/one_quant"
    TIMESCALE_URL: str = "postgresql+asyncpg://localhost:5432/timescale"
    CLICKHOUSE_URL: str = "http://localhost:8123/one_quant"


class RedisSettings(BaseSettings):
    """Redis 连接配置"""

    model_config = SettingsConfigDict(
        env_prefix="SMARTQUANT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_PASSWORD: Optional[SecretStr] = None


class ExchangeSettings(BaseSettings):
    """交易所 API 密钥。

    所有密钥字段使用 SecretStr，不会在日志/序列化中泄露。
    """

    model_config = SettingsConfigDict(
        env_prefix="SMARTQUANT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    BINANCE_API_KEY: Optional[SecretStr] = None
    BINANCE_SECRET: Optional[SecretStr] = None
    OKX_API_KEY: Optional[SecretStr] = None
    OKX_SECRET: Optional[SecretStr] = None
    OKX_PASSPHRASE: Optional[SecretStr] = None
    DERIBIT_API_KEY: Optional[SecretStr] = None
    DERIBIT_SECRET: Optional[SecretStr] = None


class AISettings(BaseSettings):
    """AI 模型与代理配置。"""

    model_config = SettingsConfigDict(
        env_prefix="ONE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ANTHROPIC_API_KEY: Optional[SecretStr] = None
    DEEPSEEK_API_KEY: Optional[SecretStr] = None
    LLM_DAILY_BUDGET_USD: float = 50.0
    AGENT_PROVIDER: str = "deepseek"

    @field_validator("LLM_DAILY_BUDGET_USD")
    @classmethod
    def _validate_budget(cls, v: float) -> float:
        if v < 0:
            raise ValueError("LLM_DAILY_BUDGET_USD 不能为负数")
        return v


class RiskSettings(BaseSettings):
    """风控硬编码阈值常量。

    这些值在代码中固定，不从环境变量读取。
    """

    model_config = SettingsConfigDict(extra="ignore")

    MAX_DRAWDOWN_PCT: float = 0.15
    MAX_LEVERAGE_CRYPTO: int = 20
    MAX_LEVERAGE_STOCKS: int = 4
    MAX_SINGLE_POSITION_PCT: float = 0.10


class Settings(BaseSettings):
    """全局配置。"""

    model_config = SettingsConfigDict(
        env_prefix="ONE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ENV: str = "dev"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24

    database: DatabaseSettings = DatabaseSettings()
    redis: RedisSettings = RedisSettings()
    exchange: ExchangeSettings = ExchangeSettings()
    ai: AISettings = AISettings()
    risk: RiskSettings = RiskSettings()


@lru_cache
def get_settings() -> Settings:
    """获取全局配置（单例）。"""
    return Settings()

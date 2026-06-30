"""
ONE量化 - 配置体系

使用 pydantic-settings 实现基于环境变量的分层配置。
环境变量前缀: SMARTQUANT_ / ONE_
"""

from __future__ import annotations

import sys
from functools import lru_cache
from typing import Optional

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# 子配置: 数据库
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# 子配置: Redis
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# 子配置: 交易所密钥
# ---------------------------------------------------------------------------
class ExchangeSettings(BaseSettings):
    """
    交易所 API 密钥。

    启动时校验: 如果启用了对应交易所，则相关密钥不能为空。
    所有密钥字段使用 SecretStr，不会在日志/序列化中泄露。
    """

    model_config = SettingsConfigDict(
        env_prefix="SMARTQUANT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- Binance ----
    BINANCE_API_KEY: Optional[SecretStr] = None
    BINANCE_SECRET: Optional[SecretStr] = None

    # ---- OKX ----
    OKX_API_KEY: Optional[SecretStr] = None
    OKX_SECRET: Optional[SecretStr] = None
    OKX_PASSPHRASE: Optional[SecretStr] = None

    # ---- Deribit ----
    DERIBIT_API_KEY: Optional[SecretStr] = None
    DERIBIT_SECRET: Optional[SecretStr] = None


# ---------------------------------------------------------------------------
# 子配置: AI / LLM
# ---------------------------------------------------------------------------
class AISettings(BaseSettings):
    """
    AI 模型与代理配置。

    LLM_DAILY_BUDGET_USD: 每日 LLM 调用预算（美元），超出则熔断。
    AGENT_PROVIDER: 代理提供商标识 (anthropic / deepseek / ...)。
    """

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


# ---------------------------------------------------------------------------
# 子配置: 风控硬编码阈值
# ---------------------------------------------------------------------------
class RiskSettings(BaseSettings):
    """
    风控硬编码阈值常量。

    这些值在代码中固定，不从环境变量读取，防止运行时被意外篡改。
    修改需走代码审查流程。
    """

    model_config = SettingsConfigDict(
        extra="ignore",
    )

    # 最大回撤比例 (15%)
    MAX_DRAWDOWN_PCT: float = 0.15
    # 加密货币最大杠杆倍数
    MAX_LEVERAGE_CRYPTO: int = 20
    # 股票最大杠杆倍数
    MAX_LEVERAGE_STOCKS: int = 4
    # 单一持仓占总资产最大比例 (10%)
    MAX_SINGLE_POSITION_PCT: float = 0.10


# ---------------------------------------------------------------------------
# 顶层聚合配置
# ---------------------------------------------------------------------------
class Settings(BaseSettings):
    """
    顶层配置聚合，将所有子配置组合为单一入口。

    使用方式::

        settings = get_settings()
        db_url = settings.database.DATABASE_URL
        max_dd = settings.risk.MAX_DRAWDOWN_PCT
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 运行环境: dev / staging / prod
    ENV: str = "dev"

    # 子配置实例
    database: DatabaseSettings = DatabaseSettings()
    redis: RedisSettings = RedisSettings()
    exchange: ExchangeSettings = ExchangeSettings()
    ai: AISettings = AISettings()
    risk: RiskSettings = RiskSettings()


# ---------------------------------------------------------------------------
# 启动校验
# ---------------------------------------------------------------------------
def _validate_required_keys(settings: Settings) -> None:
    """
    校验必需的密钥是否已配置。

    生产环境下，以下密钥必须存在:
    - 至少一个交易所的 API Key/Secret
    - 至少一个 LLM API Key

    缺失任一必需密钥时打印错误并拒绝启动。
    """
    errors: list[str] = []

    # ---- 检查交易所密钥 (prod 环境强制) ----
    if settings.ENV == "prod":
        has_binance = (
            settings.exchange.BINANCE_API_KEY is not None
            and settings.exchange.BINANCE_SECRET is not None
        )
        has_okx = (
            settings.exchange.OKX_API_KEY is not None
            and settings.exchange.OKX_SECRET is not None
            and settings.exchange.OKX_PASSPHRASE is not None
        )
        has_deribit = (
            settings.exchange.DERIBIT_API_KEY is not None
            and settings.exchange.DERIBIT_SECRET is not None
        )
        if not (has_binance or has_okx or has_deribit):
            errors.append(
                "生产环境至少需要配置一个交易所的完整密钥 "
                "(Binance / OKX / Deribit)"
            )

    # ---- 检查 LLM 密钥 ----
    has_anthropic = settings.ai.ANTHROPIC_API_KEY is not None
    has_deepseek = settings.ai.DEEPSEEK_API_KEY is not None
    if not (has_anthropic or has_deepseek):
        errors.append(
            "至少需要配置一个 LLM API Key "
            "(ANTHROPIC_API_KEY / DEEPSEEK_API_KEY)"
        )

    # ---- 报错并退出 ----
    if errors:
        error_msg = "配置校验失败:\n" + "\n".join(f"  - {e}" for e in errors)
        print(error_msg, file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# 单例入口
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    获取全局配置单例。

    首次调用时创建 Settings 实例并执行启动校验，
    后续调用直接返回缓存实例。

    Returns:
        Settings: 全局配置对象
    """
    settings = Settings()
    _validate_required_keys(settings)
    return settings

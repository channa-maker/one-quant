"""
ONE量化 - 选股选币过滤器

一级过滤层：流动性 / 市值 / 上市时长 / 可交易性。
所有金额使用 Decimal 精确计算。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)


class BaseFilter(ABC):
    """过滤器基类"""

    @abstractmethod
    def filter(
        self,
        symbols: list[str],
        market_data: dict[str, Any],
    ) -> list[str]:
        """过滤标的列表。

        Args:
            symbols: 候选标的符号列表。
            market_data: 市场数据（ticker、市值等）。

        Returns:
            通过过滤的标的列表。
        """
        ...


class LiquidityFilter(BaseFilter):
    """流动性过滤器。

    剔除 24h 成交量低于阈值的标的，保证进入候选池的标的
    具有足够的流动性以支持实际交易。
    """

    def __init__(self, min_volume_24h: Decimal = Decimal("100000")) -> None:
        """初始化流动性过滤器。

        Args:
            min_volume_24h: 最小 24h 成交量（计价币种）。
        """
        self.min_volume_24h = min_volume_24h

    def filter(
        self,
        symbols: list[str],
        market_data: dict[str, Any],
    ) -> list[str]:
        """过滤流动性不足的标的。

        Args:
            symbols: 候选标的符号列表。
            market_data: 市场数据，每个标的需包含 volume_24h 字段。

        Returns:
            通过流动性阈值的标的列表。
        """
        result: list[str] = []
        for sym in symbols:
            ticker = market_data.get(sym, {})
            volume_str = str(ticker.get("volume_24h", "0"))
            volume = Decimal(volume_str)
            if volume >= self.min_volume_24h:
                result.append(sym)
            else:
                logger.debug(
                    "流动性过滤: %s 成交量 %s < 阈值 %s",
                    sym,
                    volume,
                    self.min_volume_24h,
                )
        logger.info(
            "流动性过滤: %d → %d 标的（阈值 %s）",
            len(symbols),
            len(result),
            self.min_volume_24h,
        )
        return result


class MarketCapFilter(BaseFilter):
    """市值过滤器。

    剔除市值低于阈值的标的，避免小市值标的的高波动和低流动性风险。
    """

    def __init__(self, min_market_cap: Decimal = Decimal("10000000")) -> None:
        """初始化市值过滤器。

        Args:
            min_market_cap: 最小市值（计价币种）。
        """
        self.min_market_cap = min_market_cap

    def filter(
        self,
        symbols: list[str],
        market_data: dict[str, Any],
    ) -> list[str]:
        """过滤市值不足的标的。

        Args:
            symbols: 候选标的符号列表。
            market_data: 市场数据，每个标的需包含 market_cap 字段。

        Returns:
            通过市值阈值的标的列表。
        """
        result: list[str] = []
        for sym in symbols:
            ticker = market_data.get(sym, {})
            cap_str = str(ticker.get("market_cap", "0"))
            cap = Decimal(cap_str)
            if cap >= self.min_market_cap:
                result.append(sym)
            else:
                logger.debug(
                    "市值过滤: %s 市值 %s < 阈值 %s",
                    sym,
                    cap,
                    self.min_market_cap,
                )
        logger.info(
            "市值过滤: %d → %d 标的（阈值 %s）",
            len(symbols),
            len(result),
            self.min_market_cap,
        )
        return result


class ListingAgeFilter(BaseFilter):
    """上市时长过滤器。

    剔除上市时间过短的标的，避免新上市标的的价格剧烈波动和数据不足问题。
    """

    def __init__(self, min_days: int = 30) -> None:
        """初始化上市时长过滤器。

        Args:
            min_days: 最小上市天数。
        """
        self.min_days = min_days

    def filter(
        self,
        symbols: list[str],
        market_data: dict[str, Any],
    ) -> list[str]:
        """过滤上市时长不足的标的。

        Args:
            symbols: 候选标的符号列表。
            market_data: 市场数据，每个标的需包含 listing_date 字段
                         （ISO 格式日期字符串或 Unix 时间戳）。

        Returns:
            通过上市时长阈值的标的列表。
        """
        now = datetime.now(timezone.utc)
        result: list[str] = []
        for sym in symbols:
            ticker = market_data.get(sym, {})
            listing_date_raw = ticker.get("listing_date")
            if listing_date_raw is None:
                # 无上市日期信息，默认通过
                result.append(sym)
                continue

            try:
                if isinstance(listing_date_raw, (int, float)):
                    # Unix 时间戳（秒）
                    listed_dt = datetime.fromtimestamp(
                        listing_date_raw, tz=timezone.utc
                    )
                else:
                    # ISO 格式日期字符串
                    listed_dt = datetime.fromisoformat(str(listing_date_raw))
                    if listed_dt.tzinfo is None:
                        listed_dt = listed_dt.replace(tzinfo=timezone.utc)
                age_days = (now - listed_dt).days
            except (ValueError, TypeError, OSError):
                logger.warning(
                    "上市时长过滤: %s 日期格式异常 %r，默认通过",
                    sym,
                    listing_date_raw,
                )
                result.append(sym)
                continue

            if age_days >= self.min_days:
                result.append(sym)
            else:
                logger.debug(
                    "上市时长过滤: %s 上市 %d 天 < 阈值 %d 天",
                    sym,
                    age_days,
                    self.min_days,
                )
        logger.info(
            "上市时长过滤: %d → %d 标的（阈值 %d 天）",
            len(symbols),
            len(result),
            self.min_days,
        )
        return result


class TradabilityFilter(BaseFilter):
    """可交易性过滤器。

    剔除不可交易的标的（停牌、退市、暂停交易等）。
    """

    def filter(
        self,
        symbols: list[str],
        market_data: dict[str, Any],
    ) -> list[str]:
        """过滤不可交易的标的。

        Args:
            symbols: 候选标的符号列表。
            market_data: 市场数据，每个标的需包含 is_tradable 字段（bool）。

        Returns:
            可交易的标的列表。
        """
        result: list[str] = []
        for sym in symbols:
            ticker = market_data.get(sym, {})
            is_tradable = ticker.get("is_tradable", True)
            if is_tradable:
                result.append(sym)
            else:
                logger.debug("可交易性过滤: %s 不可交易", sym)
        logger.info("可交易性过滤: %d → %d 标的", len(symbols), len(result))
        return result

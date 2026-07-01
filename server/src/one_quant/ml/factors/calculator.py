"""
因子库 — 批量计算接口与因子库管理器
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from one_quant.ml.factors.flow import FlowCVDFactor, FlowFundingRateFactor, FlowLargeOrderNetFactor
from one_quant.ml.factors.momentum import (
    MomentumBreakoutFactor,
    MomentumMACDFactor,
    MomentumRSIFactor,
)
from one_quant.ml.factors.protocols import _safe_decimal, _safe_float
from one_quant.ml.factors.sentiment import EventCalendarProximityFactor, SentimentScoreFactor
from one_quant.ml.factors.volatility import VolatilityATRFactor, VolatilityRealizedFactor


class FactorCalculator:
    """因子计算器 — 统一入口，供 ML 管线调用。

    组合所有因子类，提供批量计算接口。
    """

    def __init__(self) -> None:
        self._momentum_rsi = MomentumRSIFactor()
        self._momentum_macd = MomentumMACDFactor()
        self._momentum_breakout = MomentumBreakoutFactor()
        self._flow_cvd = FlowCVDFactor()
        self._flow_funding = FlowFundingRateFactor()
        self._flow_large_order = FlowLargeOrderNetFactor()
        self._volatility_atr = VolatilityATRFactor()
        self._volatility_realized = VolatilityRealizedFactor()
        self._sentiment = SentimentScoreFactor()
        self._event_proximity = EventCalendarProximityFactor()

    def momentum_rsi(self, prices: list[Decimal], period: int = 14) -> float | None:
        """RSI 动量因子。"""
        return MomentumRSIFactor(period).compute(prices)

    def momentum_macd(
        self, prices: list[Decimal], fast: int = 12, slow: int = 26, signal: int = 9
    ) -> dict[str, float | None]:
        """MACD 因子。"""
        return MomentumMACDFactor(fast, slow, signal).compute(prices)

    def momentum_breakout(self, prices: list[Decimal], window: int = 20) -> float | None:
        """突破强度因子。"""
        return MomentumBreakoutFactor(window).compute(prices)

    def flow_cvd(self, trades: list[dict[str, Any]]) -> Decimal | None:
        """累计成交量差 CVD。"""
        return self._flow_cvd.compute(trades)

    def flow_funding_rate(self, rate: Decimal) -> float | None:
        """资金费率因子。"""
        return self._flow_funding.compute(rate)

    def flow_large_order_net(
        self, trades: list[dict[str, Any]], threshold: Decimal
    ) -> Decimal | None:
        """大单净流入。"""
        return self._flow_large_order.compute(trades, threshold)

    def volatility_atr(
        self,
        highs: list[Decimal],
        lows: list[Decimal],
        closes: list[Decimal],
        period: int = 14,
    ) -> Decimal | None:
        """ATR 波动因子。"""
        return VolatilityATRFactor(period).compute(highs, lows, closes)

    def volatility_realized(self, returns: list[Decimal], window: int = 20) -> Decimal | None:
        """已实现波动率。"""
        return VolatilityRealizedFactor(window).compute(returns)

    def sentiment_score(self, news_texts: list[str]) -> float | None:
        """新闻情绪因子（-1 到 1）。"""
        return self._sentiment.compute(news_texts)

    def event_calendar_proximity(self, event_date: int, current_date: int) -> float | None:
        """事件日历临近度。"""
        return self._event_proximity.compute(event_date, current_date)

    def compute_all(self, market_data: dict[str, Any]) -> dict[str, float | None]:
        """从市场数据字典批量计算所有因子。

        Args:
            market_data: 市场数据，键包括：
                - prices: list[Decimal] — 收盘价
                - highs: list[Decimal] — 最高价
                - lows: list[Decimal] — 最低价
                - closes: list[Decimal] — 收盘价（别名）
                - returns: list[Decimal] — 收益率
                - trades: list[dict] — 交易数据
                - funding_rate: Decimal — 资金费率
                - news_texts: list[str] — 新闻文本
                - event_date: int — 事件日期
                - current_date: int — 当前日期

        Returns:
            因子名到因子值的映射，None 表示数据不足。
        """
        result: dict[str, float | None] = {}
        prices = market_data.get("prices") or market_data.get("closes", [])
        highs = market_data.get("highs", [])
        lows = market_data.get("lows", [])
        closes = market_data.get("closes") or prices
        returns = market_data.get("returns", [])
        trades = market_data.get("trades", [])
        funding_rate = market_data.get("funding_rate")
        news_texts = market_data.get("news_texts", [])
        event_date = market_data.get("event_date")
        current_date = market_data.get("current_date")
        large_order_threshold = market_data.get("large_order_threshold")

        # 动量因子
        if prices:
            result["momentum_rsi_14"] = self.momentum_rsi(prices, 14)
            result["momentum_rsi_7"] = self.momentum_rsi(prices, 7)
            macd = self.momentum_macd(prices)
            result["momentum_macd_12_26_9"] = macd.get("histogram")
            result["momentum_breakout_20"] = self.momentum_breakout(prices, 20)

        # 资金流因子
        if trades:
            cvd = self.flow_cvd(trades)
            result["flow_cvd"] = _safe_float(cvd)
            if large_order_threshold is not None:
                threshold = _safe_decimal(large_order_threshold) or Decimal("0")
                lon = self.flow_large_order_net(trades, threshold)
                result["flow_large_order_net"] = _safe_float(lon)

        if funding_rate is not None:
            result["flow_funding_rate"] = self.flow_funding_rate(
                _safe_decimal(funding_rate) or Decimal("0")
            )

        # 波动因子
        if highs and lows and closes:
            atr = self.volatility_atr(highs, lows, closes, 14)
            result["volatility_atr_14"] = _safe_float(atr)

        if returns:
            rv = self.volatility_realized(returns, 20)
            result["volatility_realized_20"] = _safe_float(rv)

        # 情绪因子
        if news_texts:
            result["sentiment_score"] = self.sentiment_score(news_texts)

        # 事件因子
        if event_date is not None and current_date is not None:
            result["event_calendar_proximity"] = self.event_calendar_proximity(
                event_date, current_date
            )

        return result


class FactorLibrary:
    """因子库管理器 — 注册、查询、批量计算。

    职责：
      - 管理因子元数据注册表
      - 统一调度因子计算
      - 支持因子的启用/禁用
    """

    def __init__(self) -> None:
        self._calculator = FactorCalculator()
        self._registry: dict[str, dict[str, Any]] = {}

    @property
    def calculator(self) -> FactorCalculator:
        """获取底层计算器。"""
        return self._calculator

    def register(self, name: str, category: str, description: str) -> None:
        """注册因子元数据。

        Args:
            name: 因子名称（遵循 {类别}_{名称}_{窗口} 规范）。
            category: 因子类别（momentum/flow/volatility/sentiment/event）。
            description: 因子描述。
        """
        self._registry[name] = {
            "name": name,
            "category": category,
            "description": description,
            "enabled": True,
        }

    def enable(self, name: str) -> None:
        """启用因子。"""
        if name in self._registry:
            self._registry[name]["enabled"] = True

    def disable(self, name: str) -> None:
        """禁用因子。"""
        if name in self._registry:
            self._registry[name]["enabled"] = False

    def compute_all(self, market_data: dict[str, Any]) -> dict[str, float | None]:
        """计算所有已注册且启用的因子。

        Args:
            market_data: 市场数据字典（参见 FactorCalculator.compute_all）。

        Returns:
            因子名到因子值的映射。
        """
        all_factors = self._calculator.compute_all(market_data)

        # 如果有注册表，过滤出已注册且启用的因子
        if self._registry:
            return {
                k: v
                for k, v in all_factors.items()
                if k in self._registry and self._registry[k].get("enabled", True)
            }

        # 未注册时返回全部
        return all_factors

    def get_factor_info(self, name: str) -> dict[str, Any] | None:
        """获取因子元数据。

        Args:
            name: 因子名称。

        Returns:
            因子元数据字典，不存在返回 None。
        """
        return self._registry.get(name)

    def list_factors(self, category: str | None = None) -> list[dict[str, Any]]:
        """列出所有已注册因子。

        Args:
            category: 可选，按类别过滤。

        Returns:
            因子元数据列表。
        """
        factors = list(self._registry.values())
        if category:
            factors = [f for f in factors if f["category"] == category]
        return factors

    def register_defaults(self) -> None:
        """注册默认因子集。"""
        defaults = [
            ("momentum_rsi_14", "momentum", "RSI 动量因子（14 周期）"),
            ("momentum_rsi_7", "momentum", "RSI 动量因子（7 周期）"),
            ("momentum_macd_12_26_9", "momentum", "MACD 动量因子"),
            ("momentum_breakout_20", "momentum", "突破强度因子（20 周期）"),
            ("flow_cvd", "flow", "累计成交量差 CVD"),
            ("flow_funding_rate", "flow", "资金费率因子"),
            ("flow_large_order_net", "flow", "大单净流入"),
            ("volatility_atr_14", "volatility", "ATR 波动因子（14 周期）"),
            ("volatility_realized_20", "volatility", "已实现波动率（20 周期）"),
            ("sentiment_score", "sentiment", "新闻情绪因子"),
            ("event_calendar_proximity", "event", "事件日历临近度"),
        ]
        for name, category, description in defaults:
            self.register(name, category, description)

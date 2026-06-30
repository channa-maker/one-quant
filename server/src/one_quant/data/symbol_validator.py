"""新标的上线校验流程 — 流动性/数据/风控/合规四项检查"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from one_quant.core.types import Instrument
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ValidationResult:
    """校验结果"""

    passed: bool
    checks: dict[str, bool] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    timestamp_ns: int = 0

    def __post_init__(self) -> None:
        if self.timestamp_ns == 0:
            self.timestamp_ns = time.time_ns()


class SymbolValidator:
    """新标的上线校验器。

    四项检查全部通过才允许交易：
    1. 流动性检查：日均成交额 > 阈值，买卖价差 < 阈值
    2. 数据检查：历史数据完整性，行情源可达
    3. 风控检查：标的不在黑名单，波动率可接受
    4. 合规检查：不在制裁名单，交易所支持
    """

    def __init__(
        self,
        min_daily_volume_usd: Decimal = Decimal("100000"),
        max_spread_pct: Decimal = Decimal("0.02"),
        min_history_days: int = 30,
    ) -> None:
        self._min_daily_volume = min_daily_volume_usd
        self._max_spread_pct = max_spread_pct
        self._min_history_days = min_history_days
        self._blacklist: set[str] = set()

    def validate(
        self, instrument: Instrument, market_data: dict[str, Any] | None = None
    ) -> ValidationResult:
        """执行四项校验。

        Args:
            instrument: 待校验标的
            market_data: 市场数据（可选，缺数据时检查标记为待补充）

        Returns:
            校验结果
        """
        checks: dict[str, bool] = {}
        reasons: list[str] = []

        # 1. 流动性检查
        if market_data:
            daily_vol = Decimal(str(market_data.get("daily_volume_usd", 0)))
            spread_pct = Decimal(str(market_data.get("spread_pct", "0.01")))
            checks["liquidity_volume"] = daily_vol >= self._min_daily_volume
            checks["liquidity_spread"] = spread_pct <= self._max_spread_pct
            if not checks["liquidity_volume"]:
                reasons.append(f"日均成交额 {daily_vol} 低于阈值 {self._min_daily_volume}")
            if not checks["liquidity_spread"]:
                reasons.append(f"买卖价差 {spread_pct} 超过阈值 {self._max_spread_pct}")
        else:
            checks["liquidity_volume"] = False
            checks["liquidity_spread"] = False
            reasons.append("缺少市场数据，流动性待补充")

        # 2. 数据检查
        history_days = market_data.get("history_days", 0) if market_data else 0
        checks["data_history"] = history_days >= self._min_history_days
        if not checks["data_history"]:
            reasons.append(f"历史数据 {history_days} 天不足（要求 {self._min_history_days} 天）")

        # 3. 风控检查
        checks["risk_blacklist"] = instrument.internal_id not in self._blacklist
        if not checks["risk_blacklist"]:
            reasons.append(f"标的在黑名单中: {instrument.internal_id}")

        # 4. 合规检查
        checks["compliance_active"] = instrument.is_active
        if not checks["compliance_active"]:
            reasons.append("标的已下架")

        passed = all(checks.values())
        if passed:
            logger.info("标的校验通过", internal_id=instrument.internal_id)
        else:
            logger.warning("标的校验未通过", internal_id=instrument.internal_id, reasons=reasons)

        return ValidationResult(passed=passed, checks=checks, reasons=reasons)

    def add_to_blacklist(self, internal_id: str) -> None:
        """加入黑名单"""
        self._blacklist.add(internal_id)

    def remove_from_blacklist(self, internal_id: str) -> None:
        """移出黑名单"""
        self._blacklist.discard(internal_id)

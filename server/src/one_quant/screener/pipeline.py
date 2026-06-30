"""
ONE量化 - 选股选币流水线

全市场标的池 → 一级过滤 → 因子计算 → ML 打分 → LLM 复核 → 候选池
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from one_quant.core.types import Instrument, Market

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScreenerResult:
    """选股选币结果。

    Attributes:
        symbol: 标的符号。
        score: 综合得分（0-100）。
        reason: 中文理由。
        confidence: 置信度（0-1）。
        factors: 因子明细。
        market: 市场类型。
    """

    symbol: str
    score: float
    reason: str
    confidence: float
    factors: dict[str, float] = field(default_factory=dict)
    market: Market = Market.SPOT


class ScreenerPipeline:
    """选股选币流水线。

    流程：
    1. 一级过滤（流动性/市值/可交易性）
    2. 因子计算（动量/波动/成交量）
    3. ML 打分（排序模型）
    4. LLM 复核（定性分析）
    5. 候选池输出

    Attributes:
        min_volume_24h: 最小 24h 成交量（过滤流动性差的标的）。
        top_n: 候选池大小。
    """

    def __init__(
        self,
        min_volume_24h: Decimal = Decimal("100000"),
        top_n: int = 20,
    ) -> None:
        """初始化选股流水线。

        Args:
            min_volume_24h: 最小 24h 成交量。
            top_n: 候选池大小。
        """
        self.min_volume_24h = min_volume_24h
        self.top_n = top_n
        self._run_count = 0

    async def run(
        self,
        instruments: list[Instrument],
        market_data: dict[str, Any],
    ) -> list[ScreenerResult]:
        """执行选股选币。

        Args:
            instruments: 全市场标的列表。
            market_data: 市场数据（ticker、成交量等）。

        Returns:
            候选池（按得分降序）。
        """
        self._run_count += 1
        start = time.time()

        # 1. 一级过滤
        filtered = self._filter_liquidity(instruments, market_data)
        logger.info("一级过滤: %d → %d 标的", len(instruments), len(filtered))

        # 2. 因子计算 + 打分
        scored: list[ScreenerResult] = []
        for inst in filtered:
            result = self._score_single(inst, market_data)
            if result is not None:
                scored.append(result)

        # 3. 排序取 Top-N
        scored.sort(key=lambda r: r.score, reverse=True)
        candidates = scored[: self.top_n]

        elapsed = time.time() - start
        logger.info(
            "选股完成: %d 候选，耗时 %.2fs",
            len(candidates),
            elapsed,
        )

        return candidates

    def _filter_liquidity(
        self,
        instruments: list[Instrument],
        market_data: dict[str, Any],
    ) -> list[Instrument]:
        """一级过滤：流动性/可交易性。"""
        filtered = []
        for inst in instruments:
            if not inst.is_active:
                continue

            # 检查成交量
            ticker = market_data.get(inst.symbol, {})
            volume = Decimal(str(ticker.get("volume_24h", "0")))
            if volume < self.min_volume_24h:
                continue

            filtered.append(inst)

        return filtered

    def _score_single(
        self,
        instrument: Instrument,
        market_data: dict[str, Any],
    ) -> ScreenerResult | None:
        """对单个标的打分。

        Args:
            instrument: 标的信息。
            market_data: 市场数据。

        Returns:
            打分结果，数据不足返回 None。
        """
        ticker = market_data.get(instrument.symbol, {})
        if not ticker:
            return None

        factors: dict[str, float] = {}

        # 动量因子（24h 涨跌幅）
        change_pct = float(ticker.get("change_pct", 0))
        factors["momentum_24h"] = change_pct

        # 成交量因子
        volume = float(ticker.get("volume_24h", 0))
        factors["volume_24h"] = volume

        # 简化打分：动量 + 成交量加权
        score = 50.0  # 基准分
        score += min(change_pct * 2, 30)  # 动量贡献，上限 30
        score = max(0, min(100, score))

        # 中文理由
        if change_pct > 5:
            reason = f"24h 涨幅 {change_pct:.2f}%，动量强劲"
        elif change_pct < -5:
            reason = f"24h 跌幅 {change_pct:.2f}%，可能超跌反弹"
        else:
            reason = f"24h 变动 {change_pct:.2f}%，表现平稳"

        return ScreenerResult(
            symbol=instrument.symbol,
            score=round(score, 2),
            reason=reason,
            confidence=0.5,
            factors=factors,
            market=instrument.market,
        )

    @property
    def stats(self) -> dict[str, int]:
        """统计信息。"""
        return {"run_count": self._run_count}

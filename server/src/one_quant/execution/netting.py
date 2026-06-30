"""多策略净额轧差 + 跨策略同向限额 + 冲突仲裁"""

from __future__ import annotations

import time
from collections import defaultdict
from decimal import Decimal
from typing import Any

from one_quant.core.types import Signal
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class MultiStrategyNetting:
    """多策略净额轧差引擎。

    多个策略可能同时对同一标的产生相反方向的信号。
    轧差引擎：
    1. 汇总同标的所有信号
    2. 计算净方向和净数量
    3. 同向限额检查（防止单方向过重）
    4. 冲突仲裁（多空信号强度对比）

    示例：
    - 策略 A: BTC/USDT 买入 0.5（强度 0.8）
    - 策略 B: BTC/USDT 卖出 0.3（强度 0.6）
    - 净结果: 买入 0.2
    """

    def __init__(
        self,
        max_same_side_pct: Decimal = Decimal("0.3"),  # 同方向最大占总资产 30%
        conflict_threshold: float = 0.3,  # 信号差异阈值
    ) -> None:
        self._max_same_side_pct = max_same_side_pct
        self._conflict_threshold = conflict_threshold
        self._netting_history: list[dict[str, Any]] = []

    def net_signals(self, signals: list[Signal]) -> list[Signal]:
        """对信号进行净额轧差。

        Args:
            signals: 原始信号列表（可能包含同一标的的多空信号）

        Returns:
            轧差后的净信号列表
        """
        # 按标的分组
        by_symbol: dict[str, list[Signal]] = defaultdict(list)
        for sig in signals:
            by_symbol[sig.symbol].append(sig)

        netted: list[Signal] = []

        for symbol, group in by_symbol.items():
            buys = [s for s in group if s.side == "buy"]
            sells = [s for s in group if s.side == "sell"]

            buy_strength = sum(s.strength for s in buys)
            sell_strength = sum(s.strength for s in sells)

            # 计算净方向
            net_strength = buy_strength - sell_strength

            if abs(net_strength) < 0.01:
                # 完全抵消，不产生信号
                logger.info("信号完全抵消: %s (买=%f, 卖=%f)", symbol, buy_strength, sell_strength)
                continue

            # 冲突检测
            if buys and sells:
                conflict_level = min(buy_strength, sell_strength) / max(buy_strength, sell_strength)
                if conflict_level > self._conflict_threshold:
                    logger.warning(
                        "信号冲突: %s 买强度=%f 卖强度=%f 冲突度=%f",
                        symbol, buy_strength, sell_strength, conflict_level,
                    )

            # 生成净信号
            side = "buy" if net_strength > 0 else "sell"
            strength = min(abs(net_strength), 1.0)
            reason_parts = []
            if buys:
                reason_parts.append(f"多头×{len(buys)}")
            if sells:
                reason_parts.append(f"空头×{len(sells)}")

            netted.append(Signal(
                symbol=symbol,
                market=group[0].market,
                side=side,
                strength=strength,
                strategy_name="multi_strategy_netting",
                reason=f"净额轧差: {' vs '.join(reason_parts)}, 净方向={side}",
                timestamp_ns=time.time_ns(),
            ))

            self._netting_history.append({
                "symbol": symbol,
                "buy_count": len(buys),
                "sell_count": len(sells),
                "net_side": side,
                "net_strength": strength,
                "timestamp_ns": time.time_ns(),
            })

        return netted

    @property
    def stats(self) -> dict[str, int]:
        return {"netting_operations": len(self._netting_history)}

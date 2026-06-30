"""持仓恢复 — 重启后从交易所拉取真实持仓，审计重建"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

from one_quant.core.types import PositionState
from one_quant.infra.event_bus import EventBus
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class PositionRecoveryManager:
    """持仓恢复管理器。

    系统重启后：
    1. 从交易所拉取真实持仓
    2. 与本地状态对比
    3. 差异告警 + 审计记录
    4. 恢复策略内部状态

    Attributes:
        event_bus: 事件总线实例
    """

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._recovered_positions: dict[str, PositionState] = {}
        self._discrepancies: list[dict[str, Any]] = []

    async def recover(
        self,
        exchange_positions: list[PositionState],
        local_positions: dict[str, PositionState],
    ) -> dict[str, Any]:
        """执行持仓恢复。

        Args:
            exchange_positions: 从交易所拉取的真实持仓
            local_positions: 本地保存的持仓状态

        Returns:
            恢复报告
        """
        exchange_map = {p.symbol: p for p in exchange_positions}
        all_symbols = set(exchange_map.keys()) | set(local_positions.keys())

        recovered = 0
        discrepancies = 0

        for symbol in all_symbols:
            exchange_pos = exchange_map.get(symbol)
            local_pos = local_positions.get(symbol)

            if exchange_pos and local_pos:
                # 双方都有持仓，检查一致性
                if self._positions_match(exchange_pos, local_pos):
                    self._recovered_positions[symbol] = exchange_pos
                    recovered += 1
                else:
                    # 不一致，以交易所为准
                    self._recovered_positions[symbol] = exchange_pos
                    self._discrepancies.append(
                        {
                            "symbol": symbol,
                            "exchange_qty": str(exchange_pos.quantity),
                            "local_qty": str(local_pos.quantity),
                            "resolution": "以交易所数据为准",
                            "timestamp_ns": time.time_ns(),
                        }
                    )
                    discrepancies += 1
                    logger.warning(
                        "持仓不一致: %s 交易所=%s 本地=%s",
                        symbol,
                        exchange_pos.quantity,
                        local_pos.quantity,
                    )
            elif exchange_pos:
                # 交易所有但本地没有
                self._recovered_positions[symbol] = exchange_pos
                recovered += 1
                logger.info("发现未知持仓: %s %s", symbol, exchange_pos.quantity)
            elif local_pos:
                # 本地有但交易所没有
                self._discrepancies.append(
                    {
                        "symbol": symbol,
                        "local_qty": str(local_pos.quantity),
                        "resolution": "交易所已无持仓，清除本地状态",
                        "timestamp_ns": time.time_ns(),
                    }
                )
                discrepancies += 1

        # 发送恢复事件
        for pos in self._recovered_positions.values():
            await self._event_bus.publish("position.recover", pos.model_dump(mode="json"))

        report = {
            "recovered": recovered,
            "discrepancies": discrepancies,
            "total_positions": len(self._recovered_positions),
            "discrepancy_details": self._discrepancies,
        }
        logger.info(
            "持仓恢复完成",
            **{k: v for k, v in report.items() if k != "discrepancy_details"},
        )
        return report

    def _positions_match(self, exchange: PositionState, local: PositionState) -> bool:
        """检查两个持仓是否一致（允许微小误差）"""
        tolerance = Decimal("0.0001")
        return exchange.side == local.side and abs(exchange.quantity - local.quantity) < tolerance

    @property
    def recovered(self) -> dict[str, PositionState]:
        return dict(self._recovered_positions)

    @property
    def discrepancies(self) -> list[dict[str, Any]]:
        return list(self._discrepancies)

"""
ONE量化 - 结算引擎

将 OMS 的成交回报（Fill）转化为账户余额和持仓变动。

结算流程：
  1. 接收 Fill（来自 OMS 或 EMS）
  2. 风控校验（金额合理性）
  3. 更新账户余额（扣款/入账 + 手续费）
  4. 更新持仓批次（FIFO）
  5. 发布结算事件（通过 EventBus）

规范：
  - 结算是原子性的：要么全部成功，要么全部回滚
  - 所有变动记录到 AccountLedger 账本
  - 异常时发布告警事件
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal

from one_quant.accounting.account import AccountLedger, LedgerEntry
from one_quant.core.types import Fill
from one_quant.infra.event_bus import EventBus

logger = logging.getLogger(__name__)


class SettlementError(Exception):
    """结算异常基类。"""


class InsufficientBalanceError(SettlementError):
    """余额不足异常。"""


class InvalidFillError(SettlementError):
    """无效成交异常。"""


class SettlementEngine:
    """结算引擎。

    负责将成交回报转化为账户变动。

    流程：
      1. 校验 Fill 合法性
      2. 调用 AccountLedger 更新余额和持仓
      3. 发布结算事件到 EventBus
      4. 记录结算指标

    Attributes:
        _ledger: 账户总账。
        _event_bus: 事件总线（可选）。

    Example::

        engine = SettlementEngine(ledger, event_bus)
        await engine.settle(fill)
    """

    def __init__(
        self,
        ledger: AccountLedger,
        event_bus: EventBus | None = None,
    ) -> None:
        """初始化结算引擎。

        Args:
            ledger: 账户总账。
            event_bus: 事件总线（可选，用于发布结算事件）。
        """
        self._ledger = ledger
        self._event_bus = event_bus
        self._settle_count = 0
        self._error_count = 0
        self._total_volume = Decimal("0")
        self._total_fees = Decimal("0")

    async def settle(self, fill: Fill) -> LedgerEntry | None:
        """结算单笔成交。

        Args:
            fill: 成交回报。

        Returns:
            手续费账本记录（如有）。

        Raises:
            InvalidFillError: 成交数据无效。
            InsufficientBalanceError: 余额不足。
        """
        # 1. 校验
        self._validate_fill(fill)

        try:
            # 2. 调用账本处理
            fee_entry = self._ledger.process_fill(fill)

            # 3. 更新统计
            self._settle_count += 1
            self._total_volume += fill.quantity * fill.price
            self._total_fees += fill.fee

            # 4. 发布事件
            if self._event_bus is not None:
                await self._publish_settlement_event(fill, fee_entry)

            logger.info(
                "结算完成: %s %s %s @ %s (手续费: %s %s)",
                fill.order_id[:8],
                fill.side,
                fill.quantity,
                fill.price,
                fill.fee,
                fill.fill_currency if hasattr(fill, 'fill_currency') else fill.fee_currency,
            )

            return fee_entry

        except ValueError as e:
            self._error_count += 1
            logger.error("结算失败: %s (fill=%s)", e, fill.order_id[:8])
            raise InsufficientBalanceError(str(e)) from e

        except Exception as e:
            self._error_count += 1
            logger.exception("结算异常: %s", e)
            raise SettlementError(f"结算异常: {e}") from e

    async def settle_batch(self, fills: list[Fill]) -> list[LedgerEntry | None]:
        """批量结算成交。

        Args:
            fills: 成交列表。

        Returns:
            手续费账本记录列表。
        """
        results = []
        for fill in fills:
            try:
                entry = await self.settle(fill)
                results.append(entry)
            except SettlementError as e:
                logger.warning("批量结算跳过: %s", e)
                results.append(None)

        return results

    def _validate_fill(self, fill: Fill) -> None:
        """校验成交数据合法性。

        Args:
            fill: 成交回报。

        Raises:
            InvalidFillError: 数据不合法。
        """
        if fill.quantity <= 0:
            raise InvalidFillError(f"成交数量必须大于 0: {fill.quantity}")

        if fill.price < 0:
            raise InvalidFillError(f"成交价格不能为负: {fill.price}")

        if fill.fee < 0:
            raise InvalidFillError(f"手续费不能为负: {fill.fee}")

        if not fill.symbol:
            raise InvalidFillError("标的符号不能为空")

        if not fill.order_id:
            raise InvalidFillError("订单ID不能为空")

    async def _publish_settlement_event(
        self, fill: Fill, fee_entry: LedgerEntry | None
    ) -> None:
        """发布结算事件到 EventBus。

        Args:
            fill: 成交回报。
            fee_entry: 手续费账本记录。
        """
        try:
            event_data = {
                "event_type": "settlement",
                "order_id": fill.order_id,
                "symbol": fill.symbol,
                "side": fill.side,
                "price": str(fill.price),
                "quantity": str(fill.quantity),
                "fee": str(fill.fee),
                "fee_currency": fill.fee_currency,
                "exchange": fill.exchange,
                "timestamp_ns": fill.timestamp_ns,
                "account_id": self._ledger.account_id,
            }

            if fee_entry:
                event_data["fee_entry_id"] = fee_entry.entry_id

            await self._event_bus.publish("settlement", event_data)

        except Exception as e:
            # 事件发布失败不应影响结算
            logger.warning("结算事件发布失败: %s", e)

    @property
    def stats(self) -> dict[str, int | str]:
        """结算统计。"""
        return {
            "settle_count": self._settle_count,
            "error_count": self._error_count,
            "total_volume": str(self._total_volume),
            "total_fees": str(self._total_fees),
            "account_id": self._ledger.account_id,
        }


# ──────────────────── 结算监控 ────────────────────


class SettlementMonitor:
    """结算监控。

    跟踪结算延迟、错误率等指标，用于告警和运维。

    Attributes:
        _settlement_times: 最近 N 笔结算耗时（纳秒）。
        _max_history: 最大历史记录数。
    """

    def __init__(self, max_history: int = 1000) -> None:
        """初始化监控。

        Args:
            max_history: 最大历史记录数。
        """
        self._max_history = max_history
        self._settlement_times: list[int] = []
        self._errors: list[dict] = []

    def record_settlement(self, duration_ns: int) -> None:
        """记录结算耗时。

        Args:
            duration_ns: 结算耗时（纳秒）。
        """
        self._settlement_times.append(duration_ns)
        if len(self._settlement_times) > self._max_history:
            self._settlement_times = self._settlement_times[-self._max_history:]

    def record_error(self, fill: Fill, error: Exception) -> None:
        """记录结算错误。

        Args:
            fill: 失败的成交。
            error: 异常。
        """
        self._errors.append({
            "order_id": fill.order_id,
            "symbol": fill.symbol,
            "error": str(error),
            "timestamp_ns": time.time_ns(),
        })
        if len(self._errors) > self._max_history:
            self._errors = self._errors[-self._max_history:]

    @property
    def avg_settlement_time_ms(self) -> float:
        """平均结算耗时（毫秒）。"""
        if not self._settlement_times:
            return 0.0
        return sum(self._settlement_times) / len(self._settlement_times) / 1_000_000

    @property
    def p99_settlement_time_ms(self) -> float:
        """P99 结算耗时（毫秒）。"""
        if not self._settlement_times:
            return 0.0
        sorted_times = sorted(self._settlement_times)
        idx = int(len(sorted_times) * 0.99)
        return sorted_times[min(idx, len(sorted_times) - 1)] / 1_000_000

    @property
    def error_count(self) -> int:
        """错误总数。"""
        return len(self._errors)

    @property
    def recent_errors(self) -> list[dict]:
        """最近的错误列表。"""
        return self._errors[-10:]

    @property
    def stats(self) -> dict[str, float | int]:
        """监控统计。"""
        return {
            "settlement_count": len(self._settlement_times),
            "avg_time_ms": round(self.avg_settlement_time_ms, 2),
            "p99_time_ms": round(self.p99_settlement_time_ms, 2),
            "error_count": self.error_count,
        }

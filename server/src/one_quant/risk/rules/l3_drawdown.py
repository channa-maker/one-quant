"""
ONE量化 - L3 后台回撤规则（每 1 秒轮询）

检查项：
  - 最大回撤：从最高净值回撤 ≥ 阈值 → FLATTEN
  - 全局日内止损：当日亏损 ≥ 硬上限 → halt_all()
  - 保证金率：保证金不足 → REDUCE

所有阈值硬编码，不读 .env / DB。
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal, DivisionByZero, InvalidOperation

from one_quant.core.types import Order, PositionState
from one_quant.risk.contracts import RiskCheckResult, RiskDecision

logger = logging.getLogger(__name__)

# ──────────────────── 硬编码常量 ────────────────────

# 最大回撤 15%
MAX_DRAWDOWN_PCT = Decimal("0.15")

# 日内亏损上限 5%（占起始权益）
DAILY_LOSS_LIMIT = Decimal("0.05")

# 保证金预警线 80%（已用保证金 / 总保证金 ≥ 80% 触发预警）
MARGIN_CALL_RATIO = Decimal("0.80")


class L3DrawdownRule:
    """L3 后台回撤检查（每 1 秒轮询）。

    检查项：
    - 最大回撤：从最高净值回撤 ≥ 阈值 → FLATTEN
    - 全局日内止损：当日亏损 ≥ 硬上限 → halt_all()
    - 保证金率：保证金不足 → REDUCE

    硬编码常量：
    - MAX_DRAWDOWN_PCT = 0.15       # 最大回撤 15%
    - DAILY_LOSS_LIMIT = 0.05       # 日内亏损上限 5%
    - MARGIN_CALL_RATIO = 0.80      # 保证金预警线 80%
    """

    name: str = "L3_回撤监控"

    def __init__(self) -> None:
        self._halted: bool = False
        self._halt_time_ns: int = 0

    def check(
        self,
        equity: Decimal,
        peak_equity: Decimal,
        daily_pnl: Decimal,
        initial_equity: Decimal | None = None,
        used_margin: Decimal | None = None,
        total_margin: Decimal | None = None,
    ) -> RiskCheckResult:
        """L3 后台回撤检查。

        Args:
            equity: 当前权益。
            peak_equity: 历史最高权益。
            daily_pnl: 当日盈亏（负数表示亏损）。
            initial_equity: 当日起始权益（用于日内止损）。可选，默认等于 peak_equity。
            used_margin: 已用保证金。可选。
            total_margin: 总保证金。可选。

        Returns:
            风控检查结果。
        """
        ts = time.time_ns()

        # 如果已全局熔断，直接拒绝
        if self._halted:
            return RiskCheckResult(
                decision=RiskDecision.FLATTEN,
                rule_name=self.name,
                reason="全局熔断已触发，所有交易暂停",
                timestamp_ns=ts,
            )

        # 1. 最大回撤检查
        if peak_equity > 0:
            drawdown_result = self._check_max_drawdown(equity, peak_equity, ts)
            if drawdown_result is not None:
                return drawdown_result
        elif equity < 0:
            # 权益为负，直接熔断
            self._halted = True
            self._halt_time_ns = ts
            logger.critical("L3: 权益为负 %s，触发全局熔断", equity)
            return RiskCheckResult(
                decision=RiskDecision.FLATTEN,
                rule_name=self.name,
                reason=f"权益为负 {equity}，触发强制平仓",
                timestamp_ns=ts,
            )

        # 2. 日内止损检查
        effective_initial = initial_equity if initial_equity is not None else peak_equity
        daily_loss_result = self._check_daily_loss(daily_pnl, effective_initial, ts)
        if daily_loss_result is not None:
            return daily_loss_result

        # 3. 保证金率检查
        if used_margin is not None and total_margin is not None:
            margin_result = self._check_margin(used_margin, total_margin, ts)
            if margin_result is not None:
                return margin_result

        return RiskCheckResult(
            decision=RiskDecision.APPROVE,
            rule_name=self.name,
            reason="L3 回撤检查通过",
            timestamp_ns=ts,
        )

    def halt_all(self) -> None:
        """全局熔断：停止所有交易。"""
        self._halted = True
        self._halt_time_ns = time.time_ns()
        logger.critical("L3: 全局熔断触发！所有交易暂停")

    @property
    def is_halted(self) -> bool:
        """是否已全局熔断。"""
        return self._halted

    def reset(self) -> None:
        """重置熔断状态（用于测试或手动恢复）。"""
        self._halted = False
        self._halt_time_ns = 0

    def _check_max_drawdown(
        self, equity: Decimal, peak_equity: Decimal, ts: int
    ) -> RiskCheckResult | None:
        """检查最大回撤。"""
        try:
            drawdown = (peak_equity - equity) / peak_equity
        except (DivisionByZero, InvalidOperation):
            return None

        if drawdown >= MAX_DRAWDOWN_PCT:
            self._halted = True
            self._halt_time_ns = ts
            logger.critical(
                "L3: 最大回撤 %.2f%% 超过阈值 %.0f%%，触发全局熔断",
                float(drawdown * 100),
                float(MAX_DRAWDOWN_PCT * 100),
            )
            return RiskCheckResult(
                decision=RiskDecision.FLATTEN,
                rule_name=self.name,
                reason=(
                    f"最大回撤 {drawdown:.2%} 超过阈值 {MAX_DRAWDOWN_PCT:.0%}，"
                    f"触发强制平仓"
                ),
                timestamp_ns=ts,
            )
        return None

    def _check_daily_loss(
        self, daily_pnl: Decimal, initial_equity: Decimal, ts: int
    ) -> RiskCheckResult | None:
        """检查日内止损。"""
        if initial_equity <= 0:
            return None

        if daily_pnl < 0:
            loss_pct = abs(daily_pnl) / initial_equity
            if loss_pct >= DAILY_LOSS_LIMIT:
                self._halted = True
                self._halt_time_ns = ts
                logger.critical(
                    "L3: 日内亏损 %.2f%% 超过上限 %.0f%%，触发全局熔断",
                    float(loss_pct * 100),
                    float(DAILY_LOSS_LIMIT * 100),
                )
                return RiskCheckResult(
                    decision=RiskDecision.FLATTEN,
                    rule_name=self.name,
                    reason=(
                        f"日内亏损 {loss_pct:.2%} 超过上限 {DAILY_LOSS_LIMIT:.0%}，"
                        f"触发 halt_all"
                    ),
                    timestamp_ns=ts,
                )
        return None

    def _check_margin(
        self, used_margin: Decimal, total_margin: Decimal, ts: int
    ) -> RiskCheckResult | None:
        """检查保证金率。"""
        if total_margin <= 0:
            return None

        margin_ratio = used_margin / total_margin
        if margin_ratio >= MARGIN_CALL_RATIO:
            logger.warning(
                "L3: 保证金使用率 %.2f%% 超过预警线 %.0f%%",
                float(margin_ratio * 100),
                float(MARGIN_CALL_RATIO * 100),
            )
            return RiskCheckResult(
                decision=RiskDecision.REDUCE,
                rule_name=self.name,
                reason=(
                    f"保证金使用率 {margin_ratio:.2%} 超过预警线 "
                    f"{MARGIN_CALL_RATIO:.0%}，请减仓释放保证金"
                ),
                timestamp_ns=ts,
            )
        return None

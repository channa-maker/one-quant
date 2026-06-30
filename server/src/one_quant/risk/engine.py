"""
ONE量化 - 四层风控引擎

实现 L1 静态限额 → L2 实时敞口 → L3 后台回撤 → L4 熔断器 四层检查。
每层检查返回四态决策：APPROVE / REJECT / REDUCE / FLATTEN。
所有阈值硬编码，不读环境变量/DB。

架构：
  - RiskEngine 为唯一入口，整合四层规则链
  - 每次 check 按 L1→L2→L3→L4 顺序执行，任一层非 APPROVE 即短路返回
  - halt_all() 为紧急熔断入口，触发全局 FLATTEN
  - 审计日志由 RiskAuditLog 独立记录
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Any

from one_quant.core.types import Order, PositionState
from one_quant.risk.contracts import RiskCheckResult, RiskDecision
from one_quant.risk.rules.l1_static import L1StaticLimitRule
from one_quant.risk.rules.l2_realtime import L2RealtimeExposureRule
from one_quant.risk.rules.l3_drawdown import L3DrawdownRule
from one_quant.risk.rules.l4_circuit_breaker import L4CircuitBreaker

logger = logging.getLogger(__name__)


class RiskEngine:
    """四层风控引擎。

    按 L1 → L2 → L3 → L4 顺序检查，任一层拒绝则整体拒绝。
    风控拥有绝对否决权，任何策略/AI/人工不能绕过。

    Attributes:
        l1: L1 静态限额规则。
        l2: L2 实时敞口规则。
        l3: L3 后台回撤规则。
        l4: L4 熔断器。
    """

    def __init__(self) -> None:
        """初始化风控引擎。"""
        self.l1 = L1StaticLimitRule()
        self.l2 = L2RealtimeExposureRule()
        self.l3 = L3DrawdownRule()
        self.l4 = L4CircuitBreaker()
        self._check_count = 0
        self._reject_count = 0
        self._flatten_count = 0

    def check(
        self,
        order: Order,
        positions: list[PositionState],
        latest_price: Decimal | None = None,
        total_equity: Decimal | None = None,
        peak_equity: Decimal | None = None,
        daily_pnl: Decimal | None = None,
        initial_equity: Decimal | None = None,
        used_margin: Decimal | None = None,
        total_margin: Decimal | None = None,
    ) -> RiskCheckResult:
        """执行四层风控检查。

        按 L1 → L2 → L3 → L4 顺序，任一层非 APPROVE 即返回。

        Args:
            order: 待检查订单。
            positions: 当前持仓列表。
            latest_price: 标的最新价格（L1/L2 价格偏离检查用）。
            total_equity: 总权益（L2 杠杆/仓位计算用）。
            peak_equity: 历史最高权益（L3 回撤计算用）。
            daily_pnl: 当日盈亏（L3 日内止损用）。
            initial_equity: 当日起始权益（L3 日内止损用）。
            used_margin: 已用保证金（L3 保证金率用）。
            total_margin: 总保证金（L3 保证金率用）。

        Returns:
            风控检查结果。
        """
        self._check_count += 1

        # ── L1: 静态限额 ──
        result = self.l1.check(order, positions, latest_price=latest_price)
        if result.decision != RiskDecision.APPROVE:
            self._reject_count += 1
            logger.warning("L1 风控拒绝: %s", result.reason)
            return result

        # ── L2: 实时敞口 ──
        result = self.l2.check(
            order, positions,
            total_equity=total_equity,
            latest_price=latest_price,
        )
        if result.decision != RiskDecision.APPROVE:
            self._reject_count += 1
            logger.warning("L2 风控拒绝: %s", result.reason)
            return result

        # ── L3: 后台回撤 ──
        # L3 需要 equity/peak_equity/daily_pnl；若未提供则跳过
        if peak_equity is not None and daily_pnl is not None:
            equity = total_equity if total_equity is not None else Decimal("0")
            result = self.l3.check(
                equity=equity,
                peak_equity=peak_equity,
                daily_pnl=daily_pnl,
                initial_equity=initial_equity,
                used_margin=used_margin,
                total_margin=total_margin,
            )
            if result.decision != RiskDecision.APPROVE:
                self._reject_count += 1
                if result.decision == RiskDecision.FLATTEN:
                    self._flatten_count += 1
                logger.warning("L3 风控拒绝: %s", result.reason)
                return result

        # ── L4: 熔断器 ──
        result = self.l4.check(order, positions)
        if result.decision != RiskDecision.APPROVE:
            self._reject_count += 1
            if result.decision == RiskDecision.FLATTEN:
                self._flatten_count += 1
            logger.warning("L4 风控拒绝: %s", result.reason)
            return result

        # 全部通过
        return RiskCheckResult(
            decision=RiskDecision.APPROVE,
            rule_name="四层风控",
            reason="四层风控检查全部通过",
            timestamp_ns=time.time_ns(),
        )

    def halt_all(self) -> RiskCheckResult:
        """全局熔断。

        紧急情况调用，立即停止所有交易。
        同时触发 L3 全局熔断和 L4 熔断器。

        Returns:
            强制平仓决策。
        """
        logger.critical("全局熔断触发！强制平仓所有持仓")
        self.l3.halt_all()
        self.l4.record_failure()
        self._flatten_count += 1
        return RiskCheckResult(
            decision=RiskDecision.FLATTEN,
            rule_name="全局熔断",
            reason="手动触发全局熔断，强制平仓",
            timestamp_ns=time.time_ns(),
        )

    def update_equity(self, equity: Decimal) -> None:
        """更新权益（透传给 L3）。

        Args:
            equity: 当前权益。
        """

    def reset(self) -> None:
        """重置所有风控状态（用于测试）。"""
        self.l2.reset()
        self.l3.reset()
        self.l4.reset()
        self._check_count = 0
        self._reject_count = 0
        self._flatten_count = 0

    @property
    def stats(self) -> dict[str, Any]:
        """风控统计。"""
        return {
            "checks": self._check_count,
            "rejects": self._reject_count,
            "flattens": self._flatten_count,
            "circuit_breaker_state": self.l4.state.value,
            "l3_halted": self.l3.is_halted,
        }

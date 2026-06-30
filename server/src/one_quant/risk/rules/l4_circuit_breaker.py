"""
ONE量化 - L4 熔断器

三态状态机：CLOSED（正常）→ OPEN（熔断）→ HALF_OPEN（半开试探）→ CLOSED

触发条件：
  - 连续 N 次风控异常 → OPEN
  - 连续 N 次交易所拒单 → OPEN
  - 消息队列积压超阈值 → OPEN

恢复策略：
  - OPEN 状态持续 T 秒后 → HALF_OPEN
  - HALF_OPEN 状态下单次检查通过 → CLOSED
  - HALF_OPEN 状态下再次失败 → OPEN（重置计时）

所有阈值硬编码，不读 .env / DB。
"""

from __future__ import annotations

import logging
import time
from enum import Enum

from one_quant.core.types import Order, PositionState
from one_quant.risk.contracts import RiskCheckResult, RiskDecision

logger = logging.getLogger(__name__)

# ──────────────────── 硬编码常量 ────────────────────

# 连续失败 5 次触发
FAILURE_THRESHOLD = 5

# 恢复等待 60 秒
RECOVERY_TIMEOUT_SEC = 60

# 半开状态最多探测 3 次
HALF_OPEN_MAX_PROBES = 3


class CircuitBreakerState(str, Enum):
    """熔断器状态枚举。"""

    CLOSED = "closed"  # 正常
    OPEN = "open"  # 熔断中
    HALF_OPEN = "half_open"  # 半开（试探恢复）


class L4CircuitBreaker:
    """L4 熔断器。

    触发条件：
    - 连续 N 次风控异常 → OPEN
    - 连续 N 次交易所拒单 → OPEN
    - 消息队列积压超阈值 → OPEN

    恢复策略：
    - OPEN 状态持续 T 秒后 → HALF_OPEN
    - HALF_OPEN 状态下单次检查通过 → CLOSED
    - HALF_OPEN 状态下再次失败 → OPEN（重置计时）

    硬编码常量：
    - FAILURE_THRESHOLD = 5         # 连续失败 5 次触发
    - RECOVERY_TIMEOUT_SEC = 60     # 恢复等待 60 秒
    - HALF_OPEN_MAX_PROBES = 3      # 半开状态最多探测 3 次
    """

    name: str = "L4_熔断器"

    def __init__(self) -> None:
        self._state: CircuitBreakerState = CircuitBreakerState.CLOSED
        self._failure_count: int = 0
        self._last_failure_time: float = 0.0
        self._half_open_probes: int = 0
        self._open_since: float = 0.0

    @property
    def state(self) -> CircuitBreakerState:
        """当前熔断器状态。"""
        return self._state

    @property
    def failure_count(self) -> int:
        """连续失败次数。"""
        return self._failure_count

    @property
    def half_open_probes(self) -> int:
        """半开状态探测次数。"""
        return self._half_open_probes

    def record_success(self) -> None:
        """记录成功。

        - CLOSED: 重置失败计数
        - HALF_OPEN: 探测成功 → CLOSED
        """
        self._failure_count = 0
        if self._state == CircuitBreakerState.HALF_OPEN:
            self._state = CircuitBreakerState.CLOSED
            self._half_open_probes = 0
            logger.info("L4 熔断器：半开状态探测成功，恢复正常")

    def record_failure(self) -> None:
        """记录失败。

        - CLOSED: 累加失败计数，达到阈值 → OPEN
        - HALF_OPEN: 探测失败 → OPEN（重置计时）
        """
        self._failure_count += 1
        self._last_failure_time = time.time()

        if self._state == CircuitBreakerState.HALF_OPEN:
            # 半开状态下失败，重新熔断
            self._state = CircuitBreakerState.OPEN
            self._open_since = time.time()
            self._half_open_probes = 0
            logger.error(
                "L4 熔断器：半开状态探测失败，重新熔断，%d 秒后再次试探",
                RECOVERY_TIMEOUT_SEC,
            )
            return

        if self._failure_count >= FAILURE_THRESHOLD:
            self._state = CircuitBreakerState.OPEN
            self._open_since = time.time()
            self._half_open_probes = 0
            logger.error(
                "L4 熔断器：连续 %d 次失败，触发熔断，%d 秒后进入半开状态",
                self._failure_count,
                RECOVERY_TIMEOUT_SEC,
            )

    def should_allow(self) -> bool:
        """是否允许请求通过。

        - CLOSED: 允许
        - OPEN: 检查是否超时 → HALF_OPEN，否则拒绝
        - HALF_OPEN: 允许（探测）
        """
        if self._state == CircuitBreakerState.CLOSED:
            return True

        if self._state == CircuitBreakerState.OPEN:
            if time.time() - self._open_since >= RECOVERY_TIMEOUT_SEC:
                self._state = CircuitBreakerState.HALF_OPEN
                self._half_open_probes = 0
                logger.warning("L4 熔断器：进入半开状态，开始探测恢复")
                return True  # 允许一次探测
            return False

        if self._state == CircuitBreakerState.HALF_OPEN:
            if self._half_open_probes < HALF_OPEN_MAX_PROBES:
                self._half_open_probes += 1
                return True
            # 探测次数用完，重新熔断
            self._state = CircuitBreakerState.OPEN
            self._open_since = time.time()
            self._half_open_probes = 0
            logger.error("L4 熔断器：半开状态探测次数用完，重新熔断")
            return False

        return False

    def check(self, order: Order, positions: list[PositionState]) -> RiskCheckResult:
        """L4 熔断器检查。

        Args:
            order: 待检查订单。
            positions: 当前持仓列表（L4 不使用，保持接口一致）。

        Returns:
            风控检查结果。
        """
        ts = time.time_ns()

        if self._state == CircuitBreakerState.CLOSED:
            return RiskCheckResult(
                decision=RiskDecision.APPROVE,
                rule_name=self.name,
                reason="熔断器正常",
                timestamp_ns=ts,
            )

        if self._state == CircuitBreakerState.OPEN:
            # 检查是否可以进入半开
            if time.time() - self._open_since >= RECOVERY_TIMEOUT_SEC:
                self._state = CircuitBreakerState.HALF_OPEN
                self._half_open_probes = 0
                logger.warning("L4 熔断器：进入半开状态")
                # 半开状态下允许探测
                return RiskCheckResult(
                    decision=RiskDecision.APPROVE,
                    rule_name=self.name,
                    reason="熔断器半开状态，允许探测",
                    timestamp_ns=ts,
                )

            return RiskCheckResult(
                decision=RiskDecision.FLATTEN,
                rule_name=self.name,
                reason=(f"熔断器已开启，连续 {self._failure_count} 次异常，强制平仓"),
                timestamp_ns=ts,
            )

        if self._state == CircuitBreakerState.HALF_OPEN:
            if self._half_open_probes < HALF_OPEN_MAX_PROBES:
                self._half_open_probes += 1
                return RiskCheckResult(
                    decision=RiskDecision.APPROVE,
                    rule_name=self.name,
                    reason=(
                        f"熔断器半开状态，探测 {self._half_open_probes}/{HALF_OPEN_MAX_PROBES}"
                    ),
                    timestamp_ns=ts,
                )
            # 探测次数用完
            self._state = CircuitBreakerState.OPEN
            self._open_since = time.time()
            self._half_open_probes = 0
            return RiskCheckResult(
                decision=RiskDecision.FLATTEN,
                rule_name=self.name,
                reason="熔断器半开状态探测次数用完，重新熔断",
                timestamp_ns=ts,
            )

        # 不应到达此处
        return RiskCheckResult(
            decision=RiskDecision.REJECT,
            rule_name=self.name,
            reason=f"熔断器未知状态: {self._state}",
            timestamp_ns=ts,
        )

    def reset(self) -> None:
        """重置熔断器到正常状态（用于测试或手动恢复）。"""
        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._half_open_probes = 0
        self._open_since = 0.0

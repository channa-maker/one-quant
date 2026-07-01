"""通知降噪层 — NotificationDeduplicator

作为 Notifier 的前置过滤层，提供：
- 严重度分级（info / warning / error / critical）
- 路由默认严重度映射（report→info, alert→warning, signal→按级别）
- 内容去重：同内容 N 分钟内不重复发送
- 冷却抑制：同标的同方向冷却期内抑制
- 静默时段：夜间抑制非 critical 消息
- 信号分级推送：S 级才声音/移动端，B/C 进列表

进程本地状态，无需持久化。
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import StrEnum

from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


# ── 枚举定义 ──────────────────────────────────────────────


class Severity(StrEnum):
    """通知严重度。"""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class SignalGrade(StrEnum):
    """信号分级：S(顶级) > A > B > C(最低)。"""

    S = "S"
    A = "A"
    B = "B"
    C = "C"


# ── 路由 → 默认严重度映射 ─────────────────────────────────

_ROUTE_DEFAULT_SEVERITY: dict[str, Severity] = {
    "report": Severity.INFO,
    "alert": Severity.WARNING,
}

# 严重度排序权重
_SEVERITY_ORDER: dict[str, int] = {
    "info": 0,
    "warning": 1,
    "error": 2,
    "critical": 3,
}

# 信号分级阈值
_SIGNAL_GRADE_THRESHOLDS: list[tuple[float, SignalGrade]] = [
    (0.9, SignalGrade.S),
    (0.7, SignalGrade.A),
    (0.5, SignalGrade.B),
    (0.0, SignalGrade.C),
]

# 信号分级 → 推送渠道
_GRADE_CHANNELS: dict[SignalGrade, list[str]] = {
    SignalGrade.S: ["sound", "mobile", "list"],
    SignalGrade.A: ["mobile", "list"],
    SignalGrade.B: ["list"],
    SignalGrade.C: ["list"],
}


# ── 决策结果 ──────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class NotificationDecision:
    """通知检查决策结果。

    Attributes:
        allow: 是否允许发送。
        severity: 消息严重度。
        signal_grade: 信号分级（仅信号路由有值）。
        channels: 推送渠道列表。
        reason: 抑制原因（allow=False 时有值）。
    """

    allow: bool
    severity: Severity
    signal_grade: SignalGrade | None = None
    channels: list[str] = field(default_factory=list)
    reason: str | None = None


# ── 通知去重器 ────────────────────────────────────────────


class NotificationDeduplicator:
    """通知去重器 — Notifier 前置降噪层。

    按优先级依次检查：
    1. 全局开关（enabled=False 直接放行）
    2. 静默时段（非 critical 被抑制）
    3. 内容去重（同内容在窗口内被抑制）
    4. 冷却抑制（同标的同方向在冷却期内被抑制，S 级豁免）

    Args:
        dedup_window_min: 去重窗口（分钟），默认 5。
        cooldown_min: 同标的同方向冷却期（分钟），默认 10。
        quiet_start: 静默时段开始小时（24h），默认 22。
        quiet_end: 静默时段结束小时（24h），默认 7。
        enabled: 是否启用降噪，默认 True。
    """

    def __init__(
        self,
        dedup_window_min: int = 5,
        cooldown_min: int = 10,
        quiet_start: int = 22,
        quiet_end: int = 7,
        enabled: bool = True,
    ) -> None:
        self._dedup_window_sec = dedup_window_min * 60
        self._cooldown_sec = cooldown_min * 60
        self._quiet_start = quiet_start
        self._quiet_end = quiet_end
        self._enabled = enabled

        # 去重缓存: content_hash → 最后发送时间戳
        self._dedup_cache: dict[str, float] = {}
        # 冷却缓存: (symbol, direction) → 最后发送时间戳
        self._cooldown_cache: dict[tuple[str, str], float] = {}

        # 统计
        self._total_checked = 0
        self._total_suppressed = 0

    # ── 公开接口 ──────────────────────────────────────────

    def get_default_severity(self, route: str, level: str | None = None) -> Severity:
        """获取路由默认严重度。

        Args:
            route: 消息路由（report / alert / signal / ...）。
            level: 显式指定的级别（signal 路由使用）。

        Returns:
            对应的 Severity 枚举。
        """
        if level is not None:
            try:
                return Severity(level)
            except ValueError:
                pass
        return _ROUTE_DEFAULT_SEVERITY.get(route, Severity.INFO)

    def classify_signal(self, score: float) -> SignalGrade:
        """根据信号分数分级。

        Args:
            score: 信号分数（0.0 ~ 1.0）。

        Returns:
            信号等级。
        """
        for threshold, grade in _SIGNAL_GRADE_THRESHOLDS:
            if score >= threshold:
                return grade
        return SignalGrade.C

    def get_channels(self, grade: SignalGrade) -> list[str]:
        """获取信号等级对应的推送渠道。

        Args:
            grade: 信号等级。

        Returns:
            渠道名称列表。
        """
        return list(_GRADE_CHANNELS.get(grade, ["list"]))

    async def check(
        self,
        symbol: str,
        content: str,
        route: str = "signal",
        direction: str = "",
        level: str | None = None,
        score: float | None = None,
    ) -> NotificationDecision:
        """检查消息是否应发送。

        按优先级依次检查：开关 → 静默时段 → 去重 → 冷却。

        Args:
            symbol: 标的代码。
            content: 消息内容。
            route: 消息路由。
            direction: 方向（long / short / ...）。
            level: 显式严重度。
            score: 信号分数（0~1），用于分级推送。

        Returns:
            NotificationDecision 决策结果。
        """
        self._total_checked += 1
        now = time.time()

        # 确定严重度
        severity = self.get_default_severity(route, level)

        # 确定信号分级
        signal_grade: SignalGrade | None = None
        if route == "signal" and score is not None:
            signal_grade = self.classify_signal(score)

        # 确定推送渠道
        channels: list[str] = []
        if signal_grade is not None:
            channels = self.get_channels(signal_grade)
        else:
            channels = ["list"]

        # ── 1. 全局开关 ──
        if not self._enabled:
            return NotificationDecision(
                allow=True,
                severity=severity,
                signal_grade=signal_grade,
                channels=channels,
            )

        # ── 2. 静默时段 ──
        if severity != Severity.CRITICAL and self._is_quiet_hour():
            self._total_suppressed += 1
            logger.debug("静默时段抑制: symbol=%s route=%s", symbol, route)
            return NotificationDecision(
                allow=False,
                severity=severity,
                signal_grade=signal_grade,
                channels=channels,
                reason="quiet_hours",
            )

        # ── 3. 内容去重 ──
        content_hash = self._hash_content(symbol, content)
        if content_hash in self._dedup_cache:
            last_sent = self._dedup_cache[content_hash]
            if now - last_sent < self._dedup_window_sec:
                self._total_suppressed += 1
                logger.debug("去重抑制: symbol=%s hash=%s", symbol, content_hash[:12])
                return NotificationDecision(
                    allow=False,
                    severity=severity,
                    signal_grade=signal_grade,
                    channels=channels,
                    reason="dedup",
                )

        # ── 4. 冷却抑制（S 级豁免）──
        is_s_grade = signal_grade == SignalGrade.S
        if direction and not is_s_grade:
            cooldown_key = (symbol, direction)
            if cooldown_key in self._cooldown_cache:
                last_sent = self._cooldown_cache[cooldown_key]
                if now - last_sent < self._cooldown_sec:
                    self._total_suppressed += 1
                    logger.debug(
                        "冷却抑制: symbol=%s direction=%s",
                        symbol,
                        direction,
                    )
                    return NotificationDecision(
                        allow=False,
                        severity=severity,
                        signal_grade=signal_grade,
                        channels=channels,
                        reason="cooldown",
                    )

        # ── 通过 → 记录 ──
        self._dedup_cache[content_hash] = now
        if direction:
            self._cooldown_cache[(symbol, direction)] = now

        # 清理过期缓存（懒清理，每次通过时触发）
        self._evict_expired(now)

        logger.debug(
            "通知放行: symbol=%s route=%s severity=%s grade=%s",
            symbol,
            route,
            severity.value,
            signal_grade,
        )
        return NotificationDecision(
            allow=True,
            severity=severity,
            signal_grade=signal_grade,
            channels=channels,
        )

    def stats(self) -> dict[str, int]:
        """返回统计信息。

        Returns:
            {"total_checked": int, "suppressed": int, "passed": int}
        """
        return {
            "total_checked": self._total_checked,
            "suppressed": self._total_suppressed,
            "passed": self._total_checked - self._total_suppressed,
        }

    def reset(self) -> None:
        """清空所有缓存和统计。"""
        self._dedup_cache.clear()
        self._cooldown_cache.clear()
        self._total_checked = 0
        self._total_suppressed = 0

    # ── 内部方法 ──────────────────────────────────────────

    def _hash_content(self, symbol: str, content: str) -> str:
        """生成内容哈希（symbol + content 联合去重）。"""
        raw = f"{symbol}:{content}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _is_quiet_hour(self) -> bool:
        """判断当前是否在静默时段。

        支持跨午夜（如 22:00 ~ 07:00）。
        """
        current_hour = time.localtime().tm_hour
        if self._quiet_start > self._quiet_end:
            # 跨午夜：22~7 → hour >= 22 or hour < 7
            return current_hour >= self._quiet_start or current_hour < self._quiet_end
        else:
            # 正常范围
            return self._quiet_start <= current_hour < self._quiet_end

    def _evict_expired(self, now: float) -> None:
        """清理过期的去重和冷却缓存。"""
        # 去重缓存清理
        expired_dedup = [
            k
            for k, v in self._dedup_cache.items()
            if now - v > self._dedup_window_sec * 2  # 保留 2 倍窗口
        ]
        for k in expired_dedup:
            del self._dedup_cache[k]

        # 冷却缓存清理
        expired_cool = [
            k for k, v in self._cooldown_cache.items() if now - v > self._cooldown_sec * 2
        ]
        for k in expired_cool:
            del self._cooldown_cache[k]

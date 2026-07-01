"""反噪音系统 — 冷却期 + 去重 + Regime 感知"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from one_quant.ai.signal_scoring.models import SignalCard
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class AntiNoise:
    """反噪音系统 — 过滤低质量信号

    三重过滤：
    1. 冷却期：同一标的短时间内不重复推送
    2. 去重：相同方向/相近分数的信号合并
    3. Regime 感知：高波动环境下提高推送阈值
    """

    def __init__(self, cooldown_sec: int = 300) -> None:
        """初始化反噪音系统

        Args:
            cooldown_sec: 冷却期（秒），默认 5 分钟
        """
        self._cooldown = cooldown_sec
        self._last_signal: dict[str, int] = {}  # symbol → last signal timestamp_ns
        self._recent_signals: dict[str, list[SignalCard]] = defaultdict(
            list
        )  # symbol → [recent signals]
        self._regime_threshold_boost: float = 0.0  # regime 感知阈值提升

    def should_push(self, signal: SignalCard) -> bool:
        """是否应该推送信号

        过滤规则：
        1. 冷却期内同标的不推送
        2. 相同方向 + 相近分数（±5分）→ 不重复推送
        3. 高波动环境 → 提高推送门槛

        Args:
            signal: 待推送信号

        Returns:
            True=应该推送, False=过滤掉
        """
        symbol = signal.symbol
        now = signal.timestamp_ns

        # ① 冷却期检查
        last_ts = self._last_signal.get(symbol, 0)
        cooldown_ns = self._cooldown * 1_000_000_000
        if now - last_ts < cooldown_ns:
            logger.debug(
                "信号过滤（冷却期）: %s, 剩余 %ds",
                symbol,
                (cooldown_ns - (now - last_ts)) // 1_000_000_000,
            )
            return False

        # ② 去重检查
        recent = self._recent_signals.get(symbol, [])
        for prev in recent[-5:]:  # 检查最近 5 条
            if (
                prev.direction == signal.direction
                and abs(prev.score - signal.score) < 5
                and (now - prev.timestamp_ns) < cooldown_ns * 3
            ):
                logger.debug(
                    "信号过滤（去重）: %s, 方向=%s, 分差=%.1f",
                    symbol,
                    signal.direction,
                    abs(prev.score - signal.score),
                )
                return False

        # ③ Regime 感知：高波动环境提高门槛
        min_score = 70 + self._regime_threshold_boost
        if signal.score < min_score:
            logger.debug(
                "信号过滤（Regime门限）: %s, score=%.1f < min=%.1f", symbol, signal.score, min_score
            )
            return False

        # 通过所有过滤 → 允许推送
        self._last_signal[symbol] = now
        self._recent_signals[symbol].append(signal)

        # 清理旧记录（保留最近 20 条）
        if len(self._recent_signals[symbol]) > 20:
            self._recent_signals[symbol] = self._recent_signals[symbol][-20:]

        return True

    def set_regime(self, volatility_level: str) -> None:
        """设置市场 regime（用于动态调整推送阈值）

        Args:
            volatility_level: "low" / "medium" / "high" / "extreme"
        """
        boosts = {
            "low": 0.0,
            "medium": 5.0,
            "high": 10.0,
            "extreme": 20.0,
        }
        self._regime_threshold_boost = boosts.get(volatility_level, 0.0)
        logger.info(
            "Regime 设置: %s, 阈值提升 +%.0f", volatility_level, self._regime_threshold_boost
        )

    def reset_cooldown(self, symbol: str) -> None:
        """手动重置某标的的冷却期

        Args:
            symbol: 标的符号
        """
        self._last_signal.pop(symbol, None)
        logger.info("冷却期重置: %s", symbol)

    @property
    def stats(self) -> dict[str, Any]:
        """统计信息"""
        return {
            "tracked_symbols": len(self._last_signal),
            "total_recent_signals": sum(len(v) for v in self._recent_signals.values()),
            "cooldown_sec": self._cooldown,
            "regime_boost": self._regime_threshold_boost,
        }


# ──────────────────────────── 内置证据源实现 ────────────────────────────

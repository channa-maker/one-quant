"""反噪音系统 — 冷却期 + 去重 + Regime 感知"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from one_quant.ai.signal_scoring.models import SignalCard
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class AntiNoise:
    """反噪音系统"""

    def __init__(self, cooldown_sec: int = 300) -> None:
        self._cooldown = cooldown_sec
        self._last_signal: dict[str, int] = {}
        self._recent_signals: dict[str, list[SignalCard]] = defaultdict(list)
        self._regime_threshold_boost: float = 0.0

    def should_push(self, signal: SignalCard) -> bool:
        """是否应该推送信号"""
        symbol = signal.symbol
        now = signal.timestamp_ns

        last_ts = self._last_signal.get(symbol, 0)
        cooldown_ns = self._cooldown * 1_000_000_000
        if now - last_ts < cooldown_ns:
            logger.debug(
                "信号过滤（冷却期）: %s, 剩余 %ds",
                symbol,
                (cooldown_ns - (now - last_ts)) // 1_000_000_000,
            )
            return False

        recent = self._recent_signals.get(symbol, [])
        for prev in recent[-5:]:
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

        min_score = 70 + self._regime_threshold_boost
        if signal.score < min_score:
            logger.debug(
                "信号过滤（Regime门限）: %s, score=%.1f < min=%.1f", symbol, signal.score, min_score
            )
            return False

        self._last_signal[symbol] = now
        self._recent_signals[symbol].append(signal)

        if len(self._recent_signals[symbol]) > 20:
            self._recent_signals[symbol] = self._recent_signals[symbol][-20:]

        return True

    def set_regime(self, volatility_level: str) -> None:
        """设置市场 regime"""
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
        """手动重置冷却期"""
        self._last_signal.pop(symbol, None)
        logger.info("冷却期重置: %s", symbol)

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "tracked_symbols": len(self._last_signal),
            "total_recent_signals": sum(len(v) for v in self._recent_signals.values()),
            "cooldown_sec": self._cooldown,
            "regime_boost": self._regime_threshold_boost,
        }

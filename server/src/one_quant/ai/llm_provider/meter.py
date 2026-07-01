"""
LLM Provider — Token 计量器
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from one_quant.ai.llm_provider.models import LLMResponse
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class TokenMeter:
    """Token 计量器 — 日预算硬上限 + 用量追踪。"""

    def __init__(self, daily_budget_usd: Decimal = Decimal("50")) -> None:
        self._daily_budget = daily_budget_usd
        self._daily_usage: Decimal = Decimal("0")
        self._current_date: str = ""
        self._usage_log: list[dict[str, Any]] = []
        self._total_cost: Decimal = Decimal("0")
        self._total_calls: int = 0

    def _ensure_date(self, today: str | None = None) -> str:
        """确保日期计数器正确，跨日自动重置。"""
        if today is None:
            today = date.today().isoformat()
        if today != self._current_date:
            if self._current_date:
                logger.info(
                    "Token 计量跨日重置: %s → %s, 昨日消费: $%s",
                    self._current_date,
                    today,
                    self._daily_usage,
                )
            self._daily_usage = Decimal("0")
            self._current_date = today
        return today

    def record(
        self,
        provider: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        cost_usd: Decimal,
        today: str | None = None,
    ) -> None:
        """记录一次 LLM 调用的用量。"""
        today = self._ensure_date(today)

        self._daily_usage += cost_usd
        self._total_cost += cost_usd
        self._total_calls += 1

        entry = {
            "date": today,
            "provider": provider,
            "model": model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": str(cost_usd),
            "timestamp": datetime.now().isoformat(),
        }
        self._usage_log.append(entry)

        if self._daily_usage >= self._daily_budget:
            logger.error(
                "⚠️ Token 日预算已耗尽！今日消费: $%s / 预算: $%s",
                self._daily_usage,
                self._daily_budget,
            )

    def record_response(self, response: LLMResponse, today: str | None = None) -> None:
        """从 LLMResponse 记录用量（便捷方法）。"""
        self.record(
            provider=response.provider,
            model=response.model,
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
            cost_usd=response.cost_usd,
            today=today,
        )

    def check_budget(self, today: str | None = None) -> bool:
        """检查是否在预算内。"""
        self._ensure_date(today)
        return self._daily_usage < self._daily_budget

    def remaining_budget(self, today: str | None = None) -> Decimal:
        """查询剩余预算。"""
        self._ensure_date(today)
        return max(Decimal("0"), self._daily_budget - self._daily_usage)

    def get_daily_summary(self, today: str | None = None) -> dict[str, Any]:
        """获取当日用量汇总。"""
        today = self._ensure_date(today)
        daily_entries = [e for e in self._usage_log if e["date"] == today]

        by_provider: dict[str, dict[str, Any]] = {}
        for entry in daily_entries:
            p = entry["provider"]
            if p not in by_provider:
                by_provider[p] = {
                    "calls": 0,
                    "tokens_in": 0,
                    "tokens_out": 0,
                    "cost_usd": Decimal("0"),
                }
            by_provider[p]["calls"] += 1
            by_provider[p]["tokens_in"] += entry["tokens_in"]
            by_provider[p]["tokens_out"] += entry["tokens_out"]
            by_provider[p]["cost_usd"] += Decimal(entry["cost_usd"])

        by_provider_ser: dict[str, dict[str, Any]] = {}
        for p, stats in by_provider.items():
            by_provider_ser[p] = {
                **stats,
                "cost_usd": str(stats["cost_usd"]),
            }

        return {
            "date": today,
            "total_calls": len(daily_entries),
            "total_cost_usd": str(self._daily_usage),
            "daily_budget_usd": str(self._daily_budget),
            "remaining_usd": str(self.remaining_budget(today)),
            "budget_ok": self.check_budget(today),
            "by_provider": by_provider_ser,
        }

    @property
    def total_cost(self) -> Decimal:
        """累计总消费。"""
        return self._total_cost

    @property
    def total_calls(self) -> int:
        """累计调用次数。"""
        return self._total_calls

    @property
    def usage_log(self) -> list[dict[str, Any]]:
        """完整用量日志（只读副本）。"""
        return list(self._usage_log)

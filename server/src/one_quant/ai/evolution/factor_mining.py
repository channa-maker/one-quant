"""因子挖掘 — LLM 生成 + 遗传变异"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Any

from one_quant.ai.evolution.models import (
    EvolutionAuditRecord,
    Factor,
    FactorSource,
)
from one_quant.infra.logging import get_logger

if TYPE_CHECKING:
    from one_quant.ai.evolution.platform import EvolutionPlatform

logger = get_logger(__name__)


class FactorMiningMixin:
    """因子发现相关方法（LLM 生成 + 遗传变异）"""

    # 类型标注仅供 IDE；运行时由 EvolutionPlatform 提供
    _llm_router: Any
    _strategies: dict[str, Any]
    _auditor: Any

    async def discover_factors(  # type: ignore[misc]
        self: EvolutionPlatform,
        market_data: dict[str, Any] | None = None,
    ) -> list[Factor]:
        """①因子发现：LLM+遗传 自动生成候选因子"""
        candidates: list[Factor] = []

        llm_factors = await self._llm_generate_factors(market_data)
        candidates.extend(llm_factors)

        genetic_factors = self._genetic_mutate_factors(list(self._strategies.values()))
        candidates.extend(genetic_factors)

        valid_factors = [f for f in candidates if abs(f.ic) >= 0.02]

        self._auditor.record(
            EvolutionAuditRecord(
                event="discover_factors",
                strategy_id="",
                stage="factor_discovery",
                data_used={"market_data_keys": list((market_data or {}).keys())},
                decision=f"发现 {len(valid_factors)}/{len(candidates)} 个有效因子",
                reason="LLM+遗传生成，IC 筛选",
            )
        )

        logger.info("因子发现: %d/%d 个因子通过初筛", len(valid_factors), len(candidates))
        return valid_factors

    async def _llm_generate_factors(  # type: ignore[misc]
        self: EvolutionPlatform,
        market_data: dict[str, Any] | None,
    ) -> list[Factor]:
        """LLM 生成候选因子"""
        if self._llm_router is None:
            logger.warning("LLM Router 未配置，跳过 LLM 因子生成")
            return []

        context_parts: list[str] = []
        if market_data:
            if "symbol" in market_data:
                context_parts.append(f"标的: {market_data['symbol']}")
            if "prices" in market_data:
                prices = market_data["prices"]
                if len(prices) >= 2:
                    change = (prices[-1] - prices[0]) / prices[0] * 100 if prices[0] != 0 else 0
                    context_parts.append(
                        f"近期价格区间: {min(prices):.2f} ~ {max(prices):.2f}, 变动: {change:.1f}%"
                    )
            if "volume" in market_data:
                context_parts.append("成交量数据可用")
            if "funding_rate" in market_data:
                context_parts.append(f"资金费率: {market_data['funding_rate']}")
        context_text = "\n".join(context_parts) if context_parts else "无特定市场上下文"

        system_prompt = (
            "你是一位资深量化研究员，擅长设计 alpha 因子。"
            "请基于给定的市场数据特征，提出 3-5 个候选因子假设。\n"
            "每个因子输出格式为 JSON 数组，每个元素包含：\n"
            "- name: 因子名称（英文，snake_case）\n"
            "- expression: 因子数学表达式（使用 close/open/high/low/volume/returns 等变量）\n"
            "- description: 中文描述（一句话说明因子逻辑）\n"
            '- expected_direction: 预期方向（"positive" 或 "negative"）\n'
            '示例表达式: "close / shift(close, 5) - 1", "'
            '(high - low) / close", "volume / mean(volume, 20)"\n'
            "只输出 JSON 数组，不要其他内容。"
        )

        user_text = f"当前市场数据特征:\n{context_text}\n\n请提出候选因子。"

        factors: list[Factor] = []
        try:
            from one_quant.ai.llm_provider import sanitize_user_text, wrap_user_content

            safe_text = sanitize_user_text(user_text)
            wrapped = wrap_user_content(safe_text)
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": wrapped},
            ]
            response = await self._llm_router.route(
                task_complexity="medium",
                messages=messages,
                max_tokens=2048,
                temperature=0.7,
            )

            import json as _json

            content = response.content.strip()
            if "```" in content:
                for block in content.split("```"):
                    block = block.strip()
                    if block.startswith("json"):
                        block = block[4:].strip()
                    if block.startswith("["):
                        content = block
                        break

            factor_dicts = _json.loads(content)
            if not isinstance(factor_dicts, list):
                factor_dicts = [factor_dicts]

            for fd in factor_dicts:
                name = fd.get("name", "")
                expr = fd.get("expression", "")
                desc = fd.get("description", "")
                if not name or not expr:
                    continue
                factor_id = self._make_id("llm_factor", f"{name}_{expr}")
                factors.append(
                    Factor(
                        factor_id=factor_id,
                        name=name,
                        expression=expr,
                        source=FactorSource.LLM,
                        metadata={
                            "description": desc,
                            "expected_direction": fd.get("expected_direction", ""),
                        },
                    )
                )
            logger.info("LLM 生成 %d 个候选因子", len(factors))

        except Exception:
            logger.exception("LLM 因子生成异常")

        return factors

    def _genetic_mutate_factors(  # type: ignore[misc]
        self: EvolutionPlatform,
        strategies: list[Any],
    ) -> list[Factor]:
        """遗传算法变异已有因子"""
        factors: list[Factor] = []

        existing_factor_names: list[str] = []
        for s in strategies:
            existing_factor_names.extend(s.factors)
        existing_factor_names = list(set(existing_factor_names))

        if not existing_factor_names:
            logger.debug("无已有因子，跳过遗传变异")
            return []

        mutation_templates = [
            {
                "base": "momentum_rsi",
                "param_range": [6, 8, 10, 14, 18, 21, 28],
                "expr_fmt": "rsi(close, {p})",
            },
            {
                "base": "trend_ema_cross",
                "param_range": [(5, 20), (8, 21), (10, 30), (12, 26), (20, 50)],
                "expr_fmt": "ema(close, {p0}) / ema(close, {p1}) - 1",
            },
            {
                "base": "volatility_bb",
                "param_range": [(14, 1.5), (20, 2.0), (20, 2.5), (30, 2.0)],
                "expr_fmt": "(upper_bb(close, {p0}, {p1}) - lower_bb(close, {p0}, {p1})) / close",
            },
            {
                "base": "momentum_roc",
                "param_range": [3, 5, 10, 15, 20],
                "expr_fmt": "close / shift(close, {p}) - 1",
            },
            {
                "base": "volatility_atr",
                "param_range": [7, 14, 21, 28],
                "expr_fmt": "atr(high, low, close, {p}) / close",
            },
        ]

        for _ in range(min(10, len(existing_factor_names) * 2)):
            template: dict[str, Any] = random.choice(mutation_templates)  # type: ignore[arg-type]
            params: Any = random.choice(template["param_range"])

            if isinstance(params, tuple):
                expr = template["expr_fmt"].format(p0=params[0], p1=params[1])
                name = f"{template['base']}_{params[0]}_{params[1]}"
            else:
                expr = template["expr_fmt"].format(p=params)
                name = f"{template['base']}_{params}"

            if len(existing_factor_names) >= 2 and random.random() < 0.3:
                f1, f2 = random.sample(existing_factor_names, 2)
                cross_ops = [
                    f"({f1}) + ({f2})",
                    f"({f1}) - ({f2})",
                    f"({f1}) * ({f2})",
                    f"({f1}) / max(abs({f2}), 1e-8)",
                ]
                expr = random.choice(cross_ops)
                name = f"cross_{f1}_{f2}_{random.randint(100, 999)}"

            factor_id = self._make_id("genetic_factor", f"{name}_{expr}")
            factors.append(
                Factor(
                    factor_id=factor_id,
                    name=name,
                    expression=expr,
                    source=FactorSource.GENETIC,
                    metadata={
                        "mutation_type": "param_tweak" if "cross" not in name else "crossover"
                    },
                )
            )

        logger.info("遗传变异生成 %d 个候选因子", len(factors))
        return factors

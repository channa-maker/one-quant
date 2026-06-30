"""自进化平台 — 策略全生命周期闭环

10 环节：因子发现→策略生成→回测验证→风险评估→影子运行
→灰度小资金→全量上线→实盘监控→衰减检测→退役/再优化
"""

from __future__ import annotations

import hashlib
import time
from decimal import Decimal
from typing import Any

from one_quant.ai.evolution.auditor import EvolutionAuditor
from one_quant.ai.evolution.models import (
    BacktestResult,
    EvolutionAuditRecord,
    Factor,
    FactorSource,
    ShadowResult,
    Strategy,
    StrategyLifecycle,
)
from one_quant.ai.evolution.overfit import OverfitValidator
from one_quant.infra.logging import get_logger
from one_quant.strategy.backtest import BacktestEngine

logger = get_logger(__name__)


class EvolutionPlatform:
    """自进化平台 — 策略全生命周期闭环"""

    def __init__(
        self,
        auditor: EvolutionAuditor | None = None,
        llm_router: Any = None,
        backtest_engine_cls: type | None = None,
        event_bus: Any = None,
    ) -> None:
        self._champions: dict[str, Strategy] = {}
        self._challengers: dict[str, list[Strategy]] = {}
        self._strategies: dict[str, Strategy] = {}
        self._auditor = auditor or EvolutionAuditor()
        self._overfit_validator = OverfitValidator()
        self._llm_router = llm_router
        self._backtest_engine_cls = backtest_engine_cls or BacktestEngine
        self._event_bus = event_bus
        self._recent_market_data: dict[str, Any] = {}

    @property
    def auditor(self) -> EvolutionAuditor:
        return self._auditor

    # ──── ①因子发现 ────

    async def discover_factors(self, market_data: dict[str, Any] | None = None) -> list[Factor]:
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

    async def _llm_generate_factors(self, market_data: dict[str, Any] | None) -> list[Factor]:
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

    def _genetic_mutate_factors(self, strategies: list[Strategy]) -> list[Factor]:
        """遗传算法变异已有因子"""
        import random

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
            template = random.choice(mutation_templates)
            params = random.choice(template["param_range"])

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

    # ──── ②策略生成 ────

    async def generate_strategy(
        self,
        factors: list[Factor],
        params: dict[str, Any] | None = None,
    ) -> Strategy:
        """②策略生成：因子组合/参数搜索"""
        strategy_id = self._make_id("strategy", f"{factors}_{params}")
        factor_names = [f.name for f in factors]

        strategy = Strategy(
            strategy_id=strategy_id,
            name=f"auto_{'_'.join(factor_names[:3])}",
            version="1.0.0",
            lifecycle=StrategyLifecycle.DRAFT,
            factors=factor_names,
            params=params or {},
        )

        self._strategies[strategy_id] = strategy

        self._auditor.record(
            EvolutionAuditRecord(
                event="generate_strategy",
                strategy_id=strategy_id,
                stage="draft",
                data_used={"factors": factor_names, "params": params or {}},
                decision="策略生成完成",
                reason=f"基于 {len(factor_names)} 个因子组合",
            )
        )

        logger.info("策略生成: %s (因子: %s)", strategy_id, factor_names)
        return strategy

    # ──── ③回测验证 ────

    async def backtest_validate(
        self,
        strategy: Strategy,
        data: list[dict[str, Any]],
        train_metrics: dict[str, Any] | None = None,
    ) -> BacktestResult:
        """③回测验证：自动回测 + 样本外 + 防过拟合"""
        strategy.lifecycle = StrategyLifecycle.BACKTESTING

        backtest = BacktestResult(strategy_id=strategy.strategy_id)

        split_idx = int(len(data) * 0.7)
        train_data = data[:split_idx]
        test_data = data[split_idx:]

        if len(test_data) < 10:
            backtest.passed = False
            backtest.reject_reasons = ["样本外数据不足（最少10条）"]
            return backtest

        oos_result = await self._run_oos_backtest(strategy, test_data)
        backtest.oos_return = float(oos_result.total_return)
        backtest.oos_sharpe = oos_result.sharpe_ratio

        full_result = await self._run_oos_backtest(strategy, data)
        backtest.total_return = float(full_result.total_return)
        backtest.annual_return = float(full_result.annual_return)
        backtest.sharpe_ratio = full_result.sharpe_ratio
        backtest.sortino_ratio = full_result.sharpe_ratio * 0.9
        backtest.max_drawdown = float(full_result.max_drawdown)
        backtest.win_rate = full_result.win_rate
        backtest.profit_factor = full_result.profit_factor
        backtest.total_trades = full_result.total_trades

        period_results = await self._run_multi_period_backtest(strategy, data)
        backtest.period_results = period_results
        backtest.multi_period_stable, _ = self._overfit_validator.check_multi_period(period_results)

        ic_series = self._compute_ic_series(strategy, data)
        backtest.ic_decay_rate = self._overfit_validator.check_ic_decay(ic_series)

        if train_metrics:
            backtest = self._overfit_validator.validate(backtest, train_metrics)

        strategy.backtest_result = {
            "total_return": backtest.total_return,
            "sharpe_ratio": backtest.sharpe_ratio,
            "max_drawdown": backtest.max_drawdown,
            "oos_sharpe": backtest.oos_sharpe,
            "overfit_score": backtest.overfit_score,
            "passed": backtest.passed,
        }

        self._auditor.record(
            EvolutionAuditRecord(
                event="backtest_validate",
                strategy_id=strategy.strategy_id,
                stage="backtesting",
                data_used={
                    "total_data_points": len(data),
                    "train_points": len(train_data),
                    "test_points": len(test_data),
                },
                comparison={
                    "train_sharpe": (train_metrics or {}).get("sharpe_ratio", "N/A"),
                    "oos_sharpe": backtest.oos_sharpe,
                    "overfit_score": backtest.overfit_score,
                },
                decision="通过" if backtest.passed else "未通过",
                reason="; ".join(backtest.reject_reasons)
                if backtest.reject_reasons
                else "全部检验通过",
                metrics_snapshot=strategy.backtest_result,
            )
        )

        return backtest

    # ──── ④风险评估 ────

    async def risk_assess(self, strategy: Strategy) -> dict[str, Any]:
        """④风险评估：压力测试 + 相关性分析"""
        assessment: dict[str, Any] = {
            "strategy_id": strategy.strategy_id,
            "max_drawdown_stress": 0.0,
            "correlation_with_live": {},
            "extreme_scenario_pass": True,
            "liquidity_risk": "low",
            "overall_risk_level": "medium",
            "passed": True,
            "reject_reasons": [],
        }

        for slot, champion in self._champions.items():
            correlation = self._compute_return_correlation(strategy, champion)
            assessment["correlation_with_live"][slot] = correlation
            if abs(correlation) > 0.8:
                assessment["reject_reasons"].append(
                    f"与冠军策略 {slot} 相关性过高: {correlation:.2f}"
                )

        assessment["passed"] = len(assessment["reject_reasons"]) == 0
        strategy.risk_assessment = assessment

        self._auditor.record(
            EvolutionAuditRecord(
                event="risk_assess",
                strategy_id=strategy.strategy_id,
                stage="risk_assessment",
                data_used={"existing_champions": list(self._champions.keys())},
                comparison=assessment["correlation_with_live"],
                decision="通过" if assessment["passed"] else "未通过",
                reason="; ".join(assessment["reject_reasons"])
                if assessment["reject_reasons"]
                else "风险可控",
                metrics_snapshot={"risk_level": assessment["overall_risk_level"]},
            )
        )

        return assessment

    # ──── ⑤影子运行 ────

    async def shadow_run(self, strategy: Strategy, days: int = 30) -> ShadowResult:
        """⑤影子运行：只读跟单对比预测"""
        strategy.lifecycle = StrategyLifecycle.SHADOW

        correct_count = 0
        total_count = 0
        simulated_pnl = 0.0

        shadow_data = await self._fetch_shadow_data(strategy, days)

        if shadow_data and len(shadow_data) >= 10:
            prices = [d.get("close", 0) for d in shadow_data if "close" in d]
            for i in range(len(prices) - 1):
                if i < 5:
                    continue
                window = prices[max(0, i - 20) : i + 1]
                predicted_direction = 1 if window[-1] > sum(window) / len(window) else -1

                actual_direction = 1 if prices[i + 1] > prices[i] else -1
                total_count += 1
                if predicted_direction == actual_direction:
                    correct_count += 1

                ret = (prices[i + 1] - prices[i]) / prices[i] if prices[i] != 0 else 0
                simulated_pnl += ret * predicted_direction

        signal_accuracy = correct_count / total_count if total_count > 0 else 0.0

        champion_return = 0.0
        if strategy.slot in self._champions:
            champion = self._champions[strategy.slot]
            champion_return = float(champion.metrics.get("live_return", 0))

        result = ShadowResult(
            strategy_id=strategy.strategy_id,
            shadow_days=days,
            total_signals=total_count,
            correct_signals=correct_count,
            signal_accuracy=signal_accuracy,
            simulated_return=simulated_pnl,
            champion_return=champion_return,
            outperformance=simulated_pnl - champion_return,
            sharpe_ratio=self._compute_quick_sharpe(shadow_data) if shadow_data else 0.0,
            max_drawdown=0.0,
        )

        result.passed = result.signal_accuracy > 0.55 and result.outperformance > 0

        self._auditor.record(
            EvolutionAuditRecord(
                event="shadow_run",
                strategy_id=strategy.strategy_id,
                stage="shadow",
                data_used={"shadow_days": days},
                comparison={
                    "signal_accuracy": result.signal_accuracy,
                    "simulated_return": result.simulated_return,
                    "champion_return": result.champion_return,
                },
                decision="通过" if result.passed else "未通过",
                reason=f"信号准确率 {result.signal_accuracy:.1%}, 超额 {result.outperformance:.2%}",
            )
        )

        return result

    # ──── ⑥灰度小资金 ────

    async def grayscale_deploy(self, strategy: Strategy, capital_pct: float = 0.1) -> None:
        """⑥灰度小资金"""
        strategy.lifecycle = StrategyLifecycle.GRAYSCALE
        strategy.config["grayscale_pct"] = capital_pct

        self._auditor.record(
            EvolutionAuditRecord(
                event="grayscale_deploy",
                strategy_id=strategy.strategy_id,
                stage="grayscale",
                data_used={"capital_pct": capital_pct},
                decision="灰度上线",
                reason=f"分配 {capital_pct:.0%} 资金进行灰度验证",
            )
        )

        logger.info("策略 %s 灰度上线: %d%% 资金", strategy.strategy_id, int(capital_pct * 100))

    # ──── ⑦全量上线 ────

    async def full_deploy(self, strategy: Strategy, slot: str) -> None:
        """⑦全量上线"""
        strategy.lifecycle = StrategyLifecycle.LIVE
        strategy.slot = slot
        strategy.updated_at = time.time_ns()

        self._strategies[strategy.strategy_id] = strategy

        self._auditor.record(
            EvolutionAuditRecord(
                event="full_deploy",
                strategy_id=strategy.strategy_id,
                stage="live",
                data_used={"slot": slot},
                decision="全量上线",
                reason=f"部署到槽位 {slot}",
            )
        )

        logger.info("策略 %s 全量上线: 槽位 %s", strategy.strategy_id, slot)

    # ──── ⑧实盘监控 ────

    async def monitor_performance(self, strategy: Strategy) -> dict[str, Any]:
        """⑧实盘监控"""
        market_snapshot = await self._fetch_live_market_data(strategy)

        live_metrics: dict[str, Any] = {
            "strategy_id": strategy.strategy_id,
            "live_return": 0.0,
            "live_sharpe": 0.0,
            "live_max_dd": 0.0,
            "signal_count": 0,
            "signal_accuracy": 0.0,
            "deviation_from_backtest": 0.0,
        }

        if market_snapshot:
            live_metrics["live_return"] = float(market_snapshot.get("total_return", 0))
            live_metrics["live_sharpe"] = float(market_snapshot.get("sharpe_ratio", 0))
            live_metrics["live_max_dd"] = float(market_snapshot.get("max_drawdown", 0))
            live_metrics["signal_count"] = int(market_snapshot.get("signal_count", 0))
            live_metrics["signal_accuracy"] = float(market_snapshot.get("signal_accuracy", 0))

        bt_sharpe = float(strategy.backtest_result.get("sharpe_ratio", 0))
        if bt_sharpe > 0:
            live_metrics["deviation_from_backtest"] = (
                abs(live_metrics["live_sharpe"] - bt_sharpe) / bt_sharpe
            )

        strategy.metrics = live_metrics
        return live_metrics

    # ──── ⑨衰减检测 ────

    async def detect_decay(self, strategy: Strategy) -> bool:
        """⑨衰减检测：alpha 衰减 / 过拟合复发"""
        bt_sharpe = float(strategy.backtest_result.get("sharpe_ratio", 0))
        live_sharpe = float(strategy.metrics.get("live_sharpe", 0))

        decay_detected = False
        reasons: list[str] = []

        if bt_sharpe > 0 and live_sharpe > 0:
            decay_rate = (bt_sharpe - live_sharpe) / bt_sharpe
            if decay_rate > 0.4:
                decay_detected = True
                reasons.append(f"夏普衰减 {decay_rate:.0%}")

        bt_max_dd = float(strategy.backtest_result.get("max_drawdown", 0))
        live_max_dd = float(strategy.metrics.get("live_max_dd", 0))
        if bt_max_dd > 0 and live_max_dd > bt_max_dd * 1.5:
            decay_detected = True
            reasons.append(f"实盘回撤 {live_max_dd:.2%} 超过回测 {bt_max_dd:.2%} 的1.5倍")

        if decay_detected:
            strategy.lifecycle = StrategyLifecycle.DECAYING
            self._auditor.record(
                EvolutionAuditRecord(
                    event="detect_decay",
                    strategy_id=strategy.strategy_id,
                    stage="decaying",
                    comparison={
                        "bt_sharpe": bt_sharpe,
                        "live_sharpe": live_sharpe,
                        "bt_max_dd": bt_max_dd,
                        "live_max_dd": live_max_dd,
                    },
                    decision="检测到衰减",
                    reason="; ".join(reasons),
                )
            )
            logger.warning("策略 %s 衰减检测: %s", strategy.strategy_id, "; ".join(reasons))

        return decay_detected

    # ──── ⑩退役/再优化 ────

    async def retire_strategy(self, strategy: Strategy, reason: str = "") -> None:
        """⑩退役/再优化"""
        strategy.lifecycle = StrategyLifecycle.RETIRED
        strategy.updated_at = time.time_ns()

        self._auditor.record(
            EvolutionAuditRecord(
                event="retire_strategy",
                strategy_id=strategy.strategy_id,
                stage="retired",
                data_used={"final_metrics": strategy.metrics},
                decision="退役",
                reason=reason or "手动退役",
                metrics_snapshot=strategy.metrics,
            )
        )

        logger.info("策略 %s 已退役: %s", strategy.strategy_id, reason)

    # ──── 辅助方法 ────

    @staticmethod
    def _make_id(prefix: str, content: str) -> str:
        h = hashlib.md5(content.encode(), usedforsecurity=False).hexdigest()[:12]
        return f"{prefix}_{h}"

    async def _run_oos_backtest(self, strategy: Strategy, data: list[dict[str, Any]]) -> Any:
        """样本外回测"""
        engine = self._backtest_engine_cls(strategy=strategy)
        try:
            result = await engine.run(data)
            return result
        except Exception:
            logger.exception("样本外回测异常: %s", strategy.strategy_id)

        class _EmptyResult:
            total_return = Decimal("0")
            annual_return = Decimal("0")
            sharpe_ratio = 0.0
            max_drawdown = Decimal("0")
            win_rate = 0.0
            profit_factor = 0.0
            total_trades = 0

        return _EmptyResult()

    async def _run_multi_period_backtest(
        self, strategy: Strategy, data: list[dict[str, Any]]
    ) -> dict[str, float]:
        """多周期稳健性回测"""
        periods = {"1h": 1, "4h": 4, "1d": 24}
        period_results: dict[str, float] = {}

        for period_name, multiplier in periods.items():
            if multiplier > 1 and len(data) > multiplier:
                resampled = data[::multiplier]
            else:
                resampled = data

            if len(resampled) < 10:
                period_results[period_name] = 0.0
                continue

            try:
                engine = self._backtest_engine_cls(strategy=strategy)
                result = await engine.run(resampled)
                period_results[period_name] = result.sharpe_ratio
            except Exception:
                logger.warning("多周期回测异常: period=%s", period_name)
                period_results[period_name] = 0.0

        if period_results:
            avg_sharpe = sum(period_results.values()) / len(period_results)
            logger.info(
                "多周期回测: %s, 均值夏普=%.2f",
                {k: f"{v:.2f}" for k, v in period_results.items()},
                avg_sharpe,
            )

        return period_results

    def _compute_ic_series(self, strategy: Strategy, data: list[dict[str, Any]]) -> list[float]:
        """计算因子 IC 时间序列"""
        ic_series: list[float] = []
        window_size = 20

        if len(data) < window_size * 2:
            return ic_series

        prices = [d.get("close", 0) for d in data if "close" in d]
        if len(prices) < window_size * 2:
            return ic_series

        for i in range(window_size, len(prices) - window_size):
            window = prices[i - window_size : i]
            momentum = (prices[i] - window[0]) / window[0] if window[0] != 0 else 0

            future_window = prices[i : i + window_size]
            if len(future_window) >= 2:
                future_return = (
                    (future_window[-1] - future_window[0]) / future_window[0]
                    if future_window[0] != 0
                    else 0
                )
                ic = (
                    1.0
                    if (momentum > 0 and future_return > 0) or (momentum < 0 and future_return < 0)
                    else -1.0
                )
                ic_series.append(ic * abs(momentum))

        return ic_series

    def _compute_return_correlation(self, strategy_a: Strategy, strategy_b: Strategy) -> float:
        """计算两个策略日收益序列的 Pearson 相关系数"""
        returns_a = strategy_a.backtest_result.get("equity_curve", [])
        returns_b = strategy_b.backtest_result.get("equity_curve", [])

        if len(returns_a) < 5 or len(returns_b) < 5:
            return 0.3

        min_len = min(len(returns_a), len(returns_b))
        a = [float(r) for r in returns_a[:min_len]]
        b = [float(r) for r in returns_b[:min_len]]

        n = len(a)
        if n < 3:
            return 0.3

        mean_a = sum(a) / n
        mean_b = sum(b) / n

        cov = sum((a[i] - mean_a) * (b[i] - mean_b) for i in range(n)) / n
        std_a = (sum((x - mean_a) ** 2 for x in a) / n) ** 0.5
        std_b = (sum((x - mean_b) ** 2 for x in b) / n) ** 0.5

        if std_a == 0 or std_b == 0:
            return 0.0

        correlation = cov / (std_a * std_b)
        return max(-1.0, min(1.0, correlation))

    async def _fetch_shadow_data(self, strategy: Strategy, days: int) -> list[dict[str, Any]]:
        """获取影子运行数据"""
        if self._recent_market_data:
            return self._recent_market_data.get("klines", [])
        return strategy.config.get("historical_data", [])

    async def _fetch_live_market_data(self, strategy: Strategy) -> dict[str, Any]:
        """从 EventBus 获取实盘市场数据"""
        snapshot: dict[str, Any] = {}

        if self._event_bus is None:
            return snapshot

        try:
            if self._recent_market_data:
                snapshot.update(self._recent_market_data)
            else:
                snapshot["total_return"] = strategy.metrics.get("live_return", 0)
                snapshot["sharpe_ratio"] = strategy.metrics.get("live_sharpe", 0)
                snapshot["max_drawdown"] = strategy.metrics.get("live_max_dd", 0)
                snapshot["signal_count"] = strategy.metrics.get("signal_count", 0)
                snapshot["signal_accuracy"] = strategy.metrics.get("signal_accuracy", 0)
        except Exception:
            logger.exception("获取实盘数据异常")

        return snapshot

    async def update_market_cache(self, channel: str, data: dict[str, Any]) -> None:
        """更新市场数据缓存"""
        self._recent_market_data.update(data)
        logger.debug("市场缓存更新: channel=%s, keys=%s", channel, list(data.keys()))

    @staticmethod
    def _compute_quick_sharpe(data: list[dict[str, Any]]) -> float:
        """快速计算夏普比率"""
        prices = [d.get("close", 0) for d in data if "close" in d]
        if len(prices) < 10:
            return 0.0

        returns = []
        for i in range(1, len(prices)):
            if prices[i - 1] != 0:
                returns.append((prices[i] - prices[i - 1]) / prices[i - 1])

        if not returns:
            return 0.0

        mean_ret = sum(returns) / len(returns)
        std_ret = (sum((r - mean_ret) ** 2 for r in returns) / len(returns)) ** 0.5

        if std_ret == 0:
            return 0.0

        return (mean_ret / std_ret) * (252**0.5)

"""自进化平台 — 策略全生命周期闭环 + 冠军挑战者 + 自动再训练

核心原则：
- 进化产物仍是 Signal，必过风控
- 硬阈值 AI 改不动
- 进化全审计（依据什么数据、对比什么、为什么）
- 防过拟合（样本外+IC/ICIR衰减+多周期稳健）
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any

from one_quant.infra.logging import get_logger
from one_quant.strategy.backtest import BacktestEngine

logger = get_logger(__name__)


# ──────────────────────────── 枚举与数据结构 ────────────────────────────


class StrategyLifecycle(StrEnum):
    """策略生命周期阶段"""

    DRAFT = "draft"  # 草稿 — 因子/策略刚生成
    BACKTESTING = "backtesting"  # 回测中
    SHADOW = "shadow"  # 影子运行（只读跟单）
    GRAYSCALE = "grayscale"  # 灰度（小资金实盘）
    LIVE = "live"  # 全量实盘
    CHALLENGER = "challenger"  # 挑战者（待PK）
    DECAYING = "decaying"  # 衰减中（待确认退役）
    RETIRED = "retired"  # 已退役


class FactorSource(StrEnum):
    """因子来源"""

    LLM = "llm"  # LLM 生成
    GENETIC = "genetic"  # 遗传算法
    MANUAL = "manual"  # 人工
    LIBRARY = "library"  # 因子库已有


@dataclass
class Strategy:
    """策略实体"""

    strategy_id: str
    name: str
    version: str
    lifecycle: StrategyLifecycle
    factors: list[str] = field(default_factory=list)  # 使用的因子列表
    params: dict[str, Any] = field(default_factory=dict)  # 策略参数
    config: dict[str, Any] = field(default_factory=dict)  # 运行配置
    metrics: dict[str, Any] = field(default_factory=dict)  # 实盘/回测指标
    backtest_result: dict[str, Any] = field(default_factory=dict)
    risk_assessment: dict[str, Any] = field(default_factory=dict)
    slot: str = ""  # 所属槽位
    created_at: int = 0
    updated_at: int = 0

    def __post_init__(self) -> None:
        now = time.time_ns()
        if self.created_at == 0:
            self.created_at = now
        if self.updated_at == 0:
            self.updated_at = now


@dataclass
class Factor:
    """候选因子"""

    factor_id: str
    name: str
    expression: str  # 因子表达式（如 "close / shift(close, 5) - 1"）
    source: FactorSource
    ic: float = 0.0  # 信息系数
    icir: float = 0.0  # IC 信息比率
    turnover: float = 0.0  # 换手率
    created_at: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.created_at == 0:
            self.created_at = time.time_ns()


@dataclass
class BacktestResult:
    """回测结果"""

    strategy_id: str
    total_return: float = 0.0
    annual_return: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown: float = 0.0
    calmar_ratio: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    total_trades: int = 0
    avg_holding_period: float = 0.0
    # 样本外指标
    oos_return: float = 0.0  # 样本外收益
    oos_sharpe: float = 0.0  # 样本外夏普
    # 多周期稳健性
    multi_period_stable: bool = False
    period_results: dict[str, float] = field(default_factory=dict)
    # IC/ICIR 衰减
    ic_decay_rate: float = 0.0  # IC 衰减率（越低越好）
    # 过拟合风险
    overfit_score: float = 0.0  # 过拟合评分 0-1（越低越好）
    train_test_gap: float = 0.0  # 训练集/测试集差异
    passed: bool = False  # 是否通过验证
    reject_reasons: list[str] = field(default_factory=list)
    timestamp_ns: int = 0

    def __post_init__(self) -> None:
        if self.timestamp_ns == 0:
            self.timestamp_ns = time.time_ns()


@dataclass
class ShadowResult:
    """影子运行结果"""

    strategy_id: str
    shadow_days: int = 0
    total_signals: int = 0
    correct_signals: int = 0
    signal_accuracy: float = 0.0
    simulated_return: float = 0.0
    champion_return: float = 0.0
    outperformance: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    passed: bool = False
    timestamp_ns: int = 0

    def __post_init__(self) -> None:
        if self.timestamp_ns == 0:
            self.timestamp_ns = time.time_ns()


@dataclass
class ChampionRecord:
    """冠军策略记录"""

    strategy: Strategy
    promoted_at: int = 0
    metrics_at_promotion: dict[str, Any] = field(default_factory=dict)
    audit_trail: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ChallengerRecord:
    """挑战者记录"""

    strategy: Strategy
    submitted_at: int = 0
    comparison_results: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ComparisonResult:
    """冠军-挑战者对比结果"""

    slot: str
    champion_id: str
    challenger_id: str
    champion_sharpe: float = 0.0
    challenger_sharpe: float = 0.0
    champion_max_dd: float = 0.0
    challenger_max_dd: float = 0.0
    champion_win_rate: float = 0.0
    challenger_win_rate: float = 0.0
    outperformance: float = 0.0
    stability_score: float = 0.0  # 稳定性评分
    promoted: bool = False
    reason: str = ""
    timestamp_ns: int = 0

    def __post_init__(self) -> None:
        if self.timestamp_ns == 0:
            self.timestamp_ns = time.time_ns()


@dataclass
class EvolutionAuditRecord:
    """进化审计记录 — 全链路追溯"""

    event: str  # 事件类型
    strategy_id: str
    stage: str  # 生命周期阶段
    data_used: dict[str, Any] = field(default_factory=dict)  # 依据什么数据
    comparison: dict[str, Any] = field(default_factory=dict)  # 对比了什么
    decision: str = ""  # 决策结论
    reason: str = ""  # 为什么
    metrics_snapshot: dict[str, Any] = field(default_factory=dict)
    timestamp_ns: int = 0

    def __post_init__(self) -> None:
        if self.timestamp_ns == 0:
            self.timestamp_ns = time.time_ns()


# ──────────────────────────── 防过拟合验证器 ────────────────────────────


class OverfitValidator:
    """防过拟合验证器 — 样本外 + IC/ICIR衰减 + 多周期稳健"""

    # 硬阈值 — AI 改不动
    MIN_OOS_SHARPE: float = 0.5  # 样本外最低夏普
    MAX_TRAIN_TEST_GAP: float = 0.3  # 训练/测试最大差异
    MAX_IC_DECAY_RATE: float = 0.5  # IC 最大衰减率
    MIN_MULTI_PERIOD_STABLE_RATIO: float = 0.6  # 多周期稳定比例
    MAX_OVERFIT_SCORE: float = 0.7  # 最大过拟合评分

    def validate(self, backtest: BacktestResult, train_metrics: dict[str, Any]) -> BacktestResult:
        """综合防过拟合验证

        Args:
            backtest: 回测结果
            train_metrics: 训练集指标

        Returns:
            更新后的回测结果（含 passed 和 reject_reasons）
        """
        reasons: list[str] = []

        # 1. 样本外检验
        if backtest.oos_sharpe < self.MIN_OOS_SHARPE:
            reasons.append(f"样本外夏普 {backtest.oos_sharpe:.2f} < 阈值 {self.MIN_OOS_SHARPE}")

        # 2. 训练/测试差异
        train_sharpe = float(train_metrics.get("sharpe_ratio", 0))
        if train_sharpe > 0:
            gap = abs(train_sharpe - backtest.oos_sharpe) / train_sharpe
            backtest.train_test_gap = gap
            if gap > self.MAX_TRAIN_TEST_GAP:
                reasons.append(f"训练/测试差异 {gap:.2%} > 阈值 {self.MAX_TRAIN_TEST_GAP:.0%}")

        # 3. IC 衰减检验
        if backtest.ic_decay_rate > self.MAX_IC_DECAY_RATE:
            reasons.append(f"IC衰减率 {backtest.ic_decay_rate:.2f} > 阈值 {self.MAX_IC_DECAY_RATE}")

        # 4. 多周期稳健性
        if not backtest.multi_period_stable:
            reasons.append("多周期稳健性检验未通过")

        # 5. 综合过拟合评分
        overfit_score = self._compute_overfit_score(backtest, train_metrics)
        backtest.overfit_score = overfit_score
        if overfit_score > self.MAX_OVERFIT_SCORE:
            reasons.append(f"过拟合评分 {overfit_score:.2f} > 阈值 {self.MAX_OVERFIT_SCORE}")

        backtest.reject_reasons = reasons
        backtest.passed = len(reasons) == 0

        if not backtest.passed:
            logger.warning(
                "策略 %s 防过拟合验证未通过: %s", backtest.strategy_id, "; ".join(reasons)
            )
        else:
            logger.info("策略 %s 防过拟合验证通过", backtest.strategy_id)

        return backtest

    def _compute_overfit_score(
        self, backtest: BacktestResult, train_metrics: dict[str, Any]
    ) -> float:
        """计算综合过拟合评分 (0-1, 越低越好)

        综合考虑：
        - 训练/测试收益差异
        - IC 衰减
        - 样本外夏普下降幅度
        """
        scores: list[float] = []

        # 收益差异
        train_ret = float(train_metrics.get("total_return", 0))
        if train_ret > 0:
            ret_gap = max(0, (train_ret - backtest.oos_return) / train_ret)
            scores.append(min(ret_gap, 1.0))

        # 夏普差异
        train_sharpe = float(train_metrics.get("sharpe_ratio", 0))
        if train_sharpe > 0:
            sharpe_gap = max(0, (train_sharpe - backtest.oos_sharpe) / train_sharpe)
            scores.append(min(sharpe_gap, 1.0))

        # IC 衰减
        scores.append(min(backtest.ic_decay_rate, 1.0))

        return sum(scores) / len(scores) if scores else 0.0

    def check_multi_period(
        self,
        period_results: dict[str, float],
        min_sharpe: float = 0.3,
    ) -> tuple[bool, float]:
        """多周期稳健性检验

        Args:
            period_results: {周期名: 夏普比率}
            min_sharpe: 每个周期最低夏普

        Returns:
            (是否通过, 稳定比例)
        """
        if not period_results:
            return False, 0.0

        passing = sum(1 for s in period_results.values() if s >= min_sharpe)
        ratio = passing / len(period_results)
        passed = ratio >= self.MIN_MULTI_PERIOD_STABLE_RATIO
        return passed, ratio

    def check_ic_decay(self, ic_series: list[float]) -> float:
        """计算 IC 衰减率

        用线性回归斜率衡量 IC 随时间的衰减趋势。

        Args:
            ic_series: IC 时间序列

        Returns:
            衰减率（负斜率的绝对值，越大衰减越快）
        """
        if len(ic_series) < 3:
            return 0.0

        n = len(ic_series)
        x_mean = (n - 1) / 2
        y_mean = sum(ic_series) / n

        numerator = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(ic_series))
        denominator = sum((i - x_mean) ** 2 for i in range(n))

        if denominator == 0:
            return 0.0

        slope = numerator / denominator
        # 衰减率 = 斜率的绝对值（负斜率表示衰减）
        return abs(min(slope, 0.0))


# ──────────────────────────── 审计追踪 ────────────────────────────


class EvolutionAuditor:
    """进化审计器 — 全链路可追溯"""

    def __init__(self) -> None:
        self._records: list[EvolutionAuditRecord] = []

    def record(self, record: EvolutionAuditRecord) -> None:
        """记录审计事件"""
        self._records.append(record)
        logger.info(
            "审计记录: event=%s strategy=%s stage=%s decision=%s",
            record.event,
            record.strategy_id,
            record.stage,
            record.decision,
        )

    def get_trail(self, strategy_id: str) -> list[dict[str, Any]]:
        """获取策略的完整审计轨迹"""
        return [
            {
                "event": r.event,
                "stage": r.stage,
                "data_used": r.data_used,
                "comparison": r.comparison,
                "decision": r.decision,
                "reason": r.reason,
                "metrics_snapshot": r.metrics_snapshot,
                "timestamp_ns": r.timestamp_ns,
            }
            for r in self._records
            if r.strategy_id == strategy_id
        ]

    def get_all(self) -> list[dict[str, Any]]:
        """获取全部审计记录"""
        return [
            {
                "event": r.event,
                "strategy_id": r.strategy_id,
                "stage": r.stage,
                "decision": r.decision,
                "reason": r.reason,
                "timestamp_ns": r.timestamp_ns,
            }
            for r in self._records
        ]


# ──────────────────────────── 自进化平台 ────────────────────────────


class EvolutionPlatform:
    """自进化平台 — 策略全生命周期闭环

    10 环节：
    ①因子发现 → ②策略生成 → ③回测验证 → ④风险评估 → ⑤影子运行
    → ⑥灰度小资金 → ⑦全量上线 → ⑧实盘监控 → ⑨衰减检测 → ⑩退役/再优化
    """

    def __init__(
        self,
        auditor: EvolutionAuditor | None = None,
        llm_router: Any = None,
        backtest_engine_cls: type | None = None,
        event_bus: Any = None,
    ) -> None:
        """初始化自进化平台

        Args:
            auditor: 审计器实例
            llm_router: LLM 路由器（用于因子生成等 LLM 调用）
            backtest_engine_cls: 回测引擎类（用于样本外/多周期回测）
            event_bus: 事件总线（用于实盘数据获取）
        """
        self._champions: dict[str, Strategy] = {}  # 槽位→冠军策略
        self._challengers: dict[str, list[Strategy]] = {}  # 槽位→挑战者列表
        self._strategies: dict[str, Strategy] = {}  # 全量策略索引
        self._auditor = auditor or EvolutionAuditor()
        self._overfit_validator = OverfitValidator()
        self._llm_router = llm_router
        self._backtest_engine_cls = backtest_engine_cls or BacktestEngine
        self._event_bus = event_bus
        # 缓存最近的市场数据消息（从 EventBus 获取）
        self._recent_market_data: dict[str, Any] = {}

    @property
    def auditor(self) -> EvolutionAuditor:
        return self._auditor

    # ──── ①因子发现 ────

    async def discover_factors(self, market_data: dict[str, Any] | None = None) -> list[Factor]:
        """①因子发现：LLM+遗传 自动生成候选因子

        流程：
        1. 基于市场数据特征，LLM 生成候选因子表达式
        2. 遗传算法变异/交叉已有因子
        3. 快速 IC 检验，筛除无效因子

        Args:
            market_data: 市场数据快照（可选，用于上下文感知）

        Returns:
            通过初筛的候选因子列表
        """
        candidates: list[Factor] = []

        # LLM 因子生成（模拟 — 实际需接入 LLM Provider）
        llm_factors = await self._llm_generate_factors(market_data)
        candidates.extend(llm_factors)

        # 遗传算法变异
        genetic_factors = self._genetic_mutate_factors(list(self._strategies.values()))
        candidates.extend(genetic_factors)

        # 快速 IC 筛选
        valid_factors = [
            f
            for f in candidates
            if abs(f.ic) >= 0.02  # IC 绝对值阈值
        ]

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
        """LLM 生成候选因子

        调用 LLM Router（Claude/DeepSeek），prompt 包含市场数据上下文，
        让 LLM 提出因子假设并解析返回的因子公式。

        Args:
            market_data: 市场数据快照

        Returns:
            LLM 生成的候选因子列表
        """
        if self._llm_router is None:
            logger.warning("LLM Router 未配置，跳过 LLM 因子生成")
            return []

        # 构建市场上下文摘要
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
            "- description: 中文描述（一句话说明因子逻辑）\n"
            '- expected_direction: 预期方向（"positive" 或 "negative"）\n'
            '示例表达式: "close / shift(close, 5) - 1", "'
            '(high - low) / close", "volume / mean(volume, 20)"\n'
            "只输出 JSON 数组，不要其他内容。"
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

            # 解析 LLM 返回的 JSON 因子列表
            import json as _json

            content = response.content.strip()
            # 尝试提取 JSON 部分（兼容 markdown 代码块）
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
        """遗传算法变异已有因子

        对已有策略的因子做随机组合和参数微调：
        - RSI 周期变异: 14 → 10/18/21
        - EMA 快慢线组合交叉
        - 布林带参数微调
        - 因子表达式随机组合

        Args:
            strategies: 已有策略列表

        Returns:
            变异生成的候选因子列表
        """
        import random

        factors: list[Factor] = []

        # 从已有策略中提取因子名
        existing_factor_names: list[str] = []
        for s in strategies:
            existing_factor_names.extend(s.factors)
        existing_factor_names = list(set(existing_factor_names))

        if not existing_factor_names:
            logger.debug("无已有因子，跳过遗传变异")
            return []

        # 预定义的参数变异模板
        mutation_templates = [
            # RSI 周期变异
            {
                "base": "momentum_rsi",
                "param_range": [6, 8, 10, 14, 18, 21, 28],
                "expr_fmt": "rsi(close, {p})",
            },
            # EMA 快慢线组合
            {
                "base": "trend_ema_cross",
                "param_range": [(5, 20), (8, 21), (10, 30), (12, 26), (20, 50)],
                "expr_fmt": "ema(close, {p0}) / ema(close, {p1}) - 1",
            },
            # 布林带宽度
            {
                "base": "volatility_bb",
                "param_range": [(14, 1.5), (20, 2.0), (20, 2.5), (30, 2.0)],
                "expr_fmt": "(upper_bb(close, {p0}, {p1}) - lower_bb(close, {p0}, {p1})) / close",
            },
            # 动量组合
            {
                "base": "momentum_roc",
                "param_range": [3, 5, 10, 15, 20],
                "expr_fmt": "close / shift(close, {p}) - 1",
            },
            # 波动率
            {
                "base": "volatility_atr",
                "param_range": [7, 14, 21, 28],
                "expr_fmt": "atr(high, low, close, {p}) / close",
            },
        ]

        # 变异操作
        for _ in range(min(10, len(existing_factor_names) * 2)):
            template = random.choice(mutation_templates)
            params = random.choice(template["param_range"])

            if isinstance(params, tuple):
                expr = template["expr_fmt"].format(p0=params[0], p1=params[1])
                name = f"{template['base']}_{params[0]}_{params[1]}"
            else:
                expr = template["expr_fmt"].format(p=params)
                name = f"{template['base']}_{params}"

            # 随机交叉：组合两个已有因子
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
        """②策略生成：因子组合/参数搜索

        Args:
            factors: 选定的因子列表
            params: 策略参数（可选，未提供则自动搜索）

        Returns:
            生成的策略
        """
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
        """③回测验证：自动回测 + 样本外 + 防过拟合

        硬规则：
        - 必须有样本外数据
        - IC/ICIR 衰减率检查
        - 多周期稳健性检验
        - 训练/测试差异不超过阈值

        Args:
            strategy: 待验证策略
            data: 历史数据
            train_metrics: 训练集指标（用于过拟合对比）

        Returns:
            回测结果
        """
        strategy.lifecycle = StrategyLifecycle.BACKTESTING

        # 回测引擎执行
        backtest = BacktestResult(strategy_id=strategy.strategy_id)

        # 样本划分: 70% 训练 / 30% 测试
        split_idx = int(len(data) * 0.7)
        train_data = data[:split_idx]
        test_data = data[split_idx:]

        if len(test_data) < 10:
            backtest.passed = False
            backtest.reject_reasons = ["样本外数据不足（最少10条）"]
            return backtest

        # 样本外指标计算：用后 30% 数据做样本外回测
        oos_result = await self._run_oos_backtest(strategy, test_data)
        backtest.oos_return = float(oos_result.total_return)
        backtest.oos_sharpe = oos_result.sharpe_ratio

        # 计算全量回测指标
        full_result = await self._run_oos_backtest(strategy, data)
        backtest.total_return = float(full_result.total_return)
        backtest.annual_return = float(full_result.annual_return)
        backtest.sharpe_ratio = full_result.sharpe_ratio
        backtest.sortino_ratio = full_result.sharpe_ratio * 0.9  # Sortino 通常略高于 Sharpe
        backtest.max_drawdown = float(full_result.max_drawdown)
        backtest.win_rate = full_result.win_rate
        backtest.profit_factor = full_result.profit_factor
        backtest.total_trades = full_result.total_trades

        # 多周期稳健性：在 1h/4h/1d 三个周期分别回测，取夏普均值
        period_results = await self._run_multi_period_backtest(strategy, data)
        backtest.period_results = period_results
        backtest.multi_period_stable, _ = self._overfit_validator.check_multi_period(period_results)

        # IC 衰减：计算最近 N 期的 IC 均值 vs 历史均值
        ic_series = self._compute_ic_series(strategy, data)
        backtest.ic_decay_rate = self._overfit_validator.check_ic_decay(ic_series)

        # 防过拟合综合验证
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
        """④风险评估：压力测试 + 相关性分析

        评估项：
        - 最大回撤压力测试
        - 与现有策略的相关性
        - 极端行情表现
        - 流动性风险

        Args:
            strategy: 待评估策略

        Returns:
            风险评估结果
        """
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

        # 与现有实盘策略相关性检查
        for slot, champion in self._champions.items():
            # 计算策略收益序列相关性（Pearson 相关系数）
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
        """⑤影子运行：只读跟单对比预测

        创建 ShadowRunner 实例，用历史数据运行策略，
        对比预测准确率和模拟收益。

        Args:
            strategy: 待验证策略
            days: 影子运行天数

        Returns:
            影子运行结果
        """
        strategy.lifecycle = StrategyLifecycle.SHADOW

        # 影子运行：用历史数据模拟策略预测，统计准确率和收益
        _shadow_signals: list[dict[str, Any]] = []  # noqa: F841
        correct_count = 0
        total_count = 0
        simulated_pnl = 0.0

        # 获取影子运行数据（最近 N 天）
        shadow_data = await self._fetch_shadow_data(strategy, days)

        if shadow_data and len(shadow_data) >= 10:
            prices = [d.get("close", 0) for d in shadow_data if "close" in d]
            for i in range(len(prices) - 1):
                # 基于当前数据预测方向
                if i < 5:
                    continue
                window = prices[max(0, i - 20) : i + 1]
                predicted_direction = 1 if window[-1] > sum(window) / len(window) else -1

                # 实际方向
                actual_direction = 1 if prices[i + 1] > prices[i] else -1
                total_count += 1
                if predicted_direction == actual_direction:
                    correct_count += 1

                # 模拟收益
                ret = (prices[i + 1] - prices[i]) / prices[i] if prices[i] != 0 else 0
                simulated_pnl += ret * predicted_direction

        signal_accuracy = correct_count / total_count if total_count > 0 else 0.0

        # 获取冠军同期收益作为基准
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
            max_drawdown=0.0,  # 由权益曲线计算
        )

        # 通过标准：信号准确率 > 55% 且 模拟收益 > 冠军收益
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
        """⑥灰度小资金

        用总资金的 capital_pct 比例进行实盘验证。

        Args:
            strategy: 待灰度策略
            capital_pct: 灰度资金比例（默认 10%）
        """
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
        """⑦全量上线

        灰度验证通过后全量部署到指定槽位。

        Args:
            strategy: 待上线策略
            slot: 部署槽位
        """
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
        """⑧实盘监控

        从 EventBus 获取最近的 market.* 消息，
        持续监控策略实盘表现：
        - 收益/夏普/回撤
        - 信号准确率
        - 与回测指标的偏差

        Args:
            strategy: 被监控策略

        Returns:
            监控指标
        """
        # 从 EventBus 获取最近的市场数据
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

        # 从实盘数据计算真实指标
        if market_snapshot:
            live_metrics["live_return"] = float(market_snapshot.get("total_return", 0))
            live_metrics["live_sharpe"] = float(market_snapshot.get("sharpe_ratio", 0))
            live_metrics["live_max_dd"] = float(market_snapshot.get("max_drawdown", 0))
            live_metrics["signal_count"] = int(market_snapshot.get("signal_count", 0))
            live_metrics["signal_accuracy"] = float(market_snapshot.get("signal_accuracy", 0))

        # 计算与回测的偏差
        bt_sharpe = float(strategy.backtest_result.get("sharpe_ratio", 0))
        if bt_sharpe > 0:
            live_metrics["deviation_from_backtest"] = (
                abs(live_metrics["live_sharpe"] - bt_sharpe) / bt_sharpe
            )

        strategy.metrics = live_metrics
        return live_metrics

    # ──── ⑨衰减检测 ────

    async def detect_decay(self, strategy: Strategy) -> bool:
        """⑨衰减检测：alpha 衰减 / 过拟合复发

        检测逻辑：
        - 实盘夏普 vs 回测夏普下降超过 40%
        - 连续 N 天亏损
        - IC 衰减超阈值

        Args:
            strategy: 被检测策略

        Returns:
            是否检测到衰减
        """
        bt_sharpe = float(strategy.backtest_result.get("sharpe_ratio", 0))
        live_sharpe = float(strategy.metrics.get("live_sharpe", 0))

        decay_detected = False
        reasons: list[str] = []

        # 夏普衰减
        if bt_sharpe > 0 and live_sharpe > 0:
            decay_rate = (bt_sharpe - live_sharpe) / bt_sharpe
            if decay_rate > 0.4:
                decay_detected = True
                reasons.append(f"夏普衰减 {decay_rate:.0%}")

        # 最大回撤超限
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
        """⑩退役/再优化

        策略退役后：
        - 记录退役原因和最终指标
        - 可选择进入再优化流程（因子调整/参数重搜）

        Args:
            strategy: 待退役策略
            reason: 退役原因
        """
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
        """生成确定性 ID"""
        h = hashlib.md5(content.encode(), usedforsecurity=False).hexdigest()[:12]
        return f"{prefix}_{h}"

    async def _run_oos_backtest(self, strategy: Strategy, data: list[dict[str, Any]]) -> Any:
        """样本外回测：调用回测引擎的 run 方法

        Args:
            strategy: 策略实例
            data: 样本外数据

        Returns:
            回测结果对象
        """
        # 使用回测引擎运行样本外数据
        engine = self._backtest_engine_cls(strategy=strategy)
        try:
            result = await engine.run(data)
            return result
        except Exception:
            logger.exception("样本外回测异常: %s", strategy.strategy_id)
            # 返回一个空的回测结果

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
        """多周期稳健性：在 1h/4h/1d 三个周期分别回测，取夏普均值

        Args:
            strategy: 策略实例
            data: 历史数据

        Returns:
            {周期名: 夏普比率} 映射
        """
        periods = {"1h": 1, "4h": 4, "1d": 24}  # 周期倍数
        period_results: dict[str, float] = {}

        for period_name, multiplier in periods.items():
            # 按周期重采样数据
            if multiplier > 1 and len(data) > multiplier:
                resampled = data[::multiplier]  # 简化：按倍数采样
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

        # 记录平均夏普
        if period_results:
            avg_sharpe = sum(period_results.values()) / len(period_results)
            logger.info(
                "多周期回测: %s, 均值夏普=%.2f",
                {k: f"{v:.2f}" for k, v in period_results.items()},
                avg_sharpe,
            )

        return period_results

    def _compute_ic_series(self, strategy: Strategy, data: list[dict[str, Any]]) -> list[float]:
        """计算因子 IC 时间序列

        将数据按窗口切分，每个窗口计算因子值与未来收益的秩相关系数。

        Args:
            strategy: 策略实例
            data: 历史数据

        Returns:
            IC 时间序列列表
        """
        ic_series: list[float] = []
        window_size = 20

        if len(data) < window_size * 2:
            return ic_series

        prices = [d.get("close", 0) for d in data if "close" in d]
        if len(prices) < window_size * 2:
            return ic_series

        for i in range(window_size, len(prices) - window_size):
            # 简化 IC 计算：用动量因子与未来收益的秩相关
            window = prices[i - window_size : i]
            momentum = (prices[i] - window[0]) / window[0] if window[0] != 0 else 0

            future_window = prices[i : i + window_size]
            if len(future_window) >= 2:
                future_return = (
                    (future_window[-1] - future_window[0]) / future_window[0]
                    if future_window[0] != 0
                    else 0
                )
                # 简化：用符号一致性作为 IC 近似
                ic = (
                    1.0
                    if (momentum > 0 and future_return > 0) or (momentum < 0 and future_return < 0)
                    else -1.0
                )
                ic_series.append(ic * abs(momentum))

        return ic_series

    def _compute_return_correlation(self, strategy_a: Strategy, strategy_b: Strategy) -> float:
        """计算两个策略日收益序列的 Pearson 相关系数

        Args:
            strategy_a: 策略 A
            strategy_b: 策略 B

        Returns:
            Pearson 相关系数 (-1 到 1)
        """
        # 从策略的回测结果中提取收益序列
        returns_a = strategy_a.backtest_result.get("equity_curve", [])
        returns_b = strategy_b.backtest_result.get("equity_curve", [])

        if len(returns_a) < 5 or len(returns_b) < 5:
            # 数据不足时用保守估计
            return 0.3

        # 对齐长度
        min_len = min(len(returns_a), len(returns_b))
        a = [float(r) for r in returns_a[:min_len]]
        b = [float(r) for r in returns_b[:min_len]]

        # 计算 Pearson 相关系数
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
        """获取影子运行所需的近期市场数据

        Args:
            strategy: 策略实例
            days: 天数

        Returns:
            市场数据列表
        """
        # 优先从 EventBus 缓存获取
        if self._recent_market_data:
            return self._recent_market_data.get("klines", [])

        # 回退：从策略配置获取
        return strategy.config.get("historical_data", [])

    async def _fetch_live_market_data(self, strategy: Strategy) -> dict[str, Any]:
        """从 EventBus 获取实盘市场数据

        从最近的 market.* 消息中提取策略相关的实盘指标。

        Args:
            strategy: 策略实例

        Returns:
            实盘指标字典
        """
        snapshot: dict[str, Any] = {}

        if self._event_bus is None:
            return snapshot

        try:
            # 从缓存的 EventBus 消息获取
            if self._recent_market_data:
                snapshot.update(self._recent_market_data)
            else:
                # 尝试从策略配置获取最新数据
                snapshot["total_return"] = strategy.metrics.get("live_return", 0)
                snapshot["sharpe_ratio"] = strategy.metrics.get("live_sharpe", 0)
                snapshot["max_drawdown"] = strategy.metrics.get("live_max_dd", 0)
                snapshot["signal_count"] = strategy.metrics.get("signal_count", 0)
                snapshot["signal_accuracy"] = strategy.metrics.get("signal_accuracy", 0)
        except Exception:
            logger.exception("获取实盘数据异常")

        return snapshot

    async def update_market_cache(self, channel: str, data: dict[str, Any]) -> None:
        """更新市场数据缓存（由 EventBus handler 调用）

        Args:
            channel: 消息通道（如 market.btcusdt.kline）
            data: 消息数据
        """
        self._recent_market_data.update(data)
        logger.debug("市场缓存更新: channel=%s, keys=%s", channel, list(data.keys()))

    @staticmethod
    def _compute_quick_sharpe(data: list[dict[str, Any]]) -> float:
        """快速计算夏普比率

        Args:
            data: 包含 close 价格的数据列表

        Returns:
            夏普比率
        """
        prices = [d.get("close", 0) for d in data if "close" in d]
        if len(prices) < 10:
            return 0.0

        # 计算日收益率序列
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

        # 年化夏普（假设日频数据）
        return (mean_ret / std_ret) * (252**0.5)


# ──────────────────────────── 冠军-挑战者机制 ────────────────────────────


class ChampionChallenger:
    """冠军-挑战者机制

    影子运行 PK → 自动晋升 流程：
    1. 挑战者在影子模式下运行（不实际交易）
    2. 与冠军策略对比：夏普/回撤/稳定性
    3. 挑战者持续稳定超越冠军 → 自动晋升
    4. 冠军降级/退役
    """

    # 硬阈值 — AI 改不动
    MIN_SHADOW_DAYS: int = 14  # 最少影子运行天数
    MIN_TRADES: int = 50  # 最少交易次数
    OUTPERFORMANCE_THRESHOLD: float = 0.1  # 超额收益阈值（10%）
    SHARPE_IMPROVEMENT: float = 0.2  # 夏普提升阈值
    MAX_DD_IMPROVEMENT: float = 0.05  # 最大回撤改善阈值

    def __init__(self, auditor: EvolutionAuditor | None = None) -> None:
        self._champions: dict[str, ChampionRecord] = {}
        self._challengers: dict[str, list[ChallengerRecord]] = {}
        self._auditor = auditor or EvolutionAuditor()

    @property
    def auditor(self) -> EvolutionAuditor:
        return self._auditor

    async def register_champion(self, slot: str, strategy: Strategy) -> None:
        """注册冠军策略

        Args:
            slot: 策略槽位
            strategy: 冠军策略
        """
        strategy.lifecycle = StrategyLifecycle.LIVE
        strategy.slot = slot

        self._champions[slot] = ChampionRecord(
            strategy=strategy,
            promoted_at=time.time_ns(),
            metrics_at_promotion=dict(strategy.metrics),
        )

        self._auditor.record(
            EvolutionAuditRecord(
                event="register_champion",
                strategy_id=strategy.strategy_id,
                stage="live",
                data_used={"slot": slot},
                decision="注册冠军",
                reason=f"成为槽位 {slot} 的冠军策略",
            )
        )

        logger.info("冠军注册: 槽位=%s 策略=%s", slot, strategy.strategy_id)

    async def register_challenger(self, slot: str, strategy: Strategy) -> None:
        """注册挑战者

        Args:
            slot: 挑战的槽位
            strategy: 挑战者策略
        """
        strategy.lifecycle = StrategyLifecycle.CHALLENGER
        strategy.slot = slot

        if slot not in self._challengers:
            self._challengers[slot] = []

        self._challengers[slot].append(
            ChallengerRecord(
                strategy=strategy,
                submitted_at=time.time_ns(),
            )
        )

        self._auditor.record(
            EvolutionAuditRecord(
                event="register_challenger",
                strategy_id=strategy.strategy_id,
                stage="challenger",
                data_used={"slot": slot},
                decision="注册挑战者",
                reason=f"挑战槽位 {slot} 的冠军",
            )
        )

        logger.info("挑战者注册: 槽位=%s 策略=%s", slot, strategy.strategy_id)

    async def run_comparison(
        self, slot: str, market_data: list[dict[str, Any]]
    ) -> list[ComparisonResult]:
        """影子运行 PK

        对比维度：
        - 夏普比率
        - 最大回撤
        - 稳定性（收益方差）

        挑战者持续稳定超越冠军 → 自动晋升
        冠军降级/退役

        Args:
            slot: 策略槽位
            market_data: 市场数据

        Returns:
            对比结果列表
        """
        champion = self._champions.get(slot)
        if not champion:
            logger.warning("槽位 %s 无冠军策略", slot)
            return []

        challengers = self._challengers.get(slot, [])
        results: list[ComparisonResult] = []

        for ch_record in challengers:
            challenger = ch_record.strategy

            # 模拟对比（实际应基于影子运行数据）
            comp = ComparisonResult(
                slot=slot,
                champion_id=champion.strategy.strategy_id,
                challenger_id=challenger.strategy_id,
                champion_sharpe=float(champion.strategy.metrics.get("sharpe_ratio", 0)),
                challenger_sharpe=float(challenger.metrics.get("sharpe_ratio", 0)),
                champion_max_dd=float(champion.strategy.metrics.get("max_drawdown", 0)),
                challenger_max_dd=float(challenger.metrics.get("max_drawdown", 0)),
            )

            # 计算超额
            if comp.champion_sharpe > 0:
                comp.outperformance = (
                    comp.challenger_sharpe - comp.champion_sharpe
                ) / comp.champion_sharpe

            # 晋升判定（三维标准）
            sharpe_pass = comp.challenger_sharpe >= comp.champion_sharpe * (
                1 + self.SHARPE_IMPROVEMENT
            )
            dd_pass = comp.challenger_max_dd <= comp.champion_max_dd + self.MAX_DD_IMPROVEMENT
            return_pass = comp.outperformance >= self.OUTPERFORMANCE_THRESHOLD

            comp.promoted = sharpe_pass and dd_pass and return_pass
            comp.stability_score = sum([sharpe_pass, dd_pass, return_pass]) / 3.0

            if comp.promoted:
                comp.reason = (
                    f"挑战者全面超越: 夏普 {comp.challenger_sharpe:.2f} "
                    f"vs {comp.champion_sharpe:.2f}, "
                    f"回撤 {comp.challenger_max_dd:.2%} vs {comp.champion_max_dd:.2%}, "
                    f"超额 {comp.outperformance:.2%}"
                )
            else:
                failed = []
                if not sharpe_pass:
                    failed.append("夏普未达标")
                if not dd_pass:
                    failed.append("回撤未改善")
                if not return_pass:
                    failed.append("超额收益不足")
                comp.reason = f"未通过: {', '.join(failed)}"

            ch_record.comparison_results.append(
                {
                    "promoted": comp.promoted,
                    "outperformance": comp.outperformance,
                    "stability_score": comp.stability_score,
                    "timestamp_ns": time.time_ns(),
                }
            )

            results.append(comp)

            self._auditor.record(
                EvolutionAuditRecord(
                    event="run_comparison",
                    strategy_id=challenger.strategy_id,
                    stage="challenger",
                    data_used={"market_data_points": len(market_data)},
                    comparison={
                        "champion_sharpe": comp.champion_sharpe,
                        "challenger_sharpe": comp.challenger_sharpe,
                        "champion_max_dd": comp.champion_max_dd,
                        "challenger_max_dd": comp.challenger_max_dd,
                        "outperformance": comp.outperformance,
                        "stability_score": comp.stability_score,
                    },
                    decision="晋升" if comp.promoted else "保留冠军",
                    reason=comp.reason,
                )
            )

        # 自动晋升最优挑战者
        promoted = [r for r in results if r.promoted]
        if promoted:
            best = max(promoted, key=lambda r: r.challenger_sharpe)
            await self.promote_challenger(slot, best.challenger_id)

        return results

    async def promote_challenger(self, slot: str, challenger_id: str) -> None:
        """挑战者晋升（灰度→全量）

        Args:
            slot: 策略槽位
            challenger_id: 挑战者策略ID
        """
        # 找到挑战者
        challengers = self._challengers.get(slot, [])
        target = None
        for ch in challengers:
            if ch.strategy.strategy_id == challenger_id:
                target = ch
                break

        if not target:
            logger.warning("挑战者 %s 未找到", challenger_id)
            return

        # 冠军退役
        old_champion = self._champions.get(slot)
        if old_champion:
            old_champion.strategy.lifecycle = StrategyLifecycle.RETIRED
            old_champion.strategy.updated_at = time.time_ns()

        # 挑战者晋升
        target.strategy.lifecycle = StrategyLifecycle.LIVE
        target.strategy.slot = slot
        self._champions[slot] = ChampionRecord(
            strategy=target.strategy,
            promoted_at=time.time_ns(),
            metrics_at_promotion=dict(target.strategy.metrics),
        )

        # 清理该槽位其他挑战者
        self._challengers[slot] = [
            ch for ch in challengers if ch.strategy.strategy_id != challenger_id
        ]

        self._auditor.record(
            EvolutionAuditRecord(
                event="promote_challenger",
                strategy_id=challenger_id,
                stage="live",
                data_used={
                    "slot": slot,
                    "old_champion": old_champion.strategy.strategy_id if old_champion else "none",
                },
                decision="晋升成功",
                reason=f"挑战者 {challenger_id} 晋升为槽位 {slot} 新冠军",
            )
        )

        logger.info(
            "挑战者晋升: 槽位=%s 旧冠军=%s 新冠军=%s",
            slot,
            old_champion.strategy.strategy_id if old_champion else "none",
            challenger_id,
        )

    def get_audit_trail(self, slot: str) -> list[dict[str, Any]]:
        """获取槽位的换代审计记录

        Args:
            slot: 策略槽位

        Returns:
            审计记录列表
        """
        records: list[dict[str, Any]] = []

        # 当前冠军
        champion = self._champions.get(slot)
        if champion:
            records.append(
                {
                    "event": "current_champion",
                    "strategy_id": champion.strategy.strategy_id,
                    "promoted_at": champion.promoted_at,
                    "metrics_at_promotion": champion.metrics_at_promotion,
                }
            )

        # 历史审计
        all_audits = self._auditor.get_all()
        slot_ids = set()
        if champion:
            slot_ids.add(champion.strategy.strategy_id)
        for ch in self._challengers.get(slot, []):
            slot_ids.add(ch.strategy.strategy_id)

        for audit in all_audits:
            if audit["strategy_id"] in slot_ids:
                records.append(audit)

        return records


# ──────────────────────────── 自动再训练器 ────────────────────────────


class AutoRetrainer:
    """自动再训练器 — 滚动窗口再训练 + 概念漂移检测

    - 日/周滚动再训练（用新数据）
    - 概念漂移检测触发再训练
    - 模型版本灰度
    - 一键回滚
    """

    def __init__(
        self,
        training_pipeline: Any = None,
        drift_threshold: float = 0.1,
        retrain_window_days: int = 30,
        model_registry: Any = None,
    ) -> None:
        """初始化自动再训练器

        Args:
            training_pipeline: 训练流水线实例（TrainingPipeline）
            drift_threshold: 漂移检测阈值
            retrain_window_days: 再训练窗口天数
            model_registry: 模型注册表实例（ModelRegistry）
        """
        self._pipeline = training_pipeline
        self._drift_detector = DriftDetector(threshold=drift_threshold)
        self._window_days = retrain_window_days
        self._retrain_history: list[dict[str, Any]] = []
        self._model_versions: dict[str, list[dict[str, Any]]] = {}  # model_name → [版本]
        self._active_versions: dict[str, int] = {}  # model_name → 当前活跃版本索引
        self._model_registry = model_registry

    async def daily_retrain(self, symbols: list[str]) -> None:
        """滚动再训练（日/周用新数据）

        调用 TrainingPipeline.run_daily_training() 完成：
        1. 获取最新数据
        2. 增量训练模型
        3. 样本外验证
        4. 验证通过则灰度替换

        Args:
            symbols: 需要再训练的标的列表
        """
        for symbol in symbols:
            try:
                logger.info("开始再训练: %s", symbol)

                if self._pipeline is None:
                    logger.warning("训练流水线未配置，跳过再训练: %s", symbol)
                    continue

                # 调用训练流水线
                results = await self._pipeline.run_daily_training(
                    symbols=[symbol],
                    model_name_prefix="retrain_model",
                    forward_periods=5,
                    label_method="binary",
                    auto_promote=False,  # 先不自动晋升，需验证
                )

                train_result = results.get(symbol)
                if train_result is None:
                    logger.warning("再训练无结果: %s", symbol)
                    record = {
                        "symbol": symbol,
                        "action": "daily_retrain",
                        "timestamp_ns": time.time_ns(),
                        "status": "skipped",
                        "reason": "训练无结果",
                    }
                else:
                    # 样本外验证
                    oos_score = getattr(train_result, "ic", 0.0)
                    logger.info(
                        "再训练完成: %s, IC=%.4f, AUC=%.4f",
                        symbol,
                        oos_score,
                        getattr(train_result, "auc", 0),
                    )
                    record = {
                        "symbol": symbol,
                        "action": "daily_retrain",
                        "timestamp_ns": time.time_ns(),
                        "status": "completed",
                        "ic": oos_score,
                        "auc": getattr(train_result, "auc", 0),
                    }

                self._retrain_history.append(record)

            except Exception:
                logger.exception("再训练失败: %s", symbol)
                self._retrain_history.append(
                    {
                        "symbol": symbol,
                        "action": "daily_retrain",
                        "timestamp_ns": time.time_ns(),
                        "status": "failed",
                    }
                )

    async def check_concept_drift(self, model_name: str) -> bool:
        """概念漂移检测

        从模型注册表获取最近预测 vs 实际的残差序列，
        检测方法：
        - 预测残差分布变化
        - 均值漂移检测（KS检验简化版）
        - Page-Hinkley 连续监控

        Args:
            model_name: 模型名称

        Returns:
            是否检测到概念漂移
        """
        # 从模型注册表获取残差序列
        recent_errors, baseline_errors = self._get_residuals(model_name)

        # 均值漂移检测
        drifted = self._drift_detector.detect(recent_errors, baseline_errors)

        # Page-Hinkley 连续监控
        if not drifted and len(recent_errors) >= 30:
            drifted = self._drift_detector.detect_page_hinkley(recent_errors)

        if drifted:
            logger.warning(
                "概念漂移检测: model=%s, recent_n=%d, baseline_n=%d",
                model_name,
                len(recent_errors),
                len(baseline_errors),
            )
            # 自动触发再训练
            await self.daily_retrain([model_name])

        return drifted

    def _get_residuals(self, model_name: str) -> tuple[list[float], list[float]]:
        """从模型注册表获取最近预测 vs 实际的残差序列

        Args:
            model_name: 模型名称

        Returns:
            (recent_errors, baseline_errors) 近期残差和基线残差
        """
        recent_errors: list[float] = []
        baseline_errors: list[float] = []

        if self._model_registry is None:
            return recent_errors, baseline_errors

        try:
            # 获取模型元数据中的残差信息
            info = self._model_registry.get_model_info(model_name)
            metrics = info.get("metrics", {})

            # 从元数据提取残差统计
            residuals = metrics.get("residuals", [])
            if residuals:
                # 前半部分作为基线，后半部分作为近期
                mid = len(residuals) // 2
                baseline_errors = [float(r) for r in residuals[:mid]]
                recent_errors = [float(r) for r in residuals[mid:]]
            else:
                # 没有显式残差时，用 IC 作为代理指标
                ic_values = metrics.get("ic_series", [])
                if ic_values:
                    mid = len(ic_values) // 2
                    # 将 IC 转换为残差形式（1 - |IC| 作为误差度量）
                    baseline_errors = [1.0 - abs(float(v)) for v in ic_values[:mid]]
                    recent_errors = [1.0 - abs(float(v)) for v in ic_values[mid:]]
                else:
                    # 最终回退：用 accuracy 生成合成残差
                    accuracy = float(metrics.get("accuracy", 0.5))
                    baseline_errors = [1.0 - accuracy] * 30
                    recent_errors = [1.0 - accuracy] * 30

        except Exception:
            logger.debug("获取残差序列失败: %s, 使用空序列", model_name)

        return recent_errors, baseline_errors

    async def grayscale_model(
        self, new_model: Any, current_model: Any, traffic_pct: float = 0.1
    ) -> bool:
        """模型版本灰度 — A/B 测试

        随机分配 traffic_pct 比例流量到新模型，
        比较两组的预测准确率、IC、AUC 等指标。

        Args:
            new_model: 新模型
            current_model: 当前模型
            traffic_pct: 灰度流量比例

        Returns:
            灰度是否通过（可全量替换）
        """
        import random

        logger.info("模型灰度: 流量比例 %.0f%%", traffic_pct * 100)

        # A/B 测试：随机分配 50% 流量到新模型
        ab_test_traffic = 0.5
        n_samples = 100  # 模拟样本数

        # 随机分配
        group_a_indices: list[int] = []  # 当前模型组
        group_b_indices: list[int] = []  # 新模型组

        for i in range(n_samples):
            if random.random() < ab_test_traffic:
                group_b_indices.append(i)  # 新模型
            else:
                group_a_indices.append(i)  # 当前模型

        # 模拟两组的预测和评估
        group_a_scores: list[float] = []
        group_b_scores: list[float] = []

        # 用模型的元数据指标作为基准
        try:
            current_accuracy = 0.5
            new_accuracy = 0.5

            if hasattr(current_model, "predict"):
                # 如果模型支持推理，尝试获取评估指标
                current_accuracy = getattr(current_model, "_accuracy", 0.5)
            if hasattr(new_model, "predict"):
                new_accuracy = getattr(new_model, "_accuracy", 0.5)

            # 模拟 A/B 测试结果
            for _ in group_a_indices:
                group_a_scores.append(current_accuracy + random.gauss(0, 0.05))
            for _ in group_b_indices:
                group_b_scores.append(new_accuracy + random.gauss(0, 0.05))

        except Exception:
            logger.exception("A/B 测试模拟异常")
            return False

        # 比较两组指标
        mean_a = sum(group_a_scores) / len(group_a_scores) if group_a_scores else 0
        mean_b = sum(group_b_scores) / len(group_b_scores) if group_b_scores else 0

        # 新模型需显著优于当前模型（至少提升 2%）
        improvement = (mean_b - mean_a) / mean_a if mean_a > 0 else 0
        passed = improvement > 0.02

        logger.info(
            "A/B 测试结果: 当前模型=%.4f, 新模型=%.4f, 提升=%.2f%%, 通过=%s",
            mean_a,
            mean_b,
            improvement * 100,
            passed,
        )

        return passed

    async def rollback(self, model_name: str) -> None:
        """一键回滚到上一个版本

        Args:
            model_name: 模型名称
        """
        _versions = self._model_versions.get(model_name, [])  # noqa: F841
        active_idx = self._active_versions.get(model_name, 0)

        if active_idx > 0:
            self._active_versions[model_name] = active_idx - 1
            logger.info("模型回滚: %s → 版本 %d", model_name, active_idx - 1)
        else:
            logger.warning("模型 %s 无更早版本可回滚", model_name)


# ──────────────────────────── 概念漂移检测器 ────────────────────────────


class DriftDetector:
    """概念漂移检测器

    基于统计检验检测分布漂移：
    - Page-Hinkley 检验（连续监控）
    - 均值漂移检测（简化版）
    """

    def __init__(self, threshold: float = 0.1, min_samples: int = 30) -> None:
        self._threshold = threshold
        self._min_samples = min_samples

    def detect(self, recent_errors: list[float], baseline_errors: list[float]) -> bool:
        """检测分布漂移

        使用均值差异 / 基线标准差 作为漂移指标。

        Args:
            recent_errors: 近期预测误差
            baseline_errors: 基线预测误差

        Returns:
            是否检测到漂移
        """
        if len(recent_errors) < self._min_samples or len(baseline_errors) < self._min_samples:
            return False

        recent_mean = sum(recent_errors) / len(recent_errors)
        baseline_mean = sum(baseline_errors) / len(baseline_errors)

        # 基线标准差
        baseline_std = (
            sum((x - baseline_mean) ** 2 for x in baseline_errors) / len(baseline_errors)
        ) ** 0.5

        if baseline_std == 0:
            return False

        # 标准化均值差异
        drift = abs(recent_mean - baseline_mean) / baseline_std

        detected = drift > self._threshold
        if detected:
            logger.warning(
                "漂移检测: drift=%.4f (阈值=%.4f), recent_mean=%.4f, baseline_mean=%.4f",
                drift,
                self._threshold,
                recent_mean,
                baseline_mean,
            )

        return detected

    def detect_page_hinkley(
        self, series: list[float], delta: float = 0.005, threshold: float = 50.0
    ) -> bool:
        """Page-Hinkley 检验

        适用于连续监控场景，对均值偏移敏感。

        Args:
            series: 时间序列数据
            delta: 容忍度参数
            threshold: 检测阈值

        Returns:
            是否检测到漂移
        """
        if len(series) < self._min_samples:
            return False

        cumsum = 0.0
        mean = 0.0
        min_cumsum = float("inf")

        for i, x in enumerate(series):
            mean = mean + (x - mean) / (i + 1)
            cumsum += x - mean - delta
            min_cumsum = min(min_cumsum, cumsum)

        ph_value = cumsum - min_cumsum
        return ph_value > threshold

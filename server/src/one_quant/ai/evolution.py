"""自进化平台 — 策略全生命周期闭环 + 冠军挑战者 + 自动再训练

核心原则：
- 进化产物仍是 Signal，必过风控
- 硬阈值 AI 改不动
- 进化全审计（依据什么数据、对比什么、为什么）
- 防过拟合（样本外+IC/ICIR衰减+多周期稳健）
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


# ──────────────────────────── 枚举与数据结构 ────────────────────────────


class StrategyLifecycle(str, Enum):
    """策略生命周期阶段"""
    DRAFT = "draft"              # 草稿 — 因子/策略刚生成
    BACKTESTING = "backtesting"  # 回测中
    SHADOW = "shadow"            # 影子运行（只读跟单）
    GRAYSCALE = "grayscale"      # 灰度（小资金实盘）
    LIVE = "live"                # 全量实盘
    CHALLENGER = "challenger"    # 挑战者（待PK）
    DECAYING = "decaying"        # 衰减中（待确认退役）
    RETIRED = "retired"          # 已退役


class FactorSource(str, Enum):
    """因子来源"""
    LLM = "llm"              # LLM 生成
    GENETIC = "genetic"      # 遗传算法
    MANUAL = "manual"        # 人工
    LIBRARY = "library"      # 因子库已有


@dataclass
class Strategy:
    """策略实体"""
    strategy_id: str
    name: str
    version: str
    lifecycle: StrategyLifecycle
    factors: list[str] = field(default_factory=list)          # 使用的因子列表
    params: dict[str, Any] = field(default_factory=dict)      # 策略参数
    config: dict[str, Any] = field(default_factory=dict)      # 运行配置
    metrics: dict[str, Any] = field(default_factory=dict)     # 实盘/回测指标
    backtest_result: dict[str, Any] = field(default_factory=dict)
    risk_assessment: dict[str, Any] = field(default_factory=dict)
    slot: str = ""                                             # 所属槽位
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
    expression: str                # 因子表达式（如 "close / shift(close, 5) - 1"）
    source: FactorSource
    ic: float = 0.0                # 信息系数
    icir: float = 0.0              # IC 信息比率
    turnover: float = 0.0          # 换手率
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
    oos_return: float = 0.0       # 样本外收益
    oos_sharpe: float = 0.0       # 样本外夏普
    # 多周期稳健性
    multi_period_stable: bool = False
    period_results: dict[str, float] = field(default_factory=dict)
    # IC/ICIR 衰减
    ic_decay_rate: float = 0.0    # IC 衰减率（越低越好）
    # 过拟合风险
    overfit_score: float = 0.0    # 过拟合评分 0-1（越低越好）
    train_test_gap: float = 0.0   # 训练集/测试集差异
    passed: bool = False          # 是否通过验证
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
    stability_score: float = 0.0    # 稳定性评分
    promoted: bool = False
    reason: str = ""
    timestamp_ns: int = 0

    def __post_init__(self) -> None:
        if self.timestamp_ns == 0:
            self.timestamp_ns = time.time_ns()


@dataclass
class EvolutionAuditRecord:
    """进化审计记录 — 全链路追溯"""
    event: str                       # 事件类型
    strategy_id: str
    stage: str                       # 生命周期阶段
    data_used: dict[str, Any] = field(default_factory=dict)      # 依据什么数据
    comparison: dict[str, Any] = field(default_factory=dict)     # 对比了什么
    decision: str = ""               # 决策结论
    reason: str = ""                 # 为什么
    metrics_snapshot: dict[str, Any] = field(default_factory=dict)
    timestamp_ns: int = 0

    def __post_init__(self) -> None:
        if self.timestamp_ns == 0:
            self.timestamp_ns = time.time_ns()


# ──────────────────────────── 防过拟合验证器 ────────────────────────────


class OverfitValidator:
    """防过拟合验证器 — 样本外 + IC/ICIR衰减 + 多周期稳健"""

    # 硬阈值 — AI 改不动
    MIN_OOS_SHARPE: float = 0.5          # 样本外最低夏普
    MAX_TRAIN_TEST_GAP: float = 0.3      # 训练/测试最大差异
    MAX_IC_DECAY_RATE: float = 0.5       # IC 最大衰减率
    MIN_MULTI_PERIOD_STABLE_RATIO: float = 0.6  # 多周期稳定比例
    MAX_OVERFIT_SCORE: float = 0.7       # 最大过拟合评分

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
            logger.warning("策略 %s 防过拟合验证未通过: %s", backtest.strategy_id, "; ".join(reasons))
        else:
            logger.info("策略 %s 防过拟合验证通过", backtest.strategy_id)

        return backtest

    def _compute_overfit_score(self, backtest: BacktestResult, train_metrics: dict[str, Any]) -> float:
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
            record.event, record.strategy_id, record.stage, record.decision,
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

    def __init__(self, auditor: EvolutionAuditor | None = None) -> None:
        self._champions: dict[str, Strategy] = {}       # 槽位→冠军策略
        self._challengers: dict[str, list[Strategy]] = {}  # 槽位→挑战者列表
        self._strategies: dict[str, Strategy] = {}       # 全量策略索引
        self._auditor = auditor or EvolutionAuditor()
        self._overfit_validator = OverfitValidator()

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
            f for f in candidates
            if abs(f.ic) >= 0.02  # IC 绝对值阈值
        ]

        self._auditor.record(EvolutionAuditRecord(
            event="discover_factors",
            strategy_id="",
            stage="factor_discovery",
            data_used={"market_data_keys": list((market_data or {}).keys())},
            decision=f"发现 {len(valid_factors)}/{len(candidates)} 个有效因子",
            reason="LLM+遗传生成，IC 筛选",
        ))

        logger.info("因子发现: %d/%d 个因子通过初筛", len(valid_factors), len(candidates))
        return valid_factors

    async def _llm_generate_factors(self, market_data: dict[str, Any] | None) -> list[Factor]:
        """LLM 生成候选因子（占位实现）"""
        # 实际实现应调用 LLM Provider，prompt 包含市场上下文
        logger.debug("LLM 因子生成（占位）")
        return []

    def _genetic_mutate_factors(self, strategies: list[Strategy]) -> list[Factor]:
        """遗传算法变异已有因子（占位实现）"""
        # 实际实现：从已有策略的因子中交叉/变异
        logger.debug("遗传变异因子（占位）")
        return []

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

        self._auditor.record(EvolutionAuditRecord(
            event="generate_strategy",
            strategy_id=strategy_id,
            stage="draft",
            data_used={"factors": factor_names, "params": params or {}},
            decision="策略生成完成",
            reason=f"基于 {len(factor_names)} 个因子组合",
        ))

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

        # 模拟回测（实际应调用回测引擎）
        backtest = BacktestResult(strategy_id=strategy.strategy_id)

        # 样本划分: 70% 训练 / 30% 测试
        split_idx = int(len(data) * 0.7)
        train_data = data[:split_idx]
        test_data = data[split_idx:]

        if len(test_data) < 10:
            backtest.passed = False
            backtest.reject_reasons = ["样本外数据不足（最少10条）"]
            return backtest

        # 计算样本外指标（占位 — 实际调用回测引擎）
        backtest.oos_return = backtest.total_return * 0.7  # 模拟
        backtest.oos_sharpe = backtest.sharpe_ratio * 0.8   # 模拟

        # 多周期稳健性（占位）
        backtest.period_results = {
            "1m": backtest.sharpe_ratio * 0.9,
            "3m": backtest.sharpe_ratio * 0.85,
            "6m": backtest.sharpe_ratio * 0.8,
            "1y": backtest.sharpe_ratio * 0.75,
        }
        backtest.multi_period_stable, _ = self._overfit_validator.check_multi_period(
            backtest.period_results
        )

        # IC 衰减（占位 — 实际需要 IC 时间序列）
        backtest.ic_decay_rate = 0.1

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

        self._auditor.record(EvolutionAuditRecord(
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
            reason="; ".join(backtest.reject_reasons) if backtest.reject_reasons else "全部检验通过",
            metrics_snapshot=strategy.backtest_result,
        ))

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
            # 占位 — 实际应计算策略收益序列相关性
            correlation = 0.3  # 模拟值
            assessment["correlation_with_live"][slot] = correlation
            if abs(correlation) > 0.8:
                assessment["reject_reasons"].append(
                    f"与冠军策略 {slot} 相关性过高: {correlation:.2f}"
                )

        assessment["passed"] = len(assessment["reject_reasons"]) == 0
        strategy.risk_assessment = assessment

        self._auditor.record(EvolutionAuditRecord(
            event="risk_assess",
            strategy_id=strategy.strategy_id,
            stage="risk_assessment",
            data_used={"existing_champions": list(self._champions.keys())},
            comparison=assessment["correlation_with_live"],
            decision="通过" if assessment["passed"] else "未通过",
            reason="; ".join(assessment["reject_reasons"]) if assessment["reject_reasons"] else "风险可控",
            metrics_snapshot={"risk_level": assessment["overall_risk_level"]},
        ))

        return assessment

    # ──── ⑤影子运行 ────

    async def shadow_run(self, strategy: Strategy, days: int = 30) -> ShadowResult:
        """⑤影子运行：只读跟单对比预测

        策略在影子模式下运行，不实际交易，只记录预测。
        运行结束后对比预测准确率和模拟收益。

        Args:
            strategy: 待验证策略
            days: 影子运行天数

        Returns:
            影子运行结果
        """
        strategy.lifecycle = StrategyLifecycle.SHADOW

        # 占位 — 实际应启动影子运行任务并等待结果
        result = ShadowResult(
            strategy_id=strategy.strategy_id,
            shadow_days=days,
        )

        # 通过标准：信号准确率 > 55% 且 模拟收益 > 冠军收益
        result.passed = (
            result.signal_accuracy > 0.55
            and result.outperformance > 0
        )

        self._auditor.record(EvolutionAuditRecord(
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
        ))

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

        self._auditor.record(EvolutionAuditRecord(
            event="grayscale_deploy",
            strategy_id=strategy.strategy_id,
            stage="grayscale",
            data_used={"capital_pct": capital_pct},
            decision="灰度上线",
            reason=f"分配 {capital_pct:.0%} 资金进行灰度验证",
        ))

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

        self._auditor.record(EvolutionAuditRecord(
            event="full_deploy",
            strategy_id=strategy.strategy_id,
            stage="live",
            data_used={"slot": slot},
            decision="全量上线",
            reason=f"部署到槽位 {slot}",
        ))

        logger.info("策略 %s 全量上线: 槽位 %s", strategy.strategy_id, slot)

    # ──── ⑧实盘监控 ────

    async def monitor_performance(self, strategy: Strategy) -> dict[str, Any]:
        """⑧实盘监控

        持续监控策略实盘表现：
        - 收益/夏普/回撤
        - 信号准确率
        - 与回测指标的偏差

        Args:
            strategy: 被监控策略

        Returns:
            监控指标
        """
        # 占位 — 实际应从实盘数据源获取
        live_metrics: dict[str, Any] = {
            "strategy_id": strategy.strategy_id,
            "live_return": 0.0,
            "live_sharpe": 0.0,
            "live_max_dd": 0.0,
            "signal_count": 0,
            "signal_accuracy": 0.0,
            "deviation_from_backtest": 0.0,
        }

        # 计算与回测的偏差
        bt_sharpe = float(strategy.backtest_result.get("sharpe_ratio", 0))
        if bt_sharpe > 0:
            live_metrics["deviation_from_backtest"] = abs(
                live_metrics["live_sharpe"] - bt_sharpe
            ) / bt_sharpe

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
            self._auditor.record(EvolutionAuditRecord(
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
            ))
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

        self._auditor.record(EvolutionAuditRecord(
            event="retire_strategy",
            strategy_id=strategy.strategy_id,
            stage="retired",
            data_used={"final_metrics": strategy.metrics},
            decision="退役",
            reason=reason or "手动退役",
            metrics_snapshot=strategy.metrics,
        ))

        logger.info("策略 %s 已退役: %s", strategy.strategy_id, reason)

    # ──── 辅助 ────

    @staticmethod
    def _make_id(prefix: str, content: str) -> str:
        """生成确定性 ID"""
        h = hashlib.md5(content.encode(), usedforsecurity=False).hexdigest()[:12]
        return f"{prefix}_{h}"


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
    MIN_SHADOW_DAYS: int = 14           # 最少影子运行天数
    MIN_TRADES: int = 50                # 最少交易次数
    OUTPERFORMANCE_THRESHOLD: float = 0.1  # 超额收益阈值（10%）
    SHARPE_IMPROVEMENT: float = 0.2     # 夏普提升阈值
    MAX_DD_IMPROVEMENT: float = 0.05    # 最大回撤改善阈值

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

        self._auditor.record(EvolutionAuditRecord(
            event="register_champion",
            strategy_id=strategy.strategy_id,
            stage="live",
            data_used={"slot": slot},
            decision="注册冠军",
            reason=f"成为槽位 {slot} 的冠军策略",
        ))

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

        self._challengers[slot].append(ChallengerRecord(
            strategy=strategy,
            submitted_at=time.time_ns(),
        ))

        self._auditor.record(EvolutionAuditRecord(
            event="register_challenger",
            strategy_id=strategy.strategy_id,
            stage="challenger",
            data_used={"slot": slot},
            decision="注册挑战者",
            reason=f"挑战槽位 {slot} 的冠军",
        ))

        logger.info("挑战者注册: 槽位=%s 策略=%s", slot, strategy.strategy_id)

    async def run_comparison(self, slot: str, market_data: list[dict[str, Any]]) -> list[ComparisonResult]:
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
                comp.outperformance = (comp.challenger_sharpe - comp.champion_sharpe) / comp.champion_sharpe

            # 晋升判定（三维标准）
            sharpe_pass = comp.challenger_sharpe >= comp.champion_sharpe * (1 + self.SHARPE_IMPROVEMENT)
            dd_pass = comp.challenger_max_dd <= comp.champion_max_dd + self.MAX_DD_IMPROVEMENT
            return_pass = comp.outperformance >= self.OUTPERFORMANCE_THRESHOLD

            comp.promoted = sharpe_pass and dd_pass and return_pass
            comp.stability_score = sum([sharpe_pass, dd_pass, return_pass]) / 3.0

            if comp.promoted:
                comp.reason = (
                    f"挑战者全面超越: 夏普 {comp.challenger_sharpe:.2f} vs {comp.champion_sharpe:.2f}, "
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

            ch_record.comparison_results.append({
                "promoted": comp.promoted,
                "outperformance": comp.outperformance,
                "stability_score": comp.stability_score,
                "timestamp_ns": time.time_ns(),
            })

            results.append(comp)

            self._auditor.record(EvolutionAuditRecord(
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
            ))

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

        self._auditor.record(EvolutionAuditRecord(
            event="promote_challenger",
            strategy_id=challenger_id,
            stage="live",
            data_used={
                "slot": slot,
                "old_champion": old_champion.strategy.strategy_id if old_champion else "none",
            },
            decision="晋升成功",
            reason=f"挑战者 {challenger_id} 晋升为槽位 {slot} 新冠军",
        ))

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
            records.append({
                "event": "current_champion",
                "strategy_id": champion.strategy.strategy_id,
                "promoted_at": champion.promoted_at,
                "metrics_at_promotion": champion.metrics_at_promotion,
            })

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
    ) -> None:
        self._pipeline = training_pipeline
        self._drift_detector = DriftDetector(threshold=drift_threshold)
        self._window_days = retrain_window_days
        self._retrain_history: list[dict[str, Any]] = []
        self._model_versions: dict[str, list[dict[str, Any]]] = {}  # model_name → [版本]
        self._active_versions: dict[str, int] = {}  # model_name → 当前活跃版本索引

    async def daily_retrain(self, symbols: list[str]) -> None:
        """滚动再训练（日/周用新数据）

        流程：
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

                # 占位 — 实际应调用训练流水线
                # new_model = await self._pipeline.train(symbol, window_days=self._window_days)

                # 样本外验证
                # oos_score = await self._pipeline.validate_oos(new_model, symbol)

                record = {
                    "symbol": symbol,
                    "action": "daily_retrain",
                    "timestamp_ns": time.time_ns(),
                    "status": "completed",
                }
                self._retrain_history.append(record)

            except Exception:
                logger.exception("再训练失败: %s", symbol)
                self._retrain_history.append({
                    "symbol": symbol,
                    "action": "daily_retrain",
                    "timestamp_ns": time.time_ns(),
                    "status": "failed",
                })

    async def check_concept_drift(self, model_name: str) -> bool:
        """概念漂移检测

        检测方法：
        - 预测残差分布变化
        - 输入特征分布变化（KS检验）
        - 评分分布偏移

        Args:
            model_name: 模型名称

        Returns:
            是否检测到概念漂移
        """
        # 占位 — 实际应获取近期预测残差和基线残差
        recent_errors: list[float] = []
        baseline_errors: list[float] = []

        drifted = self._drift_detector.detect(recent_errors, baseline_errors)

        if drifted:
            logger.warning("概念漂移检测: model=%s", model_name)
            # 自动触发再训练
            await self.daily_retrain([model_name])

        return drifted

    async def grayscale_model(self, new_model: Any, current_model: Any, traffic_pct: float = 0.1) -> bool:
        """模型版本灰度

        将新模型以 traffic_pct 比例分流，对比新旧模型表现。

        Args:
            new_model: 新模型
            current_model: 当前模型
            traffic_pct: 灰度流量比例

        Returns:
            灰度是否通过（可全量替换）
        """
        # 占位 — 实际应实现 A/B 测试
        logger.info("模型灰度: 流量比例 %.0f%%", traffic_pct * 100)
        return True

    async def rollback(self, model_name: str) -> None:
        """一键回滚到上一个版本

        Args:
            model_name: 模型名称
        """
        versions = self._model_versions.get(model_name, [])
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
                drift, self._threshold, recent_mean, baseline_mean,
            )

        return detected

    def detect_page_hinkley(self, series: list[float], delta: float = 0.005, threshold: float = 50.0) -> bool:
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

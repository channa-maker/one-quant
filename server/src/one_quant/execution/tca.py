"""
ONE量化 - 交易成本分析 (TCA) + 策略容量分析

TCA 回流自进化平台，量化执行质量，驱动策略迭代。

模块职责：
  - TCAnalyzer: 实施缺口、VWAP/到达价基准、滑点归因、执行质量看板
  - StrategyCapacityAnalyzer: 容量曲线、超容量检查
"""

from __future__ import annotations

import time
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from pydantic import BaseModel

from one_quant.core.types import Fill
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


# ──────────────────────────── 数据模型 ────────────────────────────


class TCReport(BaseModel, frozen=True):
    """TCA 分析报告（结构化，可序列化回流自进化平台）

    Attributes:
        strategy_id: 策略标识
        symbol: 标的符号
        side: 买卖方向
        total_quantity: 总成交量
        avg_fill_price: 成交均价
        decision_price: 决策价格
        arrival_price: 到达价格
        market_vwap: 市场 VWAP
        implementation_shortfall: 实施缺口（金额）
        implementation_shortfall_bps: 实施缺口（基点）
        vwap_slippage_bps: VWAP 滑点（基点）
        arrival_slippage_bps: 到达价滑点（基点）
        market_impact_bps: 市场冲击（基点）
        timing_cost_bps: 时机成本（基点）
        spread_cost_bps: 价差成本（基点）
        fill_count: 成交笔数
        total_commission: 总手续费
        total_notional: 总成交金额
        period: 分析周期
        timestamp_ns: 纳秒时间戳
    """

    strategy_id: str
    symbol: str
    side: str
    total_quantity: Decimal
    avg_fill_price: Decimal
    decision_price: Decimal
    arrival_price: Decimal
    market_vwap: Decimal
    implementation_shortfall: Decimal
    implementation_shortfall_bps: float
    vwap_slippage_bps: float
    arrival_slippage_bps: float
    market_impact_bps: float
    timing_cost_bps: float
    spread_cost_bps: float
    fill_count: int
    total_commission: Decimal
    total_notional: Decimal
    period: str
    timestamp_ns: int


class CapacityEstimate(BaseModel, frozen=True):
    """策略容量估计结果

    Attributes:
        strategy_name: 策略名称
        optimal_capital: 最优资金规模（收益衰减 <5%）
        max_capital: 最大资金规模（收益衰减 <20%）
        capacity_curve: 资金规模 → 预期年化收益映射
        current_utilization: 当前资金 / 最优资金
        is_over_capacity: 是否超容量
        notes: 分析备注
    """

    strategy_name: str
    optimal_capital: Decimal
    max_capital: Decimal
    capacity_curve: dict[str, float]
    current_utilization: float
    is_over_capacity: bool
    notes: str


# ──────────────────────────── 交易成本分析器 ────────────────────────────


class TCAnalyzer:
    """交易成本分析器。

    量化每一笔交易的隐性成本，回流自进化平台驱动策略迭代。
    支持实施缺口、VWAP 基准、到达价基准、滑点归因四维度分析。
    """

    def implementation_shortfall(
        self,
        decision_price: Decimal,
        exec_price: Decimal,
        quantity: Decimal,
        side: str = "buy",
    ) -> Decimal:
        """实施缺口：决策价 vs 实际成交价。

        实施缺口 = (实际成交价 - 决策价) × 方向 × 数量
        正值表示成本增加（买贵了/卖便宜了），负值表示成本节约。

        Args:
            decision_price: 策略决策时的价格（信号产生的瞬间）
            exec_price: 实际成交均价
            quantity: 成交数量
            side: 买卖方向 ("buy" / "sell")

        Returns:
            实施缺口金额（正 = 额外成本）
        """
        side_sign = Decimal("1") if side == "buy" else Decimal("-1")
        shortfall = (exec_price - decision_price) * side_sign * quantity
        return shortfall.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)

    def implementation_shortfall_bps(
        self,
        decision_price: Decimal,
        exec_price: Decimal,
        side: str = "buy",
    ) -> float:
        """实施缺口（基点）。

        Args:
            decision_price: 决策价格
            exec_price: 实际成交均价
            side: 买卖方向

        Returns:
            基点值（正 = 额外成本）
        """
        if decision_price <= 0:
            return 0.0
        side_sign = Decimal("1") if side == "buy" else Decimal("-1")
        return float((exec_price - decision_price) / decision_price * Decimal("10000") * side_sign)

    def vwap_benchmark(self, fills: list[Fill], market_vwap: Decimal) -> float:
        """VWAP 基准对比。

        计算成交均价相对于市场 VWAP 的偏差（基点）。
        负值 = 跑赢 VWAP（执行更优），正值 = 跑输 VWAP。

        Args:
            fills: 成交记录列表
            market_vwap: 市场 VWAP 价格

        Returns:
            VWAP 偏差（基点）
        """
        if not fills or market_vwap <= 0:
            return 0.0

        total_qty = sum((f.quantity for f in fills), Decimal("0"))
        if total_qty <= 0:
            return 0.0

        avg_price = sum((f.price * f.quantity for f in fills), Decimal("0")) / total_qty
        # 买入：低于 VWAP 为好（负值）；卖出：高于 VWAP 为好（负值）
        side_sign = Decimal("1") if fills[0].side == "buy" else Decimal("-1")
        return float((avg_price - market_vwap) / market_vwap * Decimal("10000") * side_sign)

    def arrival_price_benchmark(self, fills: list[Fill], arrival_price: Decimal) -> float:
        """到达价基准。

        到达价 = 订单到达交易所时的中间价（或最新价）。
        衡量从"下单那一刻"到"实际成交"的价格漂移。

        Args:
            fills: 成交记录列表
            arrival_price: 到达价（下单时的市场中间价）

        Returns:
            到达价偏差（基点）
        """
        if not fills or arrival_price <= 0:
            return 0.0

        total_qty = sum((f.quantity for f in fills), Decimal("0"))
        if total_qty <= 0:
            return 0.0

        avg_price = sum((f.price * f.quantity for f in fills), Decimal("0")) / total_qty
        side_sign = Decimal("1") if fills[0].side == "buy" else Decimal("-1")
        return float((avg_price - arrival_price) / arrival_price * Decimal("10000") * side_sign)

    def slippage_attribution(self, fills: list[Fill]) -> dict[str, Any]:
        """滑点归因：将总滑点拆解为市场冲击、时机成本、价差成本。

        归因模型：
          总滑点 = 市场冲击 + 时机成本 + 价差成本

        - 市场冲击：大单推动市场价格移动的成本
          估算 = Σ(每笔成交价 - 成交前 mid_price) / mid_price
          简化：用前 20% 成交均价 vs 后 20% 成交均价的差值

        - 时机成本：从决策到执行期间市场价格自然波动
          估算 = (第一笔成交价 - arrival_price) 的方向性偏差
          此处用首笔成交 vs 全部成交均价近似

        - 价差成本：bid-ask spread 的一半
          估算 = 成交价 vs 同时刻 mid_price 的偏差
          简化：用成交价的标准差近似（反映分散度）

        Args:
            fills: 成交记录列表

        Returns:
            归因结果字典：
            {
                "total_slippage_bps": float,      # 总滑点（基点）
                "market_impact_bps": float,        # 市场冲击
                "timing_cost_bps": float,          # 时机成本
                "spread_cost_bps": float,          # 价差成本
                "attribution_pct": dict,           # 各项占比
                "fill_count": int,
                "total_quantity": Decimal,
            }
        """
        if not fills or len(fills) < 2:
            return {
                "total_slippage_bps": 0.0,
                "market_impact_bps": 0.0,
                "timing_cost_bps": 0.0,
                "spread_cost_bps": 0.0,
                "attribution_pct": {"impact": 0, "timing": 0, "spread": 0},
                "fill_count": len(fills),
                "total_quantity": sum((f.quantity for f in fills), Decimal("0"))
                if fills
                else Decimal("0"),
            }

        # 按时间排序
        sorted_fills = sorted(fills, key=lambda f: f.timestamp_ns)
        total_qty = sum((f.quantity for f in sorted_fills), Decimal("0"))
        avg_price = sum((f.price * f.quantity for f in sorted_fills), Decimal("0")) / total_qty

        side_sign = Decimal("1") if sorted_fills[0].side == "buy" else Decimal("-1")
        ref_price: Decimal = sorted_fills[0].price  # 到达价近似

        # ── 市场冲击：前 20% vs 后 20% 成交均价 ──
        n = len(sorted_fills)
        head_n = max(1, n // 5)
        tail_n = max(1, n // 5)

        head_qty = sum((f.quantity for f in sorted_fills[:head_n]), Decimal("0"))
        head_avg = (
            sum((f.price * f.quantity for f in sorted_fills[:head_n]), Decimal("0")) / head_qty
            if head_qty > 0
            else avg_price
        )

        tail_qty = sum((f.quantity for f in sorted_fills[-tail_n:]), Decimal("0"))
        tail_avg = (
            sum((f.price * f.quantity for f in sorted_fills[-tail_n:]), Decimal("0")) / tail_qty
            if tail_qty > 0
            else avg_price
        )

        # 买入时后成交价高于前成交价 = 正冲击
        if head_avg > 0:
            market_impact_bps = float(
                (tail_avg - head_avg) / head_avg * Decimal("10000") * side_sign
            )
        else:
            market_impact_bps = 0.0

        # ── 时机成本：首笔 vs 全局均价 ──
        first_price = sorted_fills[0].price
        if ref_price > 0:
            timing_cost_bps = float(
                (first_price - ref_price) / ref_price * Decimal("10000") * side_sign
            )
        else:
            timing_cost_bps = 0.0

        # ── 价差成本：用价格标准差近似 ──
        prices = [float(f.price) for f in sorted_fills]
        if len(prices) > 1:
            mean_p = sum(prices) / len(prices)
            variance = sum((p - mean_p) ** 2 for p in prices) / (len(prices) - 1)
            std_dev = variance**0.5
            spread_cost_bps = (std_dev / mean_p * 10000) if mean_p > 0 else 0.0
        else:
            spread_cost_bps = 0.0

        # ── 总滑点 ──
        if ref_price > 0:
            total_slippage_bps = float(
                (avg_price - ref_price) / ref_price * Decimal("10000") * side_sign
            )
        else:
            total_slippage_bps = 0.0

        # ── 占比归一化 ──
        abs_total = abs(market_impact_bps) + abs(timing_cost_bps) + abs(spread_cost_bps)
        if abs_total > 0:
            attribution_pct = {
                "impact": round(abs(market_impact_bps) / abs_total * 100, 1),
                "timing": round(abs(timing_cost_bps) / abs_total * 100, 1),
                "spread": round(abs(spread_cost_bps) / abs_total * 100, 1),
            }
        else:
            attribution_pct = {"impact": 0, "timing": 0, "spread": 0}

        return {
            "total_slippage_bps": round(total_slippage_bps, 2),
            "market_impact_bps": round(market_impact_bps, 2),
            "timing_cost_bps": round(timing_cost_bps, 2),
            "spread_cost_bps": round(spread_cost_bps, 2),
            "attribution_pct": attribution_pct,
            "fill_count": len(fills),
            "total_quantity": total_qty,
        }

    def execution_quality_report(
        self,
        strategy_id: str,
        fills: list[Fill],
        decision_price: Decimal,
        arrival_price: Decimal,
        market_vwap: Decimal,
        period: str = "2024-Q4",
    ) -> TCReport:
        """执行质量看板：一站式生成完整 TCA 报告。

        集成实施缺口、VWAP 基准、到达价基准、滑点归因四维度。
        报告可序列化后回流自进化平台，驱动策略参数优化。

        Args:
            strategy_id: 策略标识
            fills: 成交记录列表
            decision_price: 策略决策价格
            arrival_price: 订单到达价格
            market_vwap: 市场 VWAP
            period: 分析周期标识

        Returns:
            结构化 TCA 报告
        """
        if not fills:
            return TCReport(
                strategy_id=strategy_id,
                symbol="",
                side="buy",
                total_quantity=Decimal("0"),
                avg_fill_price=Decimal("0"),
                decision_price=decision_price,
                arrival_price=arrival_price,
                market_vwap=market_vwap,
                implementation_shortfall=Decimal("0"),
                implementation_shortfall_bps=0,
                vwap_slippage_bps=0,
                arrival_slippage_bps=0,
                market_impact_bps=0,
                timing_cost_bps=0,
                spread_cost_bps=0,
                fill_count=0,
                total_commission=Decimal("0"),
                total_notional=Decimal("0"),
                period=period,
                timestamp_ns=time.time_ns(),
            )

        total_qty = sum((f.quantity for f in fills), Decimal("0"))
        total_notional = sum((f.price * f.quantity for f in fills), Decimal("0"))
        avg_price = total_notional / total_qty if total_qty > 0 else Decimal("0")
        total_commission = sum((f.fee for f in fills), Decimal("0"))
        side = fills[0].side

        # 各维度指标
        shortfall = self.implementation_shortfall(decision_price, avg_price, total_qty, side)
        shortfall_bps: float = self.implementation_shortfall_bps(decision_price, avg_price, side)
        vwap_bps = self.vwap_benchmark(fills, market_vwap)
        arrival_bps = self.arrival_price_benchmark(fills, arrival_price)

        # 滑点归因
        attribution = self.slippage_attribution(fills)

        return TCReport(
            strategy_id=strategy_id,
            symbol=fills[0].symbol,
            side=side,
            total_quantity=total_qty,
            avg_fill_price=avg_price,
            decision_price=decision_price,
            arrival_price=arrival_price,
            market_vwap=market_vwap,
            implementation_shortfall=shortfall,
            implementation_shortfall_bps=round(shortfall_bps, 2),
            vwap_slippage_bps=round(vwap_bps, 2),
            arrival_slippage_bps=round(arrival_bps, 2),
            market_impact_bps=attribution["market_impact_bps"],
            timing_cost_bps=attribution["timing_cost_bps"],
            spread_cost_bps=attribution["spread_cost_bps"],
            fill_count=len(fills),
            total_commission=total_commission,
            total_notional=total_notional,
            period=period,
            timestamp_ns=time.time_ns(),
        )

    def aggregate_by_strategy(
        self,
        reports: list[TCReport],
    ) -> dict[str, dict[str, Any]]:
        """按策略聚合 TCA 报告，用于策略间横向对比。

        Args:
            reports: TCA 报告列表

        Returns:
            {strategy_id: {avg_shortfall_bps, avg_vwap_bps, total_commission, ...}}
        """
        grouped: dict[str, list[TCReport]] = defaultdict(list)
        for r in reports:
            grouped[r.strategy_id].append(r)

        result: dict[str, dict[str, Any]] = {}
        for sid, group in grouped.items():
            n = len(group)
            result[sid] = {
                "report_count": n,
                "avg_shortfall_bps": sum(r.implementation_shortfall_bps for r in group) / n,
                "avg_vwap_bps": sum(r.vwap_slippage_bps for r in group) / n,
                "avg_arrival_bps": sum(r.arrival_slippage_bps for r in group) / n,
                "avg_impact_bps": sum(r.market_impact_bps for r in group) / n,
                "total_commission": sum((r.total_commission for r in group), Decimal("0")),
                "total_notional": sum((r.total_notional for r in group), Decimal("0")),
                "total_fills": sum(r.fill_count for r in group),
            }

        return result


# ──────────────────────────── 策略容量分析 ────────────────────────────


class StrategyCapacityAnalyzer:
    """策略容量分析器。

    策略的资金容量是有限的：资金越大，市场冲击越强，收益越低。
    容量分析帮助确定策略的最优资金规模，避免"规模诅咒"。

    容量曲线：横轴 = 资金规模，纵轴 = 预期年化收益衰减比例。
    """

    # 衰减模型参数（可调）
    DECAY_MODEL_COEFFICIENTS = {
        "linear": 0.05,  # 每翻倍资金，收益衰减 5%
        "quadratic": 0.002,  # 二次衰减系数
    }

    def estimate_capacity(
        self,
        strategy_name: str,
        base_annual_return: float,
        avg_daily_volume: Decimal,
        avg_order_size: Decimal,
        market_impact_model: str = "linear",
    ) -> CapacityEstimate:
        """容量曲线估算。

        基于市场冲击模型，估算资金规模 vs 预期收益衰减关系。

        模型假设：
          - 市场冲击 ∝ order_size / daily_volume（Kyle's Lambda 简化版）
          - 收益衰减 = f(市场冲击)
          - 资金规模 ∝ order_size

        Args:
            strategy_name: 策略名称
            base_annual_return: 基准年化收益率（小数，如 0.3 = 30%）
            avg_daily_volume: 标的日均成交量（金额）
            avg_order_size: 策略平均单笔下单金额
            market_impact_model: 冲击模型 ("linear" / "quadratic")

        Returns:
            容量估计结果
        """
        if avg_daily_volume <= 0 or avg_order_size <= 0:
            return CapacityEstimate(
                strategy_name=strategy_name,
                optimal_capital=Decimal("0"),
                max_capital=Decimal("0"),
                capacity_curve={},
                current_utilization=0.0,
                is_over_capacity=False,
                notes="日均成交量或平均下单金额为零，无法估算容量",
            )

        # 参与率 = 平均下单金额 / 日均成交量
        participation_rate = float(avg_order_size / avg_daily_volume)

        # 容量曲线：从 1x 到 20x 资金规模
        capacity_curve: dict[str, float] = {}
        optimal_capital = Decimal("0")
        max_capital = Decimal("0")

        for multiplier in range(1, 21):
            capital = avg_order_size * multiplier
            current_participation = participation_rate * multiplier

            # 收益衰减模型
            if market_impact_model == "quadratic":
                decay = self.DECAY_MODEL_COEFFICIENTS["quadratic"] * current_participation**2
            else:
                decay = self.DECAY_MODEL_COEFFICIENTS["linear"] * current_participation

            expected_return = base_annual_return * max(0, 1 - decay)
            capacity_curve[str(capital)] = round(expected_return * 100, 2)

            # 最优容量：收益衰减 <5%
            if decay < 0.05 and optimal_capital == Decimal("0"):
                optimal_capital = capital
            elif decay < 0.05:
                optimal_capital = capital

            # 最大容量：收益衰减 <20%
            if decay < 0.20:
                max_capital = capital

        # 如果所有点都衰减 >5%，取第一个点
        if optimal_capital == Decimal("0"):
            optimal_capital = avg_order_size

        utilization = float(avg_order_size / optimal_capital) if optimal_capital > 0 else 0.0

        return CapacityEstimate(
            strategy_name=strategy_name,
            optimal_capital=optimal_capital,
            max_capital=max_capital,
            capacity_curve=capacity_curve,
            current_utilization=round(utilization, 4),
            is_over_capacity=utilization > 1.0,
            notes=f"基于{market_impact_model}冲击模型, 参与率={participation_rate:.4f}",
        )

    def check_over_capacity(
        self,
        strategy_name: str,
        current_capital: Decimal,
        optimal_capital: Decimal,
    ) -> bool:
        """超容量检查。

        Args:
            strategy_name: 策略名称
            current_capital: 当前管理资金
            optimal_capital: 最优资金容量

        Returns:
            True 表示超容量
        """
        if optimal_capital <= 0:
            return False

        is_over = current_capital > optimal_capital
        if is_over:
            ratio = float(current_capital / optimal_capital)
            logger.warning(
                "策略 %s 超容量: 当前资金=%s, 最优容量=%s, 超出比例=%.2f%%",
                strategy_name,
                current_capital,
                optimal_capital,
                (ratio - 1) * 100,
            )
        return is_over

    def capacity_from_tca(
        self,
        tca_reports: list[TCReport],
        strategy_name: str,
    ) -> CapacityEstimate:
        """基于 TCA 历史数据反推容量。

        用实际执行数据拟合冲击模型，比理论估算更准确。
        核心思路：滑点_bps = α × (成交金额 / 日均成交)^β
        当滑点超过阈值时即为容量上限。

        Args:
            tca_reports: 历史 TCA 报告
            strategy_name: 策略名称

        Returns:
            容量估计（基于实际数据）
        """
        if not tca_reports:
            return CapacityEstimate(
                strategy_name=strategy_name,
                optimal_capital=Decimal("0"),
                max_capital=Decimal("0"),
                capacity_curve={},
                current_utilization=0.0,
                is_over_capacity=False,
                notes="无历史 TCA 数据，无法反推容量",
            )

        # 按成交金额分桶，统计各桶平均滑点
        buckets: dict[str, list[float]] = defaultdict(list)
        for r in tca_reports:
            if r.total_notional > 0:
                bucket = str(r.total_notional.quantize(Decimal("1000"), rounding=ROUND_HALF_UP))
                buckets[bucket].append(abs(r.implementation_shortfall_bps))

        # 简单线性拟合：滑点 vs 成交金额
        sorted_buckets = sorted(buckets.items(), key=lambda x: Decimal(x[0]))
        capacity_curve: dict[str, float] = {}
        for bucket, slippages in sorted_buckets:
            avg_slip = sum(slippages) / len(slippages)
            capacity_curve[bucket] = round(avg_slip, 2)

        # 最优容量 = 滑点 < 10bps 的最大金额
        optimal = Decimal("0")
        max_cap = Decimal("0")
        for bucket, bucket_slippages in sorted_buckets:
            bucket_avg = sum(bucket_slippages) / len(bucket_slippages) if bucket_slippages else 0.0
            amt = Decimal(bucket)
            if bucket_avg < 10.0:
                optimal = amt
            if bucket_avg < 25.0:
                max_cap = amt

        return CapacityEstimate(
            strategy_name=strategy_name,
            optimal_capital=optimal,
            max_capital=max_cap,
            capacity_curve=capacity_curve,
            current_utilization=0.0,
            is_over_capacity=False,
            notes=f"基于 {len(tca_reports)} 条 TCA 历史数据反推",
        )

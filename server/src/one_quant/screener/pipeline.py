"""
ONE量化 - 选股选币流水线

全市场标的池
 → 一级过滤(流动性/市值/上市时长/可交易性)
 → 因子计算(动量/价值/质量/波动/资金流/链上)
 → ML 打分(XGBoost/LightGBM 排序,预期收益分位)
 → LLM 复核(基本面/消息面/事件面定性加减分)
 → 风险约束(行业/板块/相关性分散,单标的上限)
 → 候选池(Top-N,带分数/理由/置信度)
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Any, Protocol

from pydantic import BaseModel

from one_quant.core.types import Instrument, Market

logger = logging.getLogger(__name__)


# ──────────────────────────── 接口协议 ────────────────────────────


class FactorLibrary(Protocol):
    """因子库协议。

    提供因子注册与查询能力，每个因子接收标的数据并输出 Decimal 值。
    """

    def compute(self, symbol: str, market_data: dict[str, Any]) -> dict[str, Decimal]:
        """计算指定标的的全部因子值。

        Args:
            symbol: 标的符号。
            market_data: 市场数据。

        Returns:
            因子名 → 因子值的映射。
        """
        ...


class MLModel(Protocol):
    """ML 排序模型协议。

    接收特征矩阵，输出每个标的的预期收益分位得分（0~1）。
    """

    def predict(self, features: dict[str, dict[str, float]]) -> dict[str, float]:
        """预测标的得分。

        Args:
            features: 标的符号 → 因子名 → 因子值。

        Returns:
            标的符号 → 得分（0~1）。
        """
        ...


class LLMProvider(Protocol):
    """LLM 提供者协议。

    提供定性分析能力，输出中文一句话理由、加减分和置信度。
    """

    async def review(
        self,
        symbol: str,
        score: float,
        factors: dict[str, float],
        market_data: dict[str, Any],
    ) -> LLMReview:
        """LLM 复核单个标的。

        Args:
            symbol: 标的符号。
            score: ML 打分。
            factors: 因子明细。
            market_data: 市场数据。

        Returns:
            复核结果（理由、加减分、置信度）。
        """
        ...


# ──────────────────────────── 数据模型 ────────────────────────────


class LLMReview(BaseModel, frozen=True):
    """LLM 复核结果。

    Attributes:
        reason: 中文一句话理由。
        adjustment: 加减分（-20 ~ +20）。
        confidence: 置信度（0~1）。
    """

    reason: str
    adjustment: float = 0.0
    confidence: float = 0.5


class CandidateAsset(BaseModel, frozen=True):
    """候选标的。

    Attributes:
        symbol: 标的符号。
        market: 市场类型。
        score: ML 打分（0~100）。
        llm_adjustment: LLM 加减分（-20 ~ +20）。
        final_score: 最终得分（score + llm_adjustment，0~100）。
        confidence: 置信度（0~1）。
        reason: 中文理由（一句话）。
        factors: 因子明细（因子名 → 因子值）。
        timestamp_ns: 纳秒级时间戳。
    """

    symbol: str
    market: str
    score: float
    llm_adjustment: float
    final_score: float
    confidence: float
    reason: str
    factors: dict[str, Any]
    timestamp_ns: int


class ScreenerResult(BaseModel, frozen=True):
    """兼容旧版的选股结果。

    Attributes:
        symbol: 标的符号。
        score: 综合得分（0-100）。
        reason: 中文理由。
        confidence: 置信度（0-1）。
        factors: 因子明细。
        market: 市场类型。
    """

    symbol: str
    score: float
    reason: str
    confidence: float
    factors: dict[str, float] = {}
    market: Market = Market.SPOT


# ──────────────────────────── 内置默认实现 ────────────────────────────


class DefaultFactorLibrary:
    """默认因子库：动量 / 成交量 / 波动率 / 市值。

    使用 Decimal 精确计算所有因子。
    """

    def compute(self, symbol: str, market_data: dict[str, Any]) -> dict[str, Decimal]:
        """计算默认因子集合。

        Args:
            symbol: 标的符号。
            market_data: 市场数据。

        Returns:
            因子名 → Decimal 因子值。
        """
        ticker = market_data.get(symbol, {})
        if not ticker:
            return {}

        factors: dict[str, Decimal] = {}

        # 动量因子：24h 涨跌幅（百分比）
        change_pct = Decimal(str(ticker.get("change_pct", "0")))
        factors["momentum_24h"] = change_pct

        # 成交量因子：24h 成交量
        volume = Decimal(str(ticker.get("volume_24h", "0")))
        factors["volume_24h"] = volume

        # 市值因子
        market_cap = Decimal(str(ticker.get("market_cap", "0")))
        factors["market_cap"] = market_cap

        # 波动率因子：如果有多根 K 线数据可扩展，这里用涨跌幅绝对值近似
        factors["volatility"] = abs(change_pct)

        # 资金流因子：买入占比（如有）
        buy_ratio = Decimal(str(ticker.get("buy_volume_ratio", "0.5")))
        factors["buy_volume_ratio"] = buy_ratio

        # 链上因子：活跃地址数变化（如有）
        active_addr_change = Decimal(
            str(ticker.get("active_address_change", "0"))
        )
        factors["active_address_change"] = active_addr_change

        return factors


class DefaultMLModel:
    """默认 ML 模型：基于规则的启发式打分。

    当无训练好的 XGBoost/LightGBM 模型时使用此降级方案。
    """

    def predict(self, features: dict[str, dict[str, float]]) -> dict[str, float]:
        """基于规则的启发式打分。

        打分规则：
        - 基准分 50
        - 动量贡献：涨跌幅 * 2，上限 30 分
        - 成交量贡献：log10(volume) * 2，上限 10 分
        - 买盘占比贡献：(ratio - 0.5) * 20，上限 10 分
        - 总分限制在 0~100

        Args:
            features: 标的符号 → 因子名 → 因子值。

        Returns:
            标的符号 → 得分（0~100）。
        """
        import math

        scores: dict[str, float] = {}
        for symbol, feats in features.items():
            score = 50.0  # 基准分

            # 动量贡献
            momentum = feats.get("momentum_24h", 0.0)
            score += min(momentum * 2, 30)

            # 成交量贡献
            volume = feats.get("volume_24h", 0.0)
            if volume > 0:
                score += min(math.log10(max(volume, 1)) * 2, 10)

            # 买盘占比贡献
            buy_ratio = feats.get("buy_volume_ratio", 0.5)
            score += min((buy_ratio - 0.5) * 20, 10)

            scores[symbol] = max(0.0, min(100.0, score))
        return scores


class DefaultLLMProvider:
    """默认 LLM 提供者：基于规则的中文理由生成。

    当无可用 LLM 时使用此降级方案，根据因子值生成中文评语。
    """

    async def review(
        self,
        symbol: str,
        score: float,
        factors: dict[str, float],
        market_data: dict[str, Any],
    ) -> LLMReview:
        """基于规则生成复核结果。

        Args:
            symbol: 标的符号。
            score: ML 打分。
            factors: 因子明细。
            market_data: 市场数据。

        Returns:
            复核结果（中文理由、加减分、置信度）。
        """
        momentum = factors.get("momentum_24h", 0.0)
        volume = factors.get("volume_24h", 0.0)
        buy_ratio = factors.get("buy_volume_ratio", 0.5)

        # 生成中文理由
        parts: list[str] = []
        if momentum > 5:
            parts.append(f"24h涨幅{momentum:.1f}%，动量强劲")
        elif momentum < -5:
            parts.append(f"24h跌幅{abs(momentum):.1f}%，或有超跌反弹机会")
        else:
            parts.append(f"24h变动{momentum:.1f}%，表现平稳")

        if volume > 0:
            parts.append(f"成交量活跃")

        if buy_ratio > 0.6:
            parts.append("买盘占优")
        elif buy_ratio < 0.4:
            parts.append("卖盘占优")

        reason = "，".join(parts)

        # 简单加减分逻辑
        adjustment = 0.0
        if momentum > 10:
            adjustment += 3.0
        elif momentum < -10:
            adjustment -= 3.0
        if buy_ratio > 0.65:
            adjustment += 2.0
        elif buy_ratio < 0.35:
            adjustment -= 2.0
        adjustment = max(-20.0, min(20.0, adjustment))

        # 置信度：数据越丰富越可信
        factor_count = sum(1 for v in factors.values() if v != 0)
        confidence = min(0.5 + factor_count * 0.1, 1.0)

        return LLMReview(
            reason=reason,
            adjustment=adjustment,
            confidence=confidence,
        )


# ──────────────────────────── 主流水线 ────────────────────────────


class ScreenerPipeline:
    """选股选币流水线。

    全市场标的池
     → 一级过滤(流动性/市值/上市时长/可交易性)
     → 因子计算(动量/价值/质量/波动/资金流/链上)
     → ML 打分(XGBoost/LightGBM 排序,预期收益分位)
     → LLM 复核(基本面/消息面/事件面定性加减分)
     → 风险约束(行业/板块/相关性分散,单标的上限)
     → 候选池(Top-N,带分数/理由/置信度)

    Attributes:
        factor_lib: 因子库（可注入自定义实现）。
        ml_model: ML 模型（可注入 XGBoost/LightGBM）。
        llm_provider: LLM 提供者（可注入 GPT/DeepSeek 等）。
        min_volume_24h: 最小 24h 成交量。
        min_market_cap: 最小市值。
        min_listing_days: 最小上市天数。
        max_per_sector: 同行业最大标的数。
        max_per_market: 同市场最大标的数。
        max_correlation: 最大允许相关性系数。
        top_n: 候选池大小。
    """

    def __init__(
        self,
        factor_lib: Any = None,
        ml_model: Any = None,
        llm_provider: Any = None,
        min_volume_24h: Decimal = Decimal("100000"),
        min_market_cap: Decimal = Decimal("10000000"),
        min_listing_days: int = 30,
        max_per_sector: int = 3,
        max_per_market: int = 5,
        max_correlation: float = 0.7,
        top_n: int = 20,
    ) -> None:
        """初始化选股流水线。

        Args:
            factor_lib: 因子库，默认使用 DefaultFactorLibrary。
            ml_model: ML 模型，默认使用 DefaultMLModel。
            llm_provider: LLM 提供者，默认使用 DefaultLLMProvider。
            min_volume_24h: 最小 24h 成交量。
            min_market_cap: 最小市值。
            min_listing_days: 最小上市天数。
            max_per_sector: 同行业最大标的数。
            max_per_market: 同市场最大标的数。
            max_correlation: 最大允许相关性系数。
            top_n: 候选池大小。
        """
        self._factor_lib = factor_lib or DefaultFactorLibrary()
        self._ml_model = ml_model or DefaultMLModel()
        self._llm = llm_provider or DefaultLLMProvider()
        self.min_volume_24h = min_volume_24h
        self.min_market_cap = min_market_cap
        self.min_listing_days = min_listing_days
        self.max_per_sector = max_per_sector
        self.max_per_market = max_per_market
        self.max_correlation = max_correlation
        self.top_n = top_n
        self._run_count = 0

    async def run(
        self,
        instruments: list[Instrument],
        market_data: dict[str, Any],
        top_n: int | None = None,
    ) -> list[CandidateAsset]:
        """执行选股选币。

        完整流水线：一级过滤 → 因子计算 → ML 打分 → LLM 复核 → 风险约束 → 候选池

        Args:
            instruments: 全市场标的列表。
            market_data: 市场数据（ticker、成交量、市值等）。
            top_n: 候选池大小，为 None 时使用初始化值。

        Returns:
            候选池（按 final_score 降序，包含分数/理由/置信度/因子明细）。
        """
        self._run_count += 1
        start = time.time()
        effective_top_n = top_n if top_n is not None else self.top_n

        # 1. 一级过滤
        filtered = self._primary_filter(instruments, market_data)
        logger.info("一级过滤: %d → %d 标的", len(instruments), len(filtered))

        if not filtered:
            logger.warning("一级过滤后无标的，返回空候选池")
            return []

        # 2. 因子计算
        features = self._compute_features(filtered, market_data)
        logger.info("因子计算: %d 标的", len(features))

        # 3. ML 打分
        scored = self._ml_score(features)
        logger.info("ML 打分: %d 标的", len(scored))

        # 4. LLM 复核
        reviewed = await self._llm_review(scored, features, market_data)
        logger.info("LLM 复核: %d 标的", len(reviewed))

        # 5. 风险约束
        constrained = self._apply_constraints(reviewed)
        logger.info("风险约束: %d → %d 标的", len(reviewed), len(constrained))

        # 6. 取 Top-N
        candidates = constrained[:effective_top_n]

        elapsed = time.time() - start
        logger.info(
            "选股完成: %d 候选，耗时 %.2fs",
            len(candidates),
            elapsed,
        )

        return candidates

    def _primary_filter(
        self,
        instruments: list[Instrument],
        market_data: dict[str, Any],
    ) -> list[str]:
        """一级过滤：流动性 / 市值 / 上市时长 / 可交易性。

        Args:
            instruments: 全市场标的列表。
            market_data: 市场数据。

        Returns:
            通过全部过滤的标的符号列表。
        """
        # 剔除不可活跃标的
        symbols = [inst.symbol for inst in instruments if inst.is_active]

        # 可交易性过滤
        tradable: list[str] = []
        for sym in symbols:
            ticker = market_data.get(sym, {})
            if ticker.get("is_tradable", True):
                tradable.append(sym)

        # 流动性过滤
        liquid: list[str] = []
        for sym in tradable:
            ticker = market_data.get(sym, {})
            volume = Decimal(str(ticker.get("volume_24h", "0")))
            if volume >= self.min_volume_24h:
                liquid.append(sym)

        # 市值过滤
        cap_ok: list[str] = []
        for sym in liquid:
            ticker = market_data.get(sym, {})
            cap = Decimal(str(ticker.get("market_cap", "0")))
            if cap >= self.min_market_cap:
                cap_ok.append(sym)

        # 上市时长过滤
        now_ts = time.time()
        age_ok: list[str] = []
        for sym in cap_ok:
            ticker = market_data.get(sym, {})
            listing_date = ticker.get("listing_date")
            if listing_date is None:
                age_ok.append(sym)
                continue
            try:
                if isinstance(listing_date, (int, float)):
                    age_days = (now_ts - listing_date) / 86400
                else:
                    from datetime import datetime, timezone

                    dt = datetime.fromisoformat(str(listing_date))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    age_days = (now_ts - dt.timestamp()) / 86400
                if age_days >= self.min_listing_days:
                    age_ok.append(sym)
            except (ValueError, TypeError, OSError):
                # 日期格式异常，默认通过
                age_ok.append(sym)

        logger.debug(
            "过滤链: %d → %d(活跃) → %d(可交易) → %d(流动性) → %d(市值) → %d(上市时长)",
            len(symbols),
            len(symbols),
            len(tradable),
            len(liquid),
            len(cap_ok),
            len(age_ok),
        )

        return age_ok

    def _compute_features(
        self,
        symbols: list[str],
        market_data: dict[str, Any],
    ) -> dict[str, dict[str, float]]:
        """计算因子。

        调用因子库为每个标的计算全部因子，返回浮点数特征矩阵
        供 ML 模型消费。

        Args:
            symbols: 通过过滤的标的符号列表。
            market_data: 市场数据。

        Returns:
            标的符号 → 因子名 → 因子值（float）。
        """
        features: dict[str, dict[str, float]] = {}
        for sym in symbols:
            raw_factors = self._factor_lib.compute(sym, market_data)
            if raw_factors:
                # Decimal → float，供 ML 模型消费
                features[sym] = {
                    k: float(v) for k, v in raw_factors.items()
                }
        return features

    def _ml_score(
        self,
        features: dict[str, dict[str, float]],
    ) -> list[tuple[str, float, dict[str, float]]]:
        """ML 打分排序。

        调用 ML 模型对每个标的预测得分，并按得分降序排列。

        Args:
            features: 标的符号 → 因子名 → 因子值。

        Returns:
            [(符号, 得分, 因子明细)] 按得分降序。
        """
        raw_scores = self._ml_model.predict(features)

        scored: list[tuple[str, float, dict[str, float]]] = []
        for symbol, score in raw_scores.items():
            factor_detail = features.get(symbol, {})
            scored.append((symbol, score, factor_detail))

        # 按得分降序排列
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    async def _llm_review(
        self,
        scored: list[tuple[str, float, dict[str, float]]],
        features: dict[str, dict[str, float]],
        market_data: dict[str, Any],
    ) -> list[CandidateAsset]:
        """LLM 复核层。

        对 ML 打分结果进行定性分析，输出中文理由、加减分和置信度。
        最终得分 = ML 得分 + LLM 加减分。

        Args:
            scored: [(符号, ML得分, 因子明细)]。
            features: 全量特征矩阵。
            market_data: 市场数据。

        Returns:
            候选标的列表（含 LLM 复核结果）。
        """
        candidates: list[CandidateAsset] = []
        now_ns = int(time.time() * 1e9)

        for symbol, ml_score, factor_detail in scored:
            # 调用 LLM 复核
            review = await self._llm.review(
                symbol=symbol,
                score=ml_score,
                factors=factor_detail,
                market_data=market_data,
            )

            # 计算最终得分，限制在 0~100
            final_score = max(0.0, min(100.0, ml_score + review.adjustment))

            # 获取市场信息
            ticker = market_data.get(symbol, {})
            market = ticker.get("market", Market.SPOT)
            if isinstance(market, str):
                try:
                    market = Market(market)
                except ValueError:
                    market = Market.SPOT

            candidate = CandidateAsset(
                symbol=symbol,
                market=market.value if isinstance(market, Market) else str(market),
                score=round(ml_score, 2),
                llm_adjustment=round(review.adjustment, 2),
                final_score=round(final_score, 2),
                confidence=round(review.confidence, 3),
                reason=review.reason,
                factors=factor_detail,
                timestamp_ns=now_ns,
            )
            candidates.append(candidate)

        return candidates

    def _apply_constraints(
        self,
        candidates: list[CandidateAsset],
    ) -> list[CandidateAsset]:
        """风险约束：行业 / 市场 / 相关性分散 + 单标的上限。

        Args:
            candidates: 候选标的列表。

        Returns:
            通过风险约束的候选标的列表。
        """
        # 按最终得分降序排列
        candidates = sorted(
            candidates, key=lambda c: c.final_score, reverse=True
        )

        # 1. 分散化约束：行业 / 市场
        candidates = self._apply_diversification(candidates)

        # 2. 相关性约束（如有相关性数据）
        # 这里预留接口，实际相关性矩阵由外部注入

        return candidates

    def _apply_diversification(
        self,
        candidates: list[CandidateAsset],
    ) -> list[CandidateAsset]:
        """行业 / 市场分散化约束。

        Args:
            candidates: 候选标的列表（应已按 final_score 降序排列）。

        Returns:
            通过分散化约束的候选标的列表。
        """
        from collections import Counter

        sector_count: Counter[str] = Counter()
        market_count: Counter[str] = Counter()
        result: list[CandidateAsset] = []

        for candidate in candidates:
            sector = str(candidate.factors.get("sector", "未知"))
            market = candidate.market

            if sector_count[sector] >= self.max_per_sector:
                logger.debug(
                    "分散化: %s 行业 %s 达上限 %d",
                    candidate.symbol,
                    sector,
                    self.max_per_sector,
                )
                continue

            if market_count[market] >= self.max_per_market:
                logger.debug(
                    "分散化: %s 市场 %s 达上限 %d",
                    candidate.symbol,
                    market,
                    self.max_per_market,
                )
                continue

            sector_count[sector] += 1
            market_count[market] += 1
            result.append(candidate)

        return result

    @property
    def stats(self) -> dict[str, int]:
        """统计信息。"""
        return {"run_count": self._run_count}

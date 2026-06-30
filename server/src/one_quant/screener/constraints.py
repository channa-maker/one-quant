"""
ONE量化 - 风险约束模块

候选池输出前的风险控制层：
- 分散化约束：行业/板块/市场集中度控制
- 相关性约束：高相关标的剔除，避免重复暴露
"""

from __future__ import annotations

import logging
from collections import Counter
from decimal import Decimal

from one_quant.screener.pipeline import CandidateAsset

logger = logging.getLogger(__name__)


class DiversificationConstraint:
    """分散化约束。

    通过限制同一行业/板块/市场的标的数量，实现候选池的分散化配置，
    避免过度集中在单一领域。
    """

    def apply(
        self,
        candidates: list[CandidateAsset],
        max_per_sector: int = 3,
        max_per_market: int = 5,
        sector_key: str = "sector",
    ) -> list[CandidateAsset]:
        """应用分散化约束。

        按 final_score 降序遍历候选标的，对每个行业/市场进行配额控制，
        超出配额的标的被剔除。

        Args:
            candidates: 候选标的列表（应已按 final_score 降序排列）。
            max_per_sector: 同一行业最大标的数。
            max_per_market: 同一市场最大标的数。
            sector_key: 行业信息在 factors 字典中的键名。

        Returns:
            通过分散化约束的候选标的列表。
        """
        # 按最终得分降序排列（确保高分优先保留）
        sorted_candidates = sorted(candidates, key=lambda c: c.final_score, reverse=True)

        sector_count: Counter[str] = Counter()
        market_count: Counter[str] = Counter()
        result: list[CandidateAsset] = []

        for candidate in sorted_candidates:
            # 获取行业信息
            sector = str(candidate.factors.get(sector_key, "未知"))
            market = candidate.market

            # 检查行业配额
            if sector_count[sector] >= max_per_sector:
                logger.debug(
                    "分散化约束: %s 行业 %s 已达上限 %d",
                    candidate.symbol,
                    sector,
                    max_per_sector,
                )
                continue

            # 检查市场配额
            if market_count[market] >= max_per_market:
                logger.debug(
                    "分散化约束: %s 市场 %s 已达上限 %d",
                    candidate.symbol,
                    market,
                    max_per_market,
                )
                continue

            sector_count[sector] += 1
            market_count[market] += 1
            result.append(candidate)

        logger.info(
            "分散化约束: %d → %d 标的（行业上限 %d, 市场上限 %d）",
            len(candidates),
            len(result),
            max_per_sector,
            max_per_market,
        )
        return result


class CorrelationConstraint:
    """相关性约束。

    剔除高度相关的标的对，避免候选池中存在重复暴露。
    当两个标的相关性超过阈值时，保留得分较高的标的。
    """

    def apply(
        self,
        candidates: list[CandidateAsset],
        max_corr: float = 0.7,
        correlation_matrix: dict[tuple[str, str], float] | None = None,
    ) -> list[CandidateAsset]:
        """应用相关性约束。

        遍历候选标的对，当相关性超过阈值时，剔除得分较低的标的。

        Args:
            candidates: 候选标的列表。
            max_corr: 最大允许相关性系数（0~1）。
            correlation_matrix: 相关性矩阵，键为 (symbol_a, symbol_b) 元组，
                               值为相关性系数。未提供时跳过相关性检查。

        Returns:
            通过相关性约束的候选标的列表。
        """
        if not correlation_matrix:
            logger.info("相关性约束: 无相关性数据，跳过检查")
            return candidates

        # 按最终得分降序排列
        sorted_candidates = sorted(candidates, key=lambda c: c.final_score, reverse=True)

        removed: set[str] = set()
        result: list[CandidateAsset] = []

        for i, candidate in enumerate(sorted_candidates):
            if candidate.symbol in removed:
                continue

            # 检查与已保留标的的相关性
            is_correlated = False
            for kept in result:
                corr_key = (candidate.symbol, kept.symbol)
                corr_key_rev = (kept.symbol, candidate.symbol)
                corr = correlation_matrix.get(corr_key, correlation_matrix.get(corr_key_rev, 0.0))
                if abs(corr) > max_corr:
                    logger.debug(
                        "相关性约束: %s 与 %s 相关性 %.3f > %.3f，剔除 %s",
                        candidate.symbol,
                        kept.symbol,
                        corr,
                        max_corr,
                        candidate.symbol,
                    )
                    is_correlated = True
                    removed.add(candidate.symbol)
                    break

            if not is_correlated:
                result.append(candidate)

        logger.info(
            "相关性约束: %d → %d 标的（阈值 %.2f，剔除 %d）",
            len(candidates),
            len(result),
            max_corr,
            len(removed),
        )
        return result


class PositionLimitConstraint:
    """单标的持仓上限约束。

    限制单个标的在候选池中的权重上限，防止单一标的过度集中。
    """

    def apply(
        self,
        candidates: list[CandidateAsset],
        max_weight: Decimal = Decimal("0.2"),
    ) -> list[CandidateAsset]:
        """应用单标的持仓上限约束。

        按 final_score 降序排列，对超出权重上限的标的进行截断或剔除。

        Args:
            candidates: 候选标的列表。
            max_weight: 单标的最大权重（0~1）。

        Returns:
            通过持仓上限约束的候选标的列表。
        """
        if not candidates:
            return candidates

        # 按最终得分降序排列
        sorted_candidates = sorted(candidates, key=lambda c: c.final_score, reverse=True)

        # 计算总得分用于归一化权重
        total_score = Decimal(str(sum(c.final_score for c in sorted_candidates)))
        if total_score <= 0:
            logger.warning("持仓上限约束: 总得分 <= 0，跳过")
            return sorted_candidates

        result: list[CandidateAsset] = []
        for candidate in sorted_candidates:
            weight = Decimal(str(candidate.final_score)) / total_score
            if weight <= max_weight:
                result.append(candidate)
            else:
                logger.debug(
                    "持仓上限约束: %s 权重 %.4f > 上限 %s",
                    candidate.symbol,
                    weight,
                    max_weight,
                )
                # 权重超标但仍保留，实际交易时由执行层控制仓位

        logger.info(
            "持仓上限约束: %d → %d 标的（权重上限 %s）",
            len(candidates),
            len(result),
            max_weight,
        )
        return result

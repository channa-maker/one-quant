"""
B-5 多源数据故障转移 — FailoverManager

主源失败→备源自动切换，支持字段级合并降级。
"""

from __future__ import annotations

import asyncio
from typing import Any

from one_quant.data.data_source import (
    DataSourceError,
    FetchResult,
    FieldDegradeInfo,
    NotSupportedField,
)
from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


class FailoverManager:
    """多源故障转移管理器。

    按优先级依次尝试数据源，主源失败自动切备源。
    支持字段级合并：源A缺的字段从源B补充。

    Attributes:
        _sources: 数据源列表（按优先级排列）。
        _merge_fields: 是否启用字段级合并。
        _health: 各源健康状态。
    """

    def __init__(
        self,
        sources: list[Any],
        merge_fields: bool = False,
    ) -> None:
        """初始化故障转移管理器。

        Args:
            sources: 数据源列表，按优先级排列。
            merge_fields: 是否启用字段级合并（从备源补充主源缺失字段）。
        """
        self._sources = sources
        self._merge_fields = merge_fields
        self._health: dict[str, dict[str, Any]] = {}

    async def fetch_ticker(self, symbol: str) -> FetchResult:
        """获取实时行情，自动故障转移。

        Args:
            symbol: 标的符号。

        Returns:
            FetchResult 结果对象。

        Raises:
            ValueError: 无可用数据源。
            DataSourceError: 所有数据源均失败。
        """
        if not self._sources:
            raise ValueError("无可用数据源")

        errors: list[str] = []
        first_result: FetchResult | None = None

        for source in self._sources:
            source_name = source.name
            try:
                result = await source.fetch_ticker(symbol)
                self._mark_healthy(source_name)

                if first_result is None:
                    first_result = result

                    # 如果不需要字段合并，直接返回第一个成功的结果
                    if not self._merge_fields:
                        return first_result

                    # 合并模式下，继续尝试后续源以补充更多字段
                    # 但如果没有 NotSupportedField 且没有后续源，会在循环结束后返回
                    continue

                # 字段合并模式：用后续源补充缺失字段
                if self._merge_fields and first_result is not None:
                    first_result = self._merge_results(first_result, result)

                    # 检查是否还有 NotSupportedField
                    still_unsupported = any(
                        v is NotSupportedField for v in first_result.data.values()
                    )
                    if not still_unsupported:
                        # 所有字段都有值了，但继续尝试后续源获取更多字段
                        # 只有在没有更多源时才返回
                        pass

            except Exception as exc:
                self._mark_unhealthy(source_name, str(exc))
                normalized = self._normalize_error(exc, source_name)
                errors.append(str(normalized))
                logger.warning("数据源 %s 失败: %s", source_name, normalized)
                continue

        # 有部分结果（字段合并模式）
        if first_result is not None:
            return first_result

        # 所有源都失败
        raise DataSourceError(
            f"所有数据源均失败: {'; '.join(errors)}",
            errors=errors,
        )

    def _merge_results(self, primary: FetchResult, secondary: FetchResult) -> FetchResult:
        """合并两个结果，用 secondary 补充 primary 的缺失字段。

        Args:
            primary: 主结果。
            secondary: 补充结果。

        Returns:
            合并后的 FetchResult。
        """
        merged_data: dict[str, Any] = {}
        merged_degrades: list[FieldDegradeInfo] = list(primary.degrades)

        for field_name, primary_value in primary.data.items():
            if primary_value is NotSupportedField:
                secondary_value = secondary.data.get(field_name, NotSupportedField)
                if secondary_value is not NotSupportedField:
                    merged_data[field_name] = secondary_value
                    # 移除该字段的降级记录
                    merged_degrades = [d for d in merged_degrades if d.field != field_name]
                    logger.info(
                        "字段 %s 从 %s 补充成功",
                        field_name,
                        secondary.source,
                    )
                else:
                    merged_data[field_name] = NotSupportedField
            else:
                merged_data[field_name] = primary_value

        # 补充 secondary 中有但 primary 中没有的字段
        # 补充 secondary 中有但 primary 中没有的字段
        for field_name, value in secondary.data.items():
            if field_name not in merged_data and value is not NotSupportedField:
                merged_data[field_name] = value
                logger.info(
                    "字段 %s 从 %s 补充（primary 无此字段）",
                    field_name,
                    secondary.source,
                )

        return FetchResult(
            data=merged_data,
            source=f"{primary.source}+{secondary.source}",
            degrades=merged_degrades,
        )

    def _normalize_error(self, exc: Exception, source_name: str) -> DataSourceError:
        """将各类异常归一化为 DataSourceError。

        Args:
            exc: 原始异常。
            source_name: 数据源名称。

        Returns:
            归一化后的 DataSourceError。
        """
        if isinstance(exc, DataSourceError):
            return exc

        if isinstance(exc, asyncio.TimeoutError):
            return DataSourceError(
                f"{source_name}: 请求超时",
                source=source_name,
                original=exc,
            )

        if isinstance(exc, ConnectionError):
            return DataSourceError(
                f"{source_name}: 连接失败 - {exc}",
                source=source_name,
                original=exc,
            )

        return DataSourceError(
            f"{source_name}: 未知错误 - {exc}",
            source=source_name,
            original=exc,
        )

    def _mark_healthy(self, source_name: str) -> None:
        """标记源为健康。"""
        self._health[source_name] = {"healthy": True, "last_error": None}

    def _mark_unhealthy(self, source_name: str, error: str) -> None:
        """标记源为不健康。"""
        self._health[source_name] = {"healthy": False, "last_error": error}

    def get_health_status(self) -> dict[str, dict[str, Any]]:
        """获取所有数据源的健康状态。

        Returns:
            健康状态字典，key 为源名称，value 包含 healthy 和 last_error。
        """
        return dict(self._health)

"""B-5 多源数据故障转移测试

测试场景：
1. 主源故障自动切备源
2. 字段级降级（not_supported 标记）
3. 异常归一化
4. 不崩（全部源失败时优雅降级）
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from one_quant.data.data_source import (
    DataSourceCapability,
    FetchResult,
    FieldDegradeInfo,
    NotSupportedField,
)
from one_quant.data.failover import FailoverManager

# ──────────────────── Mock 数据源 ────────────────────


class MockDataSource:
    """模拟数据源，可控失败。"""

    def __init__(
        self,
        name: str,
        capabilities: dict[str, DataSourceCapability],
        ticker_data: dict[str, Any] | None = None,
        should_fail: bool = False,
        fail_fields: set[str] | None = None,
    ) -> None:
        self.name = name
        self._capabilities = capabilities
        self._ticker_data = ticker_data or {}
        self._should_fail = should_fail
        self._fail_fields = fail_fields or set()
        self.call_count = 0

    def get_capabilities(self) -> dict[str, DataSourceCapability]:
        return self._capabilities

    async def fetch_ticker(self, symbol: str) -> FetchResult:
        self.call_count += 1
        if self._should_fail:
            raise ConnectionError(f"{self.name}: 连接超时")

        # 检查字段级降级
        degrades: list[FieldDegradeInfo] = []
        data: dict[str, Any] = {}
        for field_name, value in self._ticker_data.items():
            if field_name in self._fail_fields:
                degrades.append(
                    FieldDegradeInfo(
                        field=field_name,
                        reason=f"{self.name} 不支持该字段",
                        fallback_value=None,
                    )
                )
                data[field_name] = NotSupportedField
            else:
                data[field_name] = value

        return FetchResult(data=data, source=self.name, degrades=degrades)


# ──────────────────── 测试: 能力声明 ────────────────────


class TestDataSourceCapability:
    """测试 DataSource 协议的能力声明。"""

    def test_capability_fields(self):
        """能力声明应包含支持的字段和市场。"""
        cap = DataSourceCapability(
            supported_fields=["last_price", "bid", "ask", "volume_24h"],
            supported_markets=["SPOT", "FUTURES"],
            rate_limit_per_min=120,
        )
        assert "last_price" in cap.supported_fields
        assert "SPOT" in cap.supported_markets
        assert cap.rate_limit_per_min == 120

    def test_capability_is_not_supported(self):
        """查询不支持的字段应返回 False。"""
        cap = DataSourceCapability(
            supported_fields=["last_price", "bid"],
            supported_markets=["SPOT"],
        )
        assert cap.is_field_supported("last_price") is True
        assert cap.is_field_supported("open_interest") is False

    def test_capability_market_support(self):
        """查询不支持的市场应返回 False。"""
        cap = DataSourceCapability(
            supported_fields=["last_price"],
            supported_markets=["SPOT"],
        )
        assert cap.is_market_supported("SPOT") is True
        assert cap.is_market_supported("OPTION") is False


# ──────────────────── 测试: FetchResult ────────────────────


class TestFetchResult:
    """测试 FetchResult 数据结构。"""

    def test_fetch_result_with_degrades(self):
        """FetchResult 应携带降级信息。"""
        result = FetchResult(
            data={"last_price": Decimal("50000"), "open_interest": NotSupportedField},
            source="source_a",
            degrades=[
                FieldDegradeInfo(
                    field="open_interest",
                    reason="source_a 不支持该字段",
                    fallback_value=None,
                )
            ],
        )
        assert result.source == "source_a"
        assert result.has_degrades is True
        assert result.degraded_fields == ["open_interest"]

    def test_fetch_result_no_degrades(self):
        """无降级时 has_degrades 应为 False。"""
        result = FetchResult(
            data={"last_price": Decimal("50000")},
            source="source_a",
        )
        assert result.has_degrades is False
        assert result.degraded_fields == []


# ──────────────────── 测试: 主源故障切备源 ────────────────────


class TestFailover:
    """测试故障转移核心逻辑。"""

    @pytest.mark.asyncio
    async def test_primary_fail_fallback_to_secondary(self):
        """主源故障时应自动切到备源。"""
        primary = MockDataSource(
            name="primary",
            capabilities={
                "ticker": DataSourceCapability(
                    supported_fields=["last_price", "bid", "ask"],
                    supported_markets=["SPOT"],
                )
            },
            should_fail=True,
        )
        secondary = MockDataSource(
            name="secondary",
            capabilities={
                "ticker": DataSourceCapability(
                    supported_fields=["last_price", "bid", "ask"],
                    supported_markets=["SPOT"],
                )
            },
            ticker_data={
                "last_price": Decimal("50000"),
                "bid": Decimal("49999"),
                "ask": Decimal("50001"),
            },
        )

        manager = FailoverManager(sources=[primary, secondary])
        result = await manager.fetch_ticker("BTCUSDT")

        assert result.source == "secondary"
        assert result.data["last_price"] == Decimal("50000")
        assert primary.call_count == 1  # 主源被调用过
        assert secondary.call_count == 1  # 备源也被调用

    @pytest.mark.asyncio
    async def test_primary_success_no_fallback(self):
        """主源正常时不应调用备源。"""
        primary = MockDataSource(
            name="primary",
            capabilities={
                "ticker": DataSourceCapability(
                    supported_fields=["last_price"],
                    supported_markets=["SPOT"],
                )
            },
            ticker_data={"last_price": Decimal("50000")},
        )
        secondary = MockDataSource(
            name="secondary",
            capabilities={
                "ticker": DataSourceCapability(
                    supported_fields=["last_price"],
                    supported_markets=["SPOT"],
                )
            },
            ticker_data={"last_price": Decimal("50001")},
        )

        manager = FailoverManager(sources=[primary, secondary])
        result = await manager.fetch_ticker("BTCUSDT")

        assert result.source == "primary"
        assert primary.call_count == 1
        assert secondary.call_count == 0  # 备源未被调用


# ──────────────────── 测试: 字段级降级 ────────────────────


class TestFieldDegrade:
    """测试字段级降级逻辑。"""

    @pytest.mark.asyncio
    async def test_field_not_supported_marks_degrade(self):
        """某源不支持的字段应标记为 not_supported 而非报错。"""
        source_a = MockDataSource(
            name="source_a",
            capabilities={
                "ticker": DataSourceCapability(
                    supported_fields=["last_price", "bid"],
                    supported_markets=["SPOT"],
                )
            },
            ticker_data={
                "last_price": Decimal("50000"),
                "bid": Decimal("49999"),
                "open_interest": None,
            },
            fail_fields={"open_interest"},
        )

        manager = FailoverManager(sources=[source_a])
        result = await manager.fetch_ticker("BTCUSDT")

        # last_price 正常
        assert result.data["last_price"] == Decimal("50000")
        # open_interest 被标记为不支持
        assert result.data["open_interest"] is NotSupportedField
        assert result.has_degrades is True
        assert "open_interest" in result.degraded_fields

    @pytest.mark.asyncio
    async def test_cross_source_field_merge(self):
        """多源互补：源A缺的字段从源B补充。"""
        source_a = MockDataSource(
            name="source_a",
            capabilities={
                "ticker": DataSourceCapability(
                    supported_fields=["last_price", "bid"],
                    supported_markets=["SPOT"],
                )
            },
            ticker_data={"last_price": Decimal("50000"), "bid": Decimal("49999")},
        )
        source_b = MockDataSource(
            name="source_b",
            capabilities={
                "ticker": DataSourceCapability(
                    supported_fields=["last_price", "bid", "open_interest"],
                    supported_markets=["SPOT"],
                )
            },
            ticker_data={
                "last_price": Decimal("50001"),
                "bid": Decimal("50000"),
                "open_interest": Decimal("12345"),
            },
        )

        manager = FailoverManager(sources=[source_a, source_b], merge_fields=True)
        result = await manager.fetch_ticker("BTCUSDT")

        # 从源A获取基础数据
        assert result.data["last_price"] == Decimal("50000")
        # open_interest 从源B补充
        assert result.data["open_interest"] == Decimal("12345")


# ──────────────────── 测试: 全部源失败不崩 ────────────────────


class TestAllSourcesFail:
    """测试全部数据源失败时的优雅降级。"""

    @pytest.mark.asyncio
    async def test_all_sources_fail_raises_aggregate_error(self):
        """所有源都失败时应抛出聚合异常，而非静默吞掉。"""
        source_a = MockDataSource(
            name="source_a",
            capabilities={},
            should_fail=True,
        )
        source_b = MockDataSource(
            name="source_b",
            capabilities={},
            should_fail=True,
        )

        manager = FailoverManager(sources=[source_a, source_b])

        with pytest.raises(Exception) as exc_info:
            await manager.fetch_ticker("BTCUSDT")

        # 异常应包含所有源的错误信息
        assert "source_a" in str(exc_info.value)
        assert "source_b" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_empty_sources_raises(self):
        """无数据源时应立即报错。"""
        manager = FailoverManager(sources=[])
        with pytest.raises(ValueError, match="无可用数据源"):
            await manager.fetch_ticker("BTCUSDT")


# ──────────────────── 测试: 异常归一化 ────────────────────


class TestErrorNormalization:
    """测试异常归一化。"""

    @pytest.mark.asyncio
    async def test_different_errors_normalized(self):
        """不同类型的异常应被归一化为统一的 DataSourceError。"""
        from one_quant.data.data_source import DataSourceError

        class TimeoutSource(MockDataSource):
            async def fetch_ticker(self, symbol: str) -> FetchResult:
                self.call_count += 1
                raise TimeoutError("请求超时")

        class HTTPSource(MockDataSource):
            async def fetch_ticker(self, symbol: str) -> FetchResult:
                self.call_count += 1
                raise ConnectionError("HTTP 503")

        source_a = TimeoutSource(name="timeout_src", capabilities={})
        source_b = HTTPSource(name="http_src", capabilities={})

        manager = FailoverManager(sources=[source_a, source_b])

        with pytest.raises(DataSourceError):
            await manager.fetch_ticker("BTCUSDT")

    @pytest.mark.asyncio
    async def test_health_status_tracking(self):
        """故障源应被标记为不健康。"""
        primary = MockDataSource(
            name="primary",
            capabilities={},
            should_fail=True,
        )
        secondary = MockDataSource(
            name="secondary",
            capabilities={},
            ticker_data={"last_price": Decimal("50000")},
        )

        manager = FailoverManager(sources=[primary, secondary])
        await manager.fetch_ticker("BTCUSDT")

        health = manager.get_health_status()
        assert health["primary"]["healthy"] is False
        assert health["secondary"]["healthy"] is True

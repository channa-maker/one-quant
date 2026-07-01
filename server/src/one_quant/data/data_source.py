"""
B-5 多源数据故障转移 — DataSource 协议 + 能力声明

设计原则：
- DataSource 协议定义统一数据源接口
- capabilities() 声明每个源支持的字段和市场
- 字段级降级：不支持的字段标 NotSupportedField 而非报错
- 异常归一化：所有源错误统一为 DataSourceError
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# ──────────────────── 异常归一化 ────────────────────


class DataSourceError(Exception):
    """数据源统一异常基类。

    所有数据源的原始异常都归一化为此类型，
    包含源名称、原始异常、聚合错误信息。
    """

    def __init__(
        self,
        message: str,
        source: str = "",
        original: Exception | None = None,
        errors: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.source = source
        self.original = original
        self.errors = errors or []


# ──────────────────── 不支持字段哨兵值 ────────────────────


class _NotSupportedField:
    """哨兵值：标记某字段在当前数据源中不支持。

    使用方式：data["open_interest"] = NotSupportedField
    检查方式：if value is NotSupportedField: ...
    """

    _instance: _NotSupportedField | None = None

    def __new__(cls) -> _NotSupportedField:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "<NotSupportedField>"

    def __bool__(self) -> bool:
        return False


NotSupportedField = _NotSupportedField()


# ──────────────────── 能力声明 ────────────────────


@dataclass(frozen=True)
class DataSourceCapability:
    """数据源能力声明。

    Attributes:
        supported_fields: 支持的字段列表（如 "last_price", "bid", "ask", "open_interest"）。
        supported_markets: 支持的市场列表（如 "SPOT", "FUTURES"）。
        rate_limit_per_min: 每分钟请求限制（0 表示无限制）。
    """

    supported_fields: list[str] = field(default_factory=list)
    supported_markets: list[str] = field(default_factory=list)
    rate_limit_per_min: int = 0

    def is_field_supported(self, field_name: str) -> bool:
        """查询字段是否支持。"""
        return field_name in self.supported_fields

    def is_market_supported(self, market: str) -> bool:
        """查询市场是否支持。"""
        return market in self.supported_markets


# ──────────────────── 字段降级信息 ────────────────────


@dataclass(frozen=True)
class FieldDegradeInfo:
    """字段降级记录。

    当某字段在当前源不支持时，记录降级原因和回退值。

    Attributes:
        field: 降级字段名。
        reason: 降级原因。
        fallback_value: 回退值（None 表示无回退）。
    """

    field: str
    reason: str
    fallback_value: Any = None


# ──────────────────── 获取结果 ────────────────────


@dataclass
class FetchResult:
    """数据获取结果。

    Attributes:
        data: 获取到的数据字典，值可能为 NotSupportedField。
        source: 数据来源名称。
        degrades: 字段降级信息列表。
    """

    data: dict[str, Any]
    source: str
    degrades: list[FieldDegradeInfo] = field(default_factory=list)

    @property
    def has_degrades(self) -> bool:
        """是否有字段降级。"""
        return len(self.degrades) > 0

    @property
    def degraded_fields(self) -> list[str]:
        """降级字段名列表。"""
        return [d.field for d in self.degrades]


# ──────────────────── DataSource 协议 ────────────────────


@runtime_checkable
class DataSource(Protocol):
    """数据源协议。

    所有数据源实现此协议，提供统一接口。
    """

    name: str

    def get_capabilities(self) -> dict[str, DataSourceCapability]:
        """获取数据源能力声明。

        Returns:
            能力字典，key 为数据类型（如 "ticker", "kline", "orderbook"），
            value 为 DataSourceCapability。
        """
        ...

    async def fetch_ticker(self, symbol: str) -> FetchResult:
        """获取实时行情。

        Args:
            symbol: 标的符号。

        Returns:
            FetchResult 结果对象。
        """
        ...

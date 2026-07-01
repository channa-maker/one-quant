"""
ONE量化 - 数据层

数据采集、数据湖（Bronze/Silver/Gold）、质检、特征商店。
"""

from one_quant.data.collector import DataCollector
from one_quant.data.data_source import (
    DataSource,
    DataSourceCapability,
    DataSourceError,
    FetchResult,
    FieldDegradeInfo,
    NotSupportedField,
)
from one_quant.data.failover import FailoverManager
from one_quant.data.tick_collector import TickCollector

__all__ = [
    "DataCollector",
    "DataSource",
    "DataSourceCapability",
    "DataSourceError",
    "FailoverManager",
    "FetchResult",
    "FieldDegradeInfo",
    "NotSupportedField",
    "TickCollector",
]

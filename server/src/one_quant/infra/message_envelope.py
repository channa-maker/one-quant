"""
ONE量化 - 消息信封

定义统一的消息信封模型，用于在各组件间传递标准化消息。
所有内部消息都封装在 MessageEnvelope 中，确保:
- 可追溯性 (trace_id)
- 时序一致性 (ts_ns)
- 版本兼容性 (schema_version)
"""

from __future__ import annotations

import time
import uuid
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

# 泛型类型变量
T = TypeVar("T")


class MessageEnvelope(BaseModel, Generic[T]):
    """
    消息信封模型。

    所有模块间传递的消息都应使用此信封封装。
    使用纳秒级时间戳确保高并发场景下的时序精度。

    Attributes:
        channel: 消息通道标识，如 ``"market.tick"``, ``"order.update"``
        schema_version: 数据结构版本号，用于向前/向后兼容
        seq: 序列号，在同一 channel 内单调递增
        ts_ns: 纳秒级时间戳 (Unix epoch)
        trace_id: 全链路追踪 ID，格式 ``trace-<uuid4>``
        data: 业务数据载荷，类型由泛型参数 T 决定

    示例::

        envelope = MessageEnvelope[dict](
            channel="market.tick",
            schema_version=1,
            seq=42,
            ts_ns=1700000000000000000,
            trace_id="trace-abc123",
            data={"symbol": "BTC/USDT", "price": 42000.0},
        )
    """

    channel: str = Field(
        ...,
        description="消息通道标识",
        examples=["market.tick", "order.update", "signal.generated"],
    )
    schema_version: int = Field(
        default=1,
        ge=1,
        description="数据结构版本号，从 1 开始",
    )
    seq: int = Field(
        ...,
        ge=0,
        description="序列号，在同一 channel 内单调递增",
    )
    ts_ns: int = Field(
        ...,
        description="纳秒级 Unix 时间戳",
    )
    trace_id: str = Field(
        ...,
        description="全链路追踪 ID",
        pattern=r"^trace-[0-9a-f\-]+$",
    )
    data: T = Field(
        ...,
        description="业务数据载荷",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "channel": "market.tick",
                    "schema_version": 1,
                    "seq": 1,
                    "ts_ns": 1700000000000000000,
                    "trace_id": "trace-550e8400-e29b-41d4-a716-446655440000",
                    "data": {"symbol": "BTC/USDT", "price": 42000.0},
                }
            ]
        }
    }


def _now_ns() -> int:
    """获取当前纳秒级时间戳"""
    return time.time_ns()


def _new_trace_id() -> str:
    """生成新的追踪 ID"""
    return f"trace-{uuid.uuid4()}"


def create_envelope(
    channel: str,
    data: T,
    seq: int,
    schema_version: int = 1,
    trace_id: str | None = None,
    ts_ns: int | None = None,
) -> MessageEnvelope[T]:
    """
    创建消息信封的工厂函数。

    自动生成 trace_id 和 ts_ns（如未提供），简化信封创建流程。

    Args:
        channel: 消息通道标识
        data: 业务数据载荷
        seq: 序列号
        schema_version: 数据结构版本号，默认 1
        trace_id: 追踪 ID，为 None 时自动生成
        ts_ns: 纳秒时间戳，为 None 时使用当前时间

    Returns:
        MessageEnvelope[T]: 封装好的消息信封

    示例::

        envelope = create_envelope(
            channel="market.tick",
            data={"symbol": "BTC/USDT", "price": 42000.0},
            seq=1,
        )
    """
    return MessageEnvelope[T](
        channel=channel,
        schema_version=schema_version,
        seq=seq,
        ts_ns=ts_ns if ts_ns is not None else _now_ns(),
        trace_id=trace_id if trace_id is not None else _new_trace_id(),
        data=data,
    )

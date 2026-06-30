"""
ONE量化 - 消息信封

统一消息格式，所有经过 EventBus 的消息都包装成信封。
信封格式：{channel, schema_version, seq, ts_ns, trace_id, data}
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class MessageEnvelope:
    """消息信封。

    所有进程间通信消息的统一包装。

    Attributes:
        channel: 消息通道名（如 "market.ticker", "strategy.signal"）。
        schema_version: 消息 schema 版本号。
        seq: 单调递增序列号。
        ts_ns: 发布时刻的纳秒级 Unix 时间戳。
        trace_id: 全链路追踪 ID（UUID4）。
        data: 业务数据载荷。
    """

    channel: str
    schema_version: str = "1.0"
    seq: int = 0
    ts_ns: int = field(default_factory=time.time_ns)
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    data: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        """序列化为 JSON 字符串。"""
        return json.dumps(
            {
                "channel": self.channel,
                "schema_version": self.schema_version,
                "seq": self.seq,
                "ts_ns": self.ts_ns,
                "trace_id": self.trace_id,
                "data": self.data,
            },
            default=str,
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, raw: str) -> MessageEnvelope:
        """从 JSON 字符串反序列化。"""
        obj = json.loads(raw)
        return cls(
            channel=obj["channel"],
            schema_version=obj.get("schema_version", "1.0"),
            seq=obj.get("seq", 0),
            ts_ns=int(obj.get("ts_ns", 0)),
            trace_id=str(obj.get("trace_id", "")),
            data=obj.get("data", {}),
        )


def create_envelope(channel: str, data: dict[str, Any], **kwargs: Any) -> MessageEnvelope:
    """创建消息信封的便捷函数。

    Args:
        channel: 消息通道。
        data: 业务数据。
        **kwargs: 其他信封字段。

    Returns:
        消息信封实例。
    """
    return MessageEnvelope(channel=channel, data=data, **kwargs)

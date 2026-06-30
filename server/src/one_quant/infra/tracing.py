"""OpenTelemetry 链路追踪骨架 — trace_id 贯穿全链路"""

from __future__ import annotations

from typing import Any

from one_quant.infra.logging import get_logger

logger = get_logger(__name__)


def setup_tracing(service_name: str = "one-quant", enabled: bool = True) -> None:
    """初始化 OpenTelemetry 链路追踪。

    Args:
        service_name: 服务名称
        enabled: 是否启用追踪
    """
    if not enabled:
        logger.info("OpenTelemetry 追踪已禁用")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

        provider = TracerProvider(resource=None)
        processor = BatchSpanProcessor(ConsoleSpanExporter())
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)
        logger.info("OpenTelemetry 追踪已初始化", service=service_name)
    except ImportError:
        logger.warning("opentelemetry-sdk 未安装，链路追踪不可用")


def get_tracer(name: str) -> Any:
    """获取 tracer 实例"""
    try:
        from opentelemetry import trace
        return trace.get_tracer(name)
    except ImportError:
        return _NoopTracer()


class _NoopTracer:
    """无操作 tracer（未安装 opentelemetry 时使用）"""

    def start_as_current_span(self, name: str, **kwargs: Any) -> Any:
        return _NoopSpan()


class _NoopSpan:
    """无操作 span"""
    def __enter__(self) -> "_NoopSpan":
        return self
    def __exit__(self, *args: object) -> None:
        pass
    def set_attribute(self, key: str, value: Any) -> None:
        pass
    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        pass

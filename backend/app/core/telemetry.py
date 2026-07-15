from contextlib import contextmanager
from typing import Any, Iterator

from app.core.config import settings


def configure_telemetry() -> None:
    if not settings.otel_enabled:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:  # pragma: no cover - deployment dependency validation.
        raise RuntimeError("OpenTelemetry dependencies are not installed") from exc

    provider = TracerProvider(
        resource=Resource.create({"service.name": settings.otel_service_name})
    )
    exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


@contextmanager
def mcp_span(name: str, attributes: dict[str, Any]) -> Iterator[Any | None]:
    if not settings.otel_enabled:
        yield None
        return
    from opentelemetry import trace

    tracer = trace.get_tracer("codemate.mcp")
    with tracer.start_as_current_span(name) as span:
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(key, value)
        yield span


def mark_span_error(span: Any | None, error: Exception | str) -> None:
    if span is None:
        return
    from opentelemetry.trace import Status, StatusCode

    message = str(error)[:1000]
    if isinstance(error, Exception):
        span.record_exception(error)
    span.set_status(Status(StatusCode.ERROR, message))

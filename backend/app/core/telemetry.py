from contextlib import contextmanager
from time import perf_counter
from typing import Any, Iterator

from app.core.config import settings
from app.core.sensitive_data import safe_exception_code


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
    attempt = attributes.get("mcp.attempt")
    retry_count = max(0, int(attempt) - 1) if isinstance(attempt, int) else 0
    with operation_span(
        name,
        component="tool",
        model="none",
        prompt_version="mcp-tool-v1",
        retry_count=retry_count,
        attributes=attributes,
    ) as span:
        yield span


@contextmanager
def operation_span(
    name: str,
    *,
    component: str,
    model: str = "none",
    prompt_version: str = "none",
    retry_count: int = 0,
    attributes: dict[str, Any] | None = None,
) -> Iterator[Any | None]:
    """Record operation metadata without exporting prompt, arguments, or results."""
    if not settings.otel_enabled:
        yield None
        return
    from opentelemetry import trace

    tracer = trace.get_tracer(f"codemate.{component}")
    started = perf_counter()
    with tracer.start_as_current_span(name) as span:
        span.set_attribute("codemate.component", component)
        span.set_attribute("gen_ai.request.model", model or "none")
        span.set_attribute("codemate.prompt.version", prompt_version or "none")
        span.set_attribute("gen_ai.usage.input_tokens", 0)
        span.set_attribute("gen_ai.usage.output_tokens", 0)
        span.set_attribute("gen_ai.usage.total_tokens", 0)
        span.set_attribute("codemate.cost.usd", 0.0)
        span.set_attribute("codemate.retry.count", max(0, retry_count))
        trace_id = span.get_span_context().trace_id
        span.set_attribute("codemate.trace_id", f"{trace_id:032x}")
        for key, value in _safe_attributes(attributes or {}).items():
            span.set_attribute(key, value)
        try:
            yield span
        except Exception as exc:
            mark_span_error(span, exc)
            raise
        finally:
            span.set_attribute("codemate.latency_ms", int((perf_counter() - started) * 1000))


def record_span_usage(
    span: Any | None,
    *,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    total_tokens: int | None = None,
    retry_count: int | None = None,
    cost_usd: float | None = None,
) -> None:
    if span is None:
        return
    safe_input = max(0, int(input_tokens or 0))
    safe_output = max(0, int(output_tokens or 0))
    safe_total = max(0, int(total_tokens if total_tokens is not None else safe_input + safe_output))
    rate = settings.llm_cost_per_million_tokens_usd
    span.set_attribute("gen_ai.usage.input_tokens", safe_input)
    span.set_attribute("gen_ai.usage.output_tokens", safe_output)
    span.set_attribute("gen_ai.usage.total_tokens", safe_total)
    resolved_cost = cost_usd
    if resolved_cost is None:
        resolved_cost = safe_total * rate / 1_000_000 if rate is not None else 0.0
    span.set_attribute("codemate.cost.usd", max(0.0, float(resolved_cost)))
    span.set_attribute("codemate.cost.estimated", cost_usd is None and rate is None)
    if retry_count is not None:
        span.set_attribute("codemate.retry.count", max(0, int(retry_count)))


def _safe_attributes(attributes: dict[str, Any]) -> dict[str, str | int | float | bool]:
    blocked = ("argument", "content", "diff", "payload", "prompt", "query", "result")
    safe: dict[str, str | int | float | bool] = {}
    for key, value in attributes.items():
        normalized_key = str(key).lower()
        if any(marker in normalized_key for marker in blocked):
            continue
        if isinstance(value, bool | int | float):
            safe[str(key)] = value
        elif isinstance(value, str):
            safe[str(key)] = value[:256]
    return safe


def mark_span_error(span: Any | None, error: Exception | str) -> None:
    if span is None:
        return
    from opentelemetry.trace import Status, StatusCode

    error_code = safe_exception_code(error)
    record_exception = getattr(span, "record_exception", None)
    if callable(record_exception):
        record_exception(RuntimeError(error_code))
    span.set_attribute("codemate.error_code", error_code)
    span.set_status(Status(StatusCode.ERROR, error_code))

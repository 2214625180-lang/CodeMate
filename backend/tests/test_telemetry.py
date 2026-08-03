from contextlib import contextmanager
import sys
from types import SimpleNamespace
from types import ModuleType

from app.core.config import settings
from app.core.telemetry import _safe_attributes, operation_span, record_span_usage


class _FakeSpan:
    def __init__(self) -> None:
        self.attributes: dict[str, object] = {}

    def set_attribute(self, key: str, value: object) -> None:
        self.attributes[key] = value

    def get_span_context(self):
        return SimpleNamespace(trace_id=0xABCD)


class _FakeTracer:
    @contextmanager
    def start_as_current_span(self, _name: str):
        yield _FakeSpan()


def test_telemetry_keeps_standard_metrics_and_drops_sensitive_attributes(monkeypatch) -> None:
    monkeypatch.setattr(settings, "otel_enabled", True)
    monkeypatch.setattr(settings, "llm_cost_per_million_tokens_usd", 2.5)
    trace_module = ModuleType("opentelemetry.trace")
    trace_module.get_tracer = lambda _name: _FakeTracer()  # type: ignore[attr-defined]
    opentelemetry_module = ModuleType("opentelemetry")
    opentelemetry_module.trace = trace_module  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "opentelemetry", opentelemetry_module)
    monkeypatch.setitem(sys.modules, "opentelemetry.trace", trace_module)

    with operation_span(
        "gen_ai.plan_next_action",
        component="llm",
        model="gpt-test",
        prompt_version="agent-planner-v1",
        retry_count=2,
        attributes={
            "gen_ai.operation.name": "plan_next_action",
            "tool.arguments": "secret",
            "tool.result": "sensitive output",
            "retrieval.query": "customer email",
        },
    ) as span:
        record_span_usage(span, input_tokens=10, output_tokens=6, total_tokens=16)

    assert span is not None
    assert span.attributes["gen_ai.request.model"] == "gpt-test"
    assert span.attributes["codemate.prompt.version"] == "agent-planner-v1"
    assert span.attributes["gen_ai.usage.total_tokens"] == 16
    assert span.attributes["codemate.cost.usd"] == 0.00004
    assert span.attributes["codemate.retry.count"] == 2
    assert span.attributes["codemate.trace_id"] == f"{0xABCD:032x}"
    assert "tool.arguments" not in span.attributes
    assert "tool.result" not in span.attributes
    assert "retrieval.query" not in span.attributes
    assert "codemate.latency_ms" in span.attributes


def test_safe_telemetry_attributes_only_allows_metadata_scalars() -> None:
    assert _safe_attributes(
        {
            "tool.name": "read_file",
            "sandbox.runtime": "docker",
            "tool.payload": {"secret": "value"},
            "tool.result_count": 3,
        }
    ) == {
        "tool.name": "read_file",
        "sandbox.runtime": "docker",
    }

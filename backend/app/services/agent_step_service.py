import json
from datetime import datetime, timedelta, timezone
from time import perf_counter
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.kms import KMSConfigurationError, decrypt_envelope, encrypt_envelope
from app.core.sensitive_data import redact_timeline_payload, safe_exception_code
from app.core.telemetry import operation_span, record_span_usage
from app.models.agent_step import AgentStep


_TIMELINE_ENVELOPE_PURPOSE = "agent-timeline"


class AgentStepService:
    def __init__(self, db: Session):
        self.db = db

    def record(
        self,
        *,
        run_id: str,
        step_type: str,
        tool_name: str | None = None,
        input_json: Any | None = None,
        output_json: Any | None = None,
        duration_ms: int | None = None,
    ) -> AgentStep:
        safe_input, input_classification = redact_timeline_payload(input_json)
        safe_output, output_classification = redact_timeline_payload(output_json)
        now = datetime.now(timezone.utc)
        step = AgentStep(
            run_id=run_id,
            step_type=step_type,
            tool_name=tool_name,
            input_json=safe_input,
            output_json=safe_output,
            input_classification=input_classification,
            output_classification=output_classification,
            duration_ms=duration_ms,
            created_at=now,
        )
        self.db.add(step)
        self.db.flush()
        step.input_encrypted = self._encrypt_restricted_payload(
            value=input_json,
            classification=input_classification,
            binding=f"{step.run_id}:{step.id}:input",
        )
        step.output_encrypted = self._encrypt_restricted_payload(
            value=output_json,
            classification=output_classification,
            binding=f"{step.run_id}:{step.id}:output",
        )
        if step.input_encrypted or step.output_encrypted:
            step.payload_expires_at = now + timedelta(
                hours=settings.agent_timeline_sensitive_retention_hours
            )
        self.purge_expired_payloads(now=now, commit=False)
        self.db.commit()
        self.db.refresh(step)
        return step

    def purge_expired_payloads(
        self,
        *,
        now: datetime | None = None,
        commit: bool = True,
    ) -> int:
        expired_at = now or datetime.now(timezone.utc)
        result = self.db.execute(
            update(AgentStep)
            .where(AgentStep.payload_expires_at.is_not(None))
            .where(AgentStep.payload_expires_at <= expired_at)
            .values(
                input_encrypted=None,
                output_encrypted=None,
                payload_expires_at=None,
            )
        )
        if commit:
            self.db.commit()
        return int(result.rowcount or 0)

    @staticmethod
    def public_dict(step: AgentStep) -> dict:
        input_json, inferred_input_classification = redact_timeline_payload(step.input_json)
        output_json, inferred_output_classification = redact_timeline_payload(step.output_json)
        return {
            "id": step.id,
            "run_id": step.run_id,
            "step_type": step.step_type,
            "tool_name": step.tool_name,
            "input_json": input_json,
            "output_json": output_json,
            "input_classification": step.input_classification or inferred_input_classification,
            "output_classification": step.output_classification or inferred_output_classification,
            "duration_ms": step.duration_ms,
            "created_at": step.created_at,
        }

    def restricted_dict(self, step: AgentStep) -> dict:
        expires_at = step.payload_expires_at
        expired = expires_at is not None and expires_at <= datetime.now(timezone.utc)
        return {
            "id": step.id,
            "run_id": step.run_id,
            "step_type": step.step_type,
            "tool_name": step.tool_name,
            "input_json": None
            if expired
            else self._decrypt_payload(step.input_encrypted, f"{step.run_id}:{step.id}:input"),
            "output_json": None
            if expired
            else self._decrypt_payload(step.output_encrypted, f"{step.run_id}:{step.id}:output"),
            "input_classification": step.input_classification,
            "output_classification": step.output_classification,
            "payload_expires_at": None if expired else expires_at,
            "created_at": step.created_at,
        }

    def record_tool(self, *, run_id: str, tool_name: str, input_json: dict, fn):
        with operation_span(
            f"codemate.tool.{tool_name}",
            component="tool",
            prompt_version="agent-tool-v1",
            attributes={"tool.name": tool_name, "agent.run_id": run_id},
        ) as span:
            start = perf_counter()
            self.record(
                run_id=run_id,
                step_type="tool_call",
                tool_name=tool_name,
                input_json=input_json,
            )
            try:
                output = fn()
            except Exception as exc:
                duration_ms = int((perf_counter() - start) * 1000)
                self.record(
                    run_id=run_id,
                    step_type="tool_result",
                    tool_name=tool_name,
                    output_json={"ok": False, "error_code": safe_exception_code(exc)},
                    duration_ms=duration_ms,
                )
                record_span_usage(span)
                raise

            duration_ms = int((perf_counter() - start) * 1000)
            self.record(
                run_id=run_id,
                step_type="tool_result",
                tool_name=tool_name,
                output_json=_jsonable(output),
                duration_ms=duration_ms,
            )
            record_span_usage(span)
            return output

    @staticmethod
    def _encrypt_restricted_payload(
        *,
        value: Any | None,
        classification: str,
        binding: str,
    ) -> str | None:
        if value is None or classification != "restricted":
            return None
        try:
            plaintext = json.dumps(value, ensure_ascii=False, default=str).encode()
            return encrypt_envelope(
                plaintext,
                binding=binding,
                purpose=_TIMELINE_ENVELOPE_PURPOSE,
            )
        except KMSConfigurationError:
            # KMS-free local development retains only the redacted summary.
            return None
        except Exception:
            # Never retain a plaintext fallback when KMS is unavailable.
            return None

    @staticmethod
    def _decrypt_payload(value: str | None, binding: str) -> Any | None:
        if value is None:
            return None
        try:
            decoded = json.loads(
                decrypt_envelope(
                    value,
                    binding=binding,
                    purpose=_TIMELINE_ENVELOPE_PURPOSE,
                )
            )
        except Exception:
            return None
        return decoded


def _jsonable(value: Any):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return str(value)

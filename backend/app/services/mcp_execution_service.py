import hashlib
import math
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from time import perf_counter
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.telemetry import mark_span_error, mcp_span
from app.models.agent_run import AgentRun
from app.models.mcp_tool_approval import MCPToolApproval
from app.models.mcp_tool_execution import MCPToolExecution
from app.services.mcp_approval_service import (
    canonical_json,
    jsonable,
    redact_sensitive,
    sha256_json,
)

TERMINAL_EXECUTION_STATUSES = {"succeeded", "failed"}


class MCPExecutionError(RuntimeError):
    pass


class MCPExecutionNotFoundError(MCPExecutionError):
    pass


class MCPExecutionConflictError(MCPExecutionError):
    pass


class MCPExecutionInProgress(MCPExecutionError):
    def __init__(self, execution: MCPToolExecution):
        super().__init__("MCP execution is already in progress")
        self.execution = execution


class MCPExecutionReconciliationRequired(MCPExecutionError):
    def __init__(self, execution: MCPToolExecution, message: str):
        super().__init__(message)
        self.execution = execution


@dataclass(frozen=True)
class MCPExecutionClaim:
    execution: MCPToolExecution
    lease_token: str | None
    cached: bool = False


class MCPExecutionService:
    def __init__(self, db: Session):
        self.db = db

    def prepare(
        self,
        *,
        run_id: str,
        call: dict[str, Any],
        idempotency_key: str,
        idempotency_mode: str,
        approval_id: str | None = None,
        checkpoint: dict[str, Any] | None = None,
    ) -> MCPToolExecution:
        arguments = jsonable(call.get("arguments") or {})
        arguments_hash = sha256_json(arguments)
        existing = self.db.execute(
            select(MCPToolExecution).where(
                MCPToolExecution.idempotency_key == idempotency_key
            )
        ).scalar_one_or_none()
        if existing is not None:
            self._verify_same_request(existing, run_id, call, arguments_hash, approval_id)
            return existing

        checkpoint_json = jsonable(checkpoint) if checkpoint is not None else None
        checkpoint_hash = None
        if checkpoint_json is not None:
            serialized = canonical_json(checkpoint_json)
            if len(serialized) > settings.mcp_execution_max_checkpoint_chars:
                raise MCPExecutionConflictError(
                    "MCP execution checkpoint exceeds the configured size limit"
                )
            checkpoint_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()

        execution = MCPToolExecution(
            run_id=run_id,
            approval_id=approval_id,
            qualified_name=str(call["qualified_name"]),
            server_name=str(call["server"]),
            tool_name=str(call["tool"]),
            arguments_json=arguments,
            arguments_hash=arguments_hash,
            idempotency_key=idempotency_key,
            idempotency_mode=idempotency_mode,
            retry_safe=idempotency_mode == "metadata",
            status="prepared",
            checkpoint_json=checkpoint_json,
            checkpoint_hash=checkpoint_hash,
            version=1,
        )
        self.db.add(execution)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = self.db.execute(
                select(MCPToolExecution).where(
                    MCPToolExecution.idempotency_key == idempotency_key
                )
            ).scalar_one_or_none()
            if existing is None:
                raise
            self._verify_same_request(existing, run_id, call, arguments_hash, approval_id)
            return existing
        self.db.refresh(execution)
        return execution

    def get(self, execution_id: str) -> MCPToolExecution:
        execution = self.db.get(MCPToolExecution, execution_id)
        if execution is None:
            raise MCPExecutionNotFoundError("MCP execution not found")
        return execution

    def list_for_run(self, run_id: str) -> list[MCPToolExecution]:
        return list(
            self.db.execute(
                select(MCPToolExecution)
                .where(MCPToolExecution.run_id == run_id)
                .order_by(MCPToolExecution.created_at.asc())
            )
            .scalars()
            .all()
        )

    def execute_once(
        self,
        execution: MCPToolExecution,
        fn: Callable[[str, str], dict[str, Any]],
    ) -> dict[str, Any]:
        claim = self.claim(execution.id)
        execution = claim.execution
        if claim.cached:
            execution.deduplication_hits += 1
            execution.version += 1
            execution.updated_at = datetime.utcnow()
            self.db.add(execution)
            self.db.commit()
            self.db.refresh(execution)
            return {
                **dict(execution.result_json or {}),
                "execution_id": execution.id,
                "deduplicated": True,
            }
        if claim.lease_token is None:
            raise MCPExecutionConflictError("MCP execution lease was not acquired")

        from app.services.mcp_operations_service import (
            MCPCircuitOpenError,
            MCPOperationsService,
        )

        operations = MCPOperationsService(self.db)
        attributes = {
            "mcp.server": execution.server_name,
            "mcp.tool": execution.tool_name,
            "mcp.qualified_name": execution.qualified_name,
            "mcp.execution_id": execution.id,
            "mcp.run_id": execution.run_id,
            "mcp.approval_id": execution.approval_id,
            "mcp.idempotency_mode": execution.idempotency_mode,
            "mcp.attempt": execution.attempt_count,
        }
        try:
            operations.before_execution(execution.server_name, execution.id)
        except MCPCircuitOpenError as exc:
            with mcp_span("mcp.tools.call", attributes) as span:
                if span is not None:
                    span.set_attribute("mcp.circuit_state", "open")
                mark_span_error(span, exc)
            result = {
                "ok": False,
                "qualified_name": execution.qualified_name,
                "error": "mcp_circuit_open",
                "server_name": execution.server_name,
                "retry_after_seconds": exc.retry_after_seconds,
                "execution_id": execution.id,
                "idempotency_key": execution.idempotency_key,
            }
            execution = self.complete(
                execution.id,
                lease_token=claim.lease_token,
                result=result,
                failed=True,
            )
            return dict(execution.result_json or {})

        try:
            from app.core.queue import enqueue_mcp_execution_watchdog

            enqueue_mcp_execution_watchdog(
                execution.id,
                version=execution.version,
                delay_seconds=effective_execution_lease_seconds() + 1,
            )
        except Exception:  # noqa: BLE001 - durable row still supports manual recovery.
            pass

        started = perf_counter()
        with mcp_span("mcp.tools.call", attributes) as span:
            try:
                raw_result = fn(execution.idempotency_key, execution.id)
            except Exception as exc:
                from app.services.mcp_quota_service import (
                    MCPQuotaExceededError,
                    MCPQuotaUnavailableError,
                )

                if isinstance(exc, (MCPQuotaExceededError, MCPQuotaUnavailableError)):
                    mark_span_error(span, exc)
                    result = {
                        "ok": False,
                        "qualified_name": execution.qualified_name,
                        "error": (
                            "mcp_quota_exceeded"
                            if isinstance(exc, MCPQuotaExceededError)
                            else "mcp_quota_unavailable"
                        ),
                        "reason": getattr(exc, "reason", None),
                        "policy_id": getattr(exc, "policy_id", None),
                        "retry_after_seconds": getattr(
                            exc, "retry_after_seconds", None
                        ),
                        "execution_id": execution.id,
                        "idempotency_key": execution.idempotency_key,
                    }
                    execution = self.complete(
                        execution.id,
                        lease_token=claim.lease_token,
                        result=result,
                        failed=True,
                    )
                    return dict(execution.result_json or {})
                latency_ms = (perf_counter() - started) * 1000
                operations.record_transport_failure(
                    execution.server_name,
                    exc,
                    latency_ms,
                )
                mark_span_error(span, exc)
                execution = self.mark_unknown(
                    execution.id,
                    lease_token=claim.lease_token,
                    reason=f"Remote outcome is unknown: {exc}",
                )
                raise MCPExecutionReconciliationRequired(
                    execution,
                    execution.error_message or str(exc),
                )
            if span is not None:
                span.set_attribute("mcp.tool_ok", bool(raw_result.get("ok")))
            operations.record_transport_success(
                execution.server_name,
                (perf_counter() - started) * 1000,
            )

        result = jsonable(
            {
                **raw_result,
                "execution_id": execution.id,
                "idempotency_key": execution.idempotency_key,
            }
        )
        execution = self.complete(
            execution.id,
            lease_token=claim.lease_token,
            result=result,
            failed=not bool(result.get("ok")),
        )
        return dict(execution.result_json or {})

    def claim(self, execution_id: str) -> MCPExecutionClaim:
        execution = self._locked(execution_id)
        now = datetime.utcnow()
        if execution.status in TERMINAL_EXECUTION_STATUSES:
            return MCPExecutionClaim(execution=execution, lease_token=None, cached=True)
        if execution.status in {"unknown", "reconciling"}:
            raise MCPExecutionReconciliationRequired(
                execution,
                execution.error_message or "MCP execution requires reconciliation",
            )
        if execution.status == "executing":
            if execution.lease_expires_at and now < execution.lease_expires_at:
                raise MCPExecutionInProgress(execution)
            execution = self._recover_expired_locked(execution, now)
            if execution.status != "prepared":
                self.db.commit()
                self.db.refresh(execution)
                raise MCPExecutionReconciliationRequired(
                    execution,
                    execution.error_message or "MCP execution outcome is unknown",
                )
        if execution.status != "prepared":
            raise MCPExecutionConflictError(
                f"MCP execution cannot be claimed from status '{execution.status}'"
            )

        lease_token = uuid.uuid4().hex
        execution.status = "executing"
        execution.lease_token = lease_token
        execution.lease_owner = f"pid:{os.getpid()}"
        execution.lease_expires_at = now + timedelta(
            seconds=effective_execution_lease_seconds()
        )
        execution.attempt_count += 1
        execution.started_at = execution.started_at or now
        execution.version += 1
        execution.updated_at = now
        self.db.add(execution)
        self.db.commit()
        self.db.refresh(execution)
        return MCPExecutionClaim(execution=execution, lease_token=lease_token)

    def complete(
        self,
        execution_id: str,
        *,
        lease_token: str,
        result: dict[str, Any],
        failed: bool,
    ) -> MCPToolExecution:
        execution = self._locked(execution_id)
        if execution.status in TERMINAL_EXECUTION_STATUSES:
            return execution
        if execution.status != "executing" or execution.lease_token != lease_token:
            raise MCPExecutionConflictError("MCP execution lease is no longer valid")
        now = datetime.utcnow()
        execution.status = "failed" if failed else "succeeded"
        execution.result_json = jsonable(result)
        execution.error_message = (
            str(result.get("error") or "MCP tool returned an error")[:4000]
            if failed
            else None
        )
        execution.lease_token = None
        execution.lease_owner = None
        execution.lease_expires_at = None
        execution.finished_at = now
        execution.version += 1
        execution.updated_at = now
        self.db.add(execution)
        self.db.commit()
        self.db.refresh(execution)
        return execution

    def mark_unknown(
        self,
        execution_id: str,
        *,
        lease_token: str,
        reason: str,
    ) -> MCPToolExecution:
        execution = self._locked(execution_id)
        if execution.status in TERMINAL_EXECUTION_STATUSES:
            return execution
        if execution.status != "executing" or execution.lease_token != lease_token:
            raise MCPExecutionConflictError("MCP execution lease is no longer valid")
        self._set_unknown(execution, reason)
        self.db.commit()
        self.db.refresh(execution)
        return execution

    def recover_stale(self, execution_id: str) -> MCPToolExecution | None:
        execution = self._locked(execution_id)
        if execution.status != "executing":
            return None
        now = datetime.utcnow()
        if execution.lease_expires_at and now < execution.lease_expires_at:
            return None
        execution = self._recover_expired_locked(execution, now)
        self.db.commit()
        self.db.refresh(execution)
        if execution.status == "unknown":
            self.mark_run_waiting_reconciliation(execution)
        return execution

    def reconcile(
        self,
        *,
        execution_id: str,
        action: str,
        expected_version: int,
        actor: str,
        provider: str,
        note: str | None,
        result: dict[str, Any] | None,
    ) -> MCPToolExecution:
        if action not in {"confirm_succeeded", "confirm_failed", "retry"}:
            raise MCPExecutionConflictError("Unsupported MCP reconciliation action")
        execution = self._locked(execution_id)
        if execution.version != expected_version:
            raise MCPExecutionConflictError("MCP execution version conflict")
        if execution.status != "unknown":
            raise MCPExecutionConflictError(
                f"MCP execution cannot be reconciled from status '{execution.status}'"
            )
        now = datetime.utcnow()
        if action == "retry":
            if not execution.retry_safe:
                raise MCPExecutionConflictError(
                    "Remote server did not declare metadata idempotency; retry is unsafe"
                )
            if execution.attempt_count >= settings.mcp_execution_max_attempts:
                raise MCPExecutionConflictError("MCP execution retry budget is exhausted")
            execution.status = "prepared"
            execution.result_json = None
            execution.error_message = None
            execution.finished_at = None
        elif action == "confirm_succeeded":
            execution.status = "succeeded"
            execution.result_json = jsonable(
                {
                    **(result or {}),
                    "ok": True,
                    "qualified_name": execution.qualified_name,
                    "execution_id": execution.id,
                    "idempotency_key": execution.idempotency_key,
                    "reconciled": True,
                }
            )
            execution.error_message = None
            execution.finished_at = now
        else:
            execution.status = "failed"
            execution.result_json = jsonable(
                {
                    **(result or {}),
                    "ok": False,
                    "qualified_name": execution.qualified_name,
                    "execution_id": execution.id,
                    "idempotency_key": execution.idempotency_key,
                    "error": (result or {}).get("error")
                    or note
                    or "Execution manually confirmed as failed",
                    "reconciled": True,
                }
            )
            execution.error_message = str(
                (execution.result_json or {}).get("error") or "Execution failed"
            )[:4000]
            execution.finished_at = now
        execution.reconciliation_note = note
        execution.reconciled_by = actor
        execution.reconciled_provider = provider
        execution.reconciled_at = now
        execution.version += 1
        execution.updated_at = now
        self.db.add(execution)
        self.db.commit()
        self.db.refresh(execution)
        return execution

    def mark_run_waiting_reconciliation(self, execution: MCPToolExecution) -> None:
        now = datetime.utcnow()
        run = self.db.get(AgentRun, execution.run_id)
        if run is not None and run.status not in {"success", "failed"}:
            run.status = "waiting_reconciliation"
            run.final_summary = "Agent 正在等待 MCP 执行结果对账。"
            run.failure_reason = None
            run.updated_at = now
            self.db.add(run)
        if execution.approval_id:
            approval = self.db.get(MCPToolApproval, execution.approval_id)
            if approval is not None and approval.status not in {"completed", "failed"}:
                approval.status = "reconciliation_required"
                approval.error_message = execution.error_message
                approval.version += 1
                approval.updated_at = now
                self.db.add(approval)
        self.db.commit()

    def prepare_resume_target(self, execution: MCPToolExecution) -> MCPToolApproval | None:
        if not execution.approval_id:
            return None
        approval = self.db.execute(
            select(MCPToolApproval)
            .where(MCPToolApproval.id == execution.approval_id)
            .with_for_update()
        ).scalar_one_or_none()
        if approval is None:
            return None
        if approval.status in {"reconciliation_required", "resuming", "failed"}:
            approval.status = "queued"
            approval.error_message = None
            approval.execution_started_at = None
            approval.execution_finished_at = None
            approval.version += 1
            approval.updated_at = datetime.utcnow()
            self.db.add(approval)
            self.db.commit()
            self.db.refresh(approval)
        return approval

    @staticmethod
    def verify_checkpoint(execution: MCPToolExecution) -> bool:
        if execution.checkpoint_json is None or execution.checkpoint_hash is None:
            return False
        digest = hashlib.sha256(
            canonical_json(execution.checkpoint_json).encode("utf-8")
        ).hexdigest()
        return digest == execution.checkpoint_hash

    @staticmethod
    def public_dict(execution: MCPToolExecution) -> dict[str, Any]:
        return {
            "id": execution.id,
            "run_id": execution.run_id,
            "approval_id": execution.approval_id,
            "qualified_name": execution.qualified_name,
            "server_name": execution.server_name,
            "tool_name": execution.tool_name,
            "arguments": redact_sensitive(execution.arguments_json),
            "arguments_hash": execution.arguments_hash,
            "idempotency_key": execution.idempotency_key,
            "idempotency_mode": execution.idempotency_mode,
            "status": execution.status,
            "attempt_count": execution.attempt_count,
            "recovery_count": execution.recovery_count,
            "deduplication_hits": execution.deduplication_hits,
            "retry_safe": execution.retry_safe,
            "lease_owner": execution.lease_owner,
            "lease_expires_at": (
                execution.lease_expires_at.isoformat() if execution.lease_expires_at else None
            ),
            "result": redact_sensitive(execution.result_json),
            "error_message": execution.error_message,
            "reconciliation_note": execution.reconciliation_note,
            "reconciled_by": execution.reconciled_by,
            "reconciled_provider": execution.reconciled_provider,
            "version": execution.version,
            "created_at": execution.created_at.isoformat(),
            "started_at": execution.started_at.isoformat() if execution.started_at else None,
            "finished_at": execution.finished_at.isoformat() if execution.finished_at else None,
            "reconciled_at": (
                execution.reconciled_at.isoformat() if execution.reconciled_at else None
            ),
            "updated_at": execution.updated_at.isoformat(),
        }

    def _locked(self, execution_id: str) -> MCPToolExecution:
        execution = self.db.execute(
            select(MCPToolExecution)
            .where(MCPToolExecution.id == execution_id)
            .with_for_update()
        ).scalar_one_or_none()
        if execution is None:
            raise MCPExecutionNotFoundError("MCP execution not found")
        return execution

    def _recover_expired_locked(
        self,
        execution: MCPToolExecution,
        now: datetime,
    ) -> MCPToolExecution:
        execution.recovery_count += 1
        execution.lease_token = None
        execution.lease_owner = None
        execution.lease_expires_at = None
        execution.version += 1
        execution.updated_at = now
        if execution.retry_safe and execution.attempt_count < settings.mcp_execution_max_attempts:
            execution.status = "prepared"
            execution.error_message = "Previous worker lease expired; retry scheduled with same key"
        else:
            self._set_unknown(
                execution,
                "Worker lease expired after remote call may have started; reconciliation required",
                increment_version=False,
            )
        self.db.add(execution)
        return execution

    def _set_unknown(
        self,
        execution: MCPToolExecution,
        reason: str,
        *,
        increment_version: bool = True,
    ) -> None:
        now = datetime.utcnow()
        execution.status = "unknown"
        execution.error_message = reason[:4000]
        execution.lease_token = None
        execution.lease_owner = None
        execution.lease_expires_at = None
        execution.finished_at = None
        if increment_version:
            execution.version += 1
        execution.updated_at = now
        self.db.add(execution)

    @staticmethod
    def _verify_same_request(
        execution: MCPToolExecution,
        run_id: str,
        call: dict[str, Any],
        arguments_hash: str,
        approval_id: str | None,
    ) -> None:
        if (
            execution.run_id != run_id
            or execution.approval_id != approval_id
            or execution.qualified_name != str(call.get("qualified_name"))
            or execution.arguments_hash != arguments_hash
        ):
            raise MCPExecutionConflictError(
                "Idempotency key is already bound to a different MCP request"
            )


def execution_idempotency_key(*parts: Any) -> str:
    return hashlib.sha256(canonical_json(list(parts)).encode("utf-8")).hexdigest()


def effective_execution_lease_seconds() -> int:
    return max(
        1,
        settings.mcp_execution_lease_seconds,
        math.ceil(settings.mcp_client_timeout_seconds) + 5,
    )

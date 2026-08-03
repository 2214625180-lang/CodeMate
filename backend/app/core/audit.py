import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable
from uuid import uuid4

from fastapi import Request, Response

from app.core.config import settings

audit_logger = logging.getLogger("codemate.audit")


async def evaluation_audit_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    if not is_security_audit_path(request.url.path):
        return await call_next(request)

    if settings.security_audit_fail_closed and settings.security_audit_sink_set:
        request.state.security_audit_intent_id = write_backend_security_audit_intent(request)

    started = time.perf_counter()
    status_code = 500
    reason: str | None = None
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    except Exception:
        reason = "unhandled_exception"
        raise
    finally:
        duration_ms = (time.perf_counter() - started) * 1000
        write_backend_evaluation_audit_event(
            request,
            status_code=status_code,
            duration_ms=duration_ms,
            reason=reason,
        )


def write_backend_evaluation_audit_event(
    request: Request,
    *,
    status_code: int,
    duration_ms: float,
    reason: str | None = None,
) -> None:
    record = backend_evaluation_audit_record(
        request,
        status_code=status_code,
        duration_ms=duration_ms,
        reason=reason,
    )
    emit_security_audit_record(record)


def write_backend_security_audit_intent(request: Request) -> str:
    event_id = str(uuid4())
    emit_security_audit_record(
        {
            "id": event_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "eventType": "backend_security_request_intent",
            "outcome": "pending",
            "actor": {"provider": "unresolved", "login": "unresolved", "role": None},
            "method": request.method,
            "path": request.url.path,
            "status": None,
            "reason": None,
            "ip": client_ip(request),
            "userAgent": truncate_header(request.headers.get("user-agent")),
            "metadata": {"phase": "before_handler"},
        }
    )
    return event_id


def emit_security_audit_record(record: dict[str, Any]) -> None:
    serialized = json.dumps(record, separators=(",", ":"), sort_keys=True)
    audit_logger.info(serialized)
    append_security_audit_record(serialized)
    enqueue_remote_security_audit_record(record)


def backend_evaluation_audit_record(
    request: Request,
    *,
    status_code: int,
    duration_ms: float,
    reason: str | None = None,
) -> dict[str, Any]:
    principal = getattr(request.state, "product_principal", None) or getattr(
        request.state, "evaluation_principal", None
    )
    auth_method = getattr(principal, "auth_method", None)
    token_kind = getattr(principal, "token_kind", None)
    return {
        "id": str(uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "eventType": backend_request_event_type(request.url.path),
        "outcome": audit_outcome(status_code),
        "actor": {
            "provider": getattr(principal, "provider", "unknown"),
            "login": getattr(principal, "login", "anonymous"),
            "role": getattr(principal, "role", None),
        },
        "method": request.method,
        "path": request.url.path,
        "status": status_code,
        "reason": reason or audit_reason(status_code),
        "ip": client_ip(request),
        "userAgent": truncate_header(request.headers.get("user-agent")),
        "metadata": {
            "authMethod": auth_method,
            "tokenKind": token_kind,
            "durationMs": round(duration_ms, 2),
            "intentId": getattr(request.state, "security_audit_intent_id", None),
        },
    }


def append_security_audit_record(serialized_record: str) -> None:
    audit_path = settings.security_audit_log_path
    if not audit_path:
        return

    try:
        path = Path(audit_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as audit_file:
            audit_file.write(f"{serialized_record}\n")
    except OSError:
        audit_logger.exception("Failed to write backend security audit event")


def enqueue_remote_security_audit_record(record: dict[str, Any]) -> None:
    if not settings.security_audit_sink_set:
        return
    try:
        from app.services.security_audit_delivery_service import (
            enqueue_security_audit_record,
        )

        enqueue_security_audit_record(record)
    except Exception:  # noqa: BLE001 - local append remains the emergency fallback.
        audit_logger.exception("Failed to enqueue security audit event for remote delivery")
        if settings.security_audit_fail_closed:
            raise


def is_evaluation_path(path: str) -> bool:
    return path == "/evaluations" or path.startswith("/evaluations/")


def is_mcp_approval_path(path: str) -> bool:
    return path == "/mcp-approvals" or path.startswith("/mcp-approvals/")


def is_mcp_execution_path(path: str) -> bool:
    return path == "/mcp-executions" or path.startswith("/mcp-executions/")


def is_mcp_operations_path(path: str) -> bool:
    return path == "/mcp-operations" or path.startswith("/mcp-operations/")


def is_mcp_registry_path(path: str) -> bool:
    return path == "/mcp-registry" or path.startswith("/mcp-registry/")


def is_mcp_tenancy_path(path: str) -> bool:
    return path == "/mcp-tenancy" or path.startswith("/mcp-tenancy/")


def is_mcp_quota_path(path: str) -> bool:
    return path == "/mcp-quotas" or path.startswith("/mcp-quotas/")


def is_product_path(path: str) -> bool:
    return path == "/repos" or path.startswith("/repos/") or path.startswith("/runs/")


def is_security_audit_path(path: str) -> bool:
    return (
        is_product_path(path)
        or is_evaluation_path(path)
        or is_mcp_approval_path(path)
        or is_mcp_execution_path(path)
        or is_mcp_operations_path(path)
        or is_mcp_registry_path(path)
        or is_mcp_tenancy_path(path)
        or is_mcp_quota_path(path)
    )


def backend_request_event_type(path: str) -> str:
    if is_product_path(path):
        return "backend_product_request"
    if is_mcp_quota_path(path):
        return "backend_mcp_quota_request"
    if is_mcp_tenancy_path(path):
        return "backend_mcp_tenancy_request"
    if is_mcp_registry_path(path):
        return "backend_mcp_registry_request"
    if is_mcp_operations_path(path):
        return "backend_mcp_operations_request"
    if is_mcp_execution_path(path):
        return "backend_mcp_execution_request"
    if is_mcp_approval_path(path):
        return "backend_mcp_approval_request"
    return "backend_evaluation_request"


def audit_outcome(status_code: int) -> str:
    if status_code < 400:
        return "success"
    if status_code in {401, 403}:
        return "blocked"
    return "failure"


def audit_reason(status_code: int) -> str | None:
    if status_code < 400:
        return None
    if status_code == 401:
        return "unauthorized"
    if status_code == 403:
        return "forbidden"
    if status_code >= 500:
        return "server_error"
    return "request_failed"


def client_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return truncate_header(forwarded_for.split(",")[0].strip())
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return truncate_header(real_ip)
    if request.client:
        return request.client.host
    return None


def truncate_header(value: str | None, limit: int = 512) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[:limit]

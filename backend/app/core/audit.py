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
    if not is_evaluation_path(request.url.path):
        return await call_next(request)

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
    serialized = json.dumps(record, separators=(",", ":"), sort_keys=True)
    audit_logger.info(serialized)
    append_security_audit_record(serialized)


def backend_evaluation_audit_record(
    request: Request,
    *,
    status_code: int,
    duration_ms: float,
    reason: str | None = None,
) -> dict[str, Any]:
    principal = getattr(request.state, "evaluation_principal", None)
    auth_method = getattr(principal, "auth_method", None)
    token_kind = getattr(principal, "token_kind", None)
    return {
        "id": str(uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "eventType": "backend_evaluation_request",
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


def is_evaluation_path(path: str) -> bool:
    return path == "/evaluations" or path.startswith("/evaluations/")


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

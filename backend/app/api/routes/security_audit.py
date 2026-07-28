import hmac
from typing import Any

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field

from app.core.audit import emit_security_audit_record
from app.core.config import settings

router = APIRouter(prefix="/security-audit", tags=["security-audit"])


class SecurityAuditIngestRequest(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    timestamp: str = Field(min_length=1, max_length=64)
    eventType: str = Field(min_length=1, max_length=128)
    outcome: str = Field(min_length=1, max_length=32)
    actor: dict[str, Any] | None = None
    method: str | None = None
    path: str | None = None
    status: int | None = None
    reason: str | None = None
    ip: str | None = None
    userAgent: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.post("/events", status_code=status.HTTP_202_ACCEPTED)
def ingest_security_audit_event(
    payload: SecurityAuditIngestRequest,
    authorization: str | None = Header(default=None),
):
    expected = (settings.security_audit_ingest_token or "").strip()
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not expected or not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid audit ingest token")
    record = payload.model_dump(mode="json")
    record["metadata"] = {**record["metadata"], "source": "codemate-frontend"}
    emit_security_audit_record(record)
    return {"accepted": True, "event_id": payload.id}

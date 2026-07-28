from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.api.auth import EvaluationPrincipal, require_evaluation_admin
from app.core.database import get_db
from app.core.config import settings
from app.core.queue import enqueue_mcp_compliance_scan, enqueue_mcp_health_probe
from app.mcp.client import MCPClientService
from app.schemas.mcp_operations import MCPCircuitControlRequest, MCPProbeResponse
from app.services.mcp_operations_service import (
    MCPCircuitConflictError,
    MCPOperationsService,
    MCPServerNotFoundError,
)
from app.services.security_audit_delivery_service import SecurityAuditDeliveryService
from app.services.mcp_compliance_service import latest_compliance_report

router = APIRouter(prefix="/mcp-operations", tags=["mcp-operations"])
AdminPrincipal = Annotated[EvaluationPrincipal, Depends(require_evaluation_admin)]


@router.get("/overview")
def operations_overview(
    _principal: AdminPrincipal,
    window_minutes: int | None = Query(default=None, ge=1, le=24 * 60),
    db: Session = Depends(get_db),
):
    service = initialized_service(db)
    return service.snapshot(window_minutes=window_minutes)


@router.get("/servers")
def list_server_health(
    _principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    service = initialized_service(db)
    return [service.public_server(item) for item in service.list_servers()]


@router.get("/metrics/prometheus", response_class=PlainTextResponse)
def prometheus_metrics(
    _principal: AdminPrincipal,
    window_minutes: int | None = Query(default=None, ge=1, le=24 * 60),
    db: Session = Depends(get_db),
):
    return PlainTextResponse(
        initialized_service(db).prometheus(window_minutes=window_minutes),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@router.post("/probes", response_model=MCPProbeResponse)
def probe_all_servers(
    _principal: AdminPrincipal,
):
    try:
        job_id = enqueue_mcp_health_probe()
    except Exception as exc:  # noqa: BLE001 - expose queue availability.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Health probe could not be queued: {exc}",
        ) from exc
    return MCPProbeResponse(server_name=None, job_id=job_id)


@router.get("/security-audit")
def security_audit_delivery_status(
    _principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    return SecurityAuditDeliveryService(db).status()


@router.post("/security-audit/deliver")
def deliver_security_audit_now(
    _principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    return SecurityAuditDeliveryService(db).deliver_batch()


@router.post("/security-audit/requeue-dead-letters")
def requeue_security_audit_dead_letters(
    _principal: AdminPrincipal,
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    return {"requeued": SecurityAuditDeliveryService(db).requeue_dead_letters(limit)}


@router.get("/compliance/latest")
def latest_mcp_compliance(_principal: AdminPrincipal):
    report = latest_compliance_report()
    if report is None:
        return {"schema_version": 1, "status": "missing", "controls": []}
    return report


@router.post("/compliance/scan")
def scan_mcp_compliance(_principal: AdminPrincipal):
    try:
        return {"job_id": enqueue_mcp_compliance_scan()}
    except Exception as exc:  # noqa: BLE001 - expose queue availability.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Compliance scan could not be queued: {exc}",
        ) from exc


@router.post("/servers/{server_name}/probe", response_model=MCPProbeResponse)
def probe_server(
    server_name: str,
    _principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    service = initialized_service(db)
    try:
        service.get_server(server_name)
    except MCPServerNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    try:
        job_id = enqueue_mcp_health_probe(server_name=server_name)
    except Exception as exc:  # noqa: BLE001 - expose queue availability.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Health probe could not be queued: {exc}",
        ) from exc
    return MCPProbeResponse(server_name=server_name, job_id=job_id)


@router.post("/servers/{server_name}/circuit")
def control_server_circuit(
    server_name: str,
    payload: MCPCircuitControlRequest,
    _principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    service = initialized_service(db)
    try:
        health = service.control_circuit(
            server_name,
            action=payload.action,
            expected_version=payload.expected_version,
        )
    except MCPServerNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except MCPCircuitConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return service.public_server(health)


def initialized_service(db: Session) -> MCPOperationsService:
    service = MCPOperationsService(db)
    try:
        if settings.mcp_registry_enabled:
            from app.services.mcp_registry_service import MCPRegistryService

            client = MCPRegistryService(db).client()
        else:
            client = MCPClientService()
        service.register_servers(client.configured_servers())
    except Exception:  # noqa: BLE001 - persisted operations data remains readable.
        pass
    return service

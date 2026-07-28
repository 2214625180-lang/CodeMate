from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.api.auth import EvaluationPrincipal, require_evaluation_admin
from app.core.database import get_db
from app.models.mcp_tenant import MCPTenant
from app.models.mcp_quota import MCPQuotaPolicy
from app.models.repository import Repository
from app.schemas.mcp_quotas import (
    MCPQuotaPolicyCreate,
    MCPQuotaPolicyUpdate,
    MCPQuotaResetRequest,
    MCPQuotaTemporaryAdjustment,
    MCPQuotaReconcileRequest,
    MCPQuotaRetentionRequest,
)
from app.services.mcp_quota_service import (
    MCPQuotaConflictError,
    MCPQuotaNotFoundError,
    MCPQuotaService,
    MCPQuotaUnavailableError,
    policy_public,
)

router = APIRouter(prefix="/mcp-quotas", tags=["mcp-quotas"])
AdminPrincipal = Annotated[EvaluationPrincipal, Depends(require_evaluation_admin)]


@router.get("/tenants/{tenant_id}/policies")
def list_quota_policies(
    tenant_id: str,
    _principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    require_tenant(db, tenant_id)
    return [policy_public(item) for item in MCPQuotaService(db).list_policies(tenant_id)]


@router.post(
    "/tenants/{tenant_id}/policies",
    status_code=status.HTTP_201_CREATED,
)
def create_quota_policy(
    tenant_id: str,
    payload: MCPQuotaPolicyCreate,
    principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    require_tenant(db, tenant_id)
    validate_repository(db, tenant_id, payload.repo_id)
    try:
        policy = MCPQuotaService(db).create_policy(
            tenant_id,
            payload.model_dump(),
            actor=principal.login,
        )
        return policy_public(policy)
    except MCPQuotaConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.patch("/policies/{policy_id}")
def update_quota_policy(
    policy_id: str,
    payload: MCPQuotaPolicyUpdate,
    principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    changes = payload.model_dump(exclude_unset=True)
    expected_version = changes.pop("expected_version")
    existing = db.get(MCPQuotaPolicy, policy_id)
    if existing and "repo_id" in changes:
        validate_repository(db, existing.tenant_id, changes["repo_id"])
    try:
        return policy_public(
            MCPQuotaService(db).update_policy(
                policy_id,
                changes,
                expected_version=expected_version,
                actor=principal.login,
            )
        )
    except MCPQuotaNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MCPQuotaConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/policies/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
def disable_quota_policy(
    policy_id: str,
    principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    try:
        MCPQuotaService(db).disable_policy(policy_id, actor=principal.login)
    except MCPQuotaNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MCPQuotaUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/policies/{policy_id}/reset")
def reset_quota_policy(
    policy_id: str,
    payload: MCPQuotaResetRequest,
    principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    try:
        return policy_public(
            MCPQuotaService(db).reset_policy(
                policy_id,
                expected_version=payload.expected_version,
                actor=principal.login,
            )
        )
    except MCPQuotaNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MCPQuotaConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except MCPQuotaUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/policies/{policy_id}/temporary-adjustment")
def temporarily_adjust_quota_policy(
    policy_id: str,
    payload: MCPQuotaTemporaryAdjustment,
    principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    overrides = payload.model_dump(
        exclude={"expected_version", "duration_seconds"}, exclude_none=True
    )
    try:
        return policy_public(
            MCPQuotaService(db).temporarily_adjust_policy(
                policy_id,
                overrides=overrides,
                duration_seconds=payload.duration_seconds,
                expected_version=payload.expected_version,
                actor=principal.login,
            )
        )
    except MCPQuotaNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MCPQuotaConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except MCPQuotaUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/tenants/{tenant_id}/overview")
def quota_overview(
    tenant_id: str,
    _principal: AdminPrincipal,
    window_days: int = Query(default=1, ge=1, le=90),
    db: Session = Depends(get_db),
):
    require_tenant(db, tenant_id)
    return MCPQuotaService(db).overview(tenant_id, window_days=window_days)


@router.get(
    "/tenants/{tenant_id}/metrics/prometheus",
    response_class=PlainTextResponse,
)
def quota_prometheus(
    tenant_id: str,
    _principal: AdminPrincipal,
    window_days: int = Query(default=1, ge=1, le=90),
    db: Session = Depends(get_db),
):
    require_tenant(db, tenant_id)
    return PlainTextResponse(
        MCPQuotaService(db).prometheus(tenant_id, window_days=window_days),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@router.post("/tenants/{tenant_id}/reconcile")
def reconcile_quota_usage(
    tenant_id: str,
    payload: MCPQuotaReconcileRequest,
    _principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    require_tenant(db, tenant_id)
    try:
        return MCPQuotaService(db).reconcile_redis(tenant_id, repair=payload.repair)
    except MCPQuotaConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except MCPQuotaUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/tenants/{tenant_id}/reconciliations")
def list_quota_reconciliations(
    tenant_id: str,
    _principal: AdminPrincipal,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    require_tenant(db, tenant_id)
    return MCPQuotaService(db).recent_reconciliations(tenant_id, limit=limit)


@router.post("/tenants/{tenant_id}/retention")
def apply_quota_retention(
    tenant_id: str,
    payload: MCPQuotaRetentionRequest,
    _principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    require_tenant(db, tenant_id)
    return MCPQuotaService(db).purge_usage(
        tenant_id,
        retention_days=payload.retention_days,
        dry_run=payload.dry_run,
    )


def require_tenant(db: Session, tenant_id: str) -> MCPTenant:
    tenant = db.get(MCPTenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


def validate_repository(db: Session, tenant_id: str, repo_id: str | None) -> None:
    if not repo_id:
        return
    repository = db.get(Repository, repo_id)
    if repository is None or repository.tenant_id != tenant_id:
        raise HTTPException(status_code=400, detail="Repository does not belong to tenant")

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.auth import EvaluationPrincipal, require_evaluation_admin
from app.core.config import settings
from app.core.database import get_db
from app.core.queue import enqueue_agent_approval_resume
from app.models.agent_run import AgentRun
from app.schemas.mcp_approvals import (
    MCPApprovalDecisionRequest,
    MCPApprovalRead,
    MCPApprovalResumeResponse,
)
from app.services.agent_step_service import AgentStepService
from app.services.mcp_approval_service import (
    MCPApprovalConflictError,
    MCPApprovalNotFoundError,
    MCPApprovalService,
)
from app.services.mcp_tenancy_service import (
    MCPAuthorizationContext,
    MCPAuthorizationDenied,
    MCPTenancyService,
)

router = APIRouter(prefix="/mcp-approvals", tags=["mcp-approvals"])
AdminPrincipal = Annotated[EvaluationPrincipal, Depends(require_evaluation_admin)]


@router.get("/runs/{run_id}", response_model=list[MCPApprovalRead])
def list_run_approvals(
    run_id: str,
    _principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    if db.get(AgentRun, run_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    service = MCPApprovalService(db)
    return [service.public_dict(approval) for approval in service.list_for_run(run_id)]


@router.get("/{approval_id}", response_model=MCPApprovalRead)
def get_approval(
    approval_id: str,
    _principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    service = MCPApprovalService(db)
    try:
        return service.public_dict(service.get(approval_id))
    except MCPApprovalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{approval_id}/decision", response_model=MCPApprovalRead)
def decide_approval(
    approval_id: str,
    payload: MCPApprovalDecisionRequest,
    principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    service = MCPApprovalService(db)
    try:
        before = service.get(approval_id)
        if settings.mcp_tenant_authorization_enabled:
            run = db.get(AgentRun, before.run_id)
            if run is None or run.tenant_id is None:
                raise MCPAuthorizationDenied("Approval run has no tenant")
            MCPTenancyService(db).require(
                MCPAuthorizationContext(
                    tenant_id=run.tenant_id,
                    repo_id=run.repo_id,
                    principal_type="user",
                    principal_id=principal.login,
                    principal_provider=principal.provider,
                ),
                server_name=before.server_name,
                tool_name=before.tool_name,
                permission="approve",
            )
        is_new_decision = before.status == "pending" and before.version == payload.expected_version
        approval = service.decide(
            approval_id=approval_id,
            decision=payload.decision,
            note=payload.note,
            actor=principal.login,
            provider=principal.provider,
            expected_version=payload.expected_version,
        )
    except MCPApprovalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except MCPApprovalConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except MCPAuthorizationDenied as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    public_approval = service.public_dict(approval)
    if is_new_decision:
        AgentStepService(db).record(
            run_id=approval.run_id,
            step_type="approval_decision",
            tool_name=approval.qualified_name,
            input_json={
                "approval_id": approval.id,
                "decision": approval.decision,
                "version": approval.version,
            },
            output_json={"approval": public_approval},
        )
    if approval.status == "queued":
        try:
            enqueue_agent_approval_resume(approval.id, version=approval.version)
        except Exception as exc:  # noqa: BLE001 - decision remains durable and retryable.
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Approval saved but resume job could not be queued: {exc}",
            ) from exc
    return public_approval


@router.post("/{approval_id}/resume", response_model=MCPApprovalResumeResponse)
def retry_approval_resume(
    approval_id: str,
    _principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    service = MCPApprovalService(db)
    try:
        approval = service.get(approval_id)
    except MCPApprovalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if approval.status == "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Approval has not been decided",
        )
    if approval.status in {"completed", "failed"}:
        return MCPApprovalResumeResponse(
            approval_id=approval.id,
            status=approval.status,
            job_id=None,
        )
    try:
        job_id = enqueue_agent_approval_resume(approval.id, version=approval.version)
    except Exception as exc:  # noqa: BLE001 - surface queue availability consistently.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Resume job could not be queued: {exc}",
        ) from exc
    return MCPApprovalResumeResponse(
        approval_id=approval.id,
        status=approval.status,
        job_id=job_id,
    )

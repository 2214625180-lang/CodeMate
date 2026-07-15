from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.auth import EvaluationPrincipal, require_evaluation_admin
from app.core.database import get_db
from app.core.queue import (
    enqueue_agent_approval_resume,
    enqueue_agent_execution_resume,
)
from app.models.agent_run import AgentRun
from app.schemas.mcp_executions import (
    MCPExecutionRead,
    MCPExecutionReconcileRequest,
    MCPExecutionReconcileResponse,
    MCPExecutionResumeResponse,
)
from app.services.agent_step_service import AgentStepService
from app.services.mcp_execution_service import (
    MCPExecutionConflictError,
    MCPExecutionNotFoundError,
    MCPExecutionService,
)

router = APIRouter(prefix="/mcp-executions", tags=["mcp-executions"])
AdminPrincipal = Annotated[EvaluationPrincipal, Depends(require_evaluation_admin)]


@router.get("/runs/{run_id}", response_model=list[MCPExecutionRead])
def list_run_executions(
    run_id: str,
    _principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    if db.get(AgentRun, run_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    service = MCPExecutionService(db)
    return [service.public_dict(item) for item in service.list_for_run(run_id)]


@router.get("/{execution_id}", response_model=MCPExecutionRead)
def get_execution(
    execution_id: str,
    _principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    service = MCPExecutionService(db)
    try:
        return service.public_dict(service.get(execution_id))
    except MCPExecutionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{execution_id}/reconcile", response_model=MCPExecutionReconcileResponse)
def reconcile_execution(
    execution_id: str,
    payload: MCPExecutionReconcileRequest,
    principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    service = MCPExecutionService(db)
    try:
        execution = service.reconcile(
            execution_id=execution_id,
            action=payload.action,
            expected_version=payload.expected_version,
            actor=principal.login,
            provider=principal.provider,
            note=payload.note,
            result=payload.result,
        )
    except MCPExecutionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except MCPExecutionConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    public_execution = service.public_dict(execution)
    AgentStepService(db).record(
        run_id=execution.run_id,
        step_type="mcp_execution",
        tool_name=execution.qualified_name,
        input_json={
            "event": "reconciled",
            "action": payload.action,
            "execution_id": execution.id,
        },
        output_json={"execution": public_execution},
    )
    try:
        approval = service.prepare_resume_target(execution)
        if approval is not None:
            job_id = enqueue_agent_approval_resume(approval.id, version=approval.version)
        else:
            job_id = enqueue_agent_execution_resume(execution.id, version=execution.version)
    except Exception as exc:  # noqa: BLE001 - reconciliation is durable and retryable.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Reconciliation saved but resume job could not be queued: {exc}",
        ) from exc
    return {"execution": public_execution, "job_id": job_id}


@router.post("/{execution_id}/resume", response_model=MCPExecutionResumeResponse)
def retry_execution_resume(
    execution_id: str,
    _principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    service = MCPExecutionService(db)
    try:
        execution = service.get(execution_id)
    except MCPExecutionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if execution.status in {"unknown", "reconciling"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Execution must be reconciled before the Agent can resume",
        )
    if execution.status == "executing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Execution is still in progress",
        )
    try:
        approval = service.prepare_resume_target(execution)
        if approval is not None:
            job_id = enqueue_agent_approval_resume(approval.id, version=approval.version)
        else:
            job_id = enqueue_agent_execution_resume(execution.id, version=execution.version)
    except Exception as exc:  # noqa: BLE001 - durable execution can be resumed later.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Resume job could not be queued: {exc}",
        ) from exc
    return {
        "execution_id": execution.id,
        "status": execution.status,
        "job_id": job_id,
    }

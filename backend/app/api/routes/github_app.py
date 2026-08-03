from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from redis.exceptions import RedisError
from sqlalchemy.orm import Session

from app.api.auth import ProductPrincipal, get_product_principal
from app.core.database import get_db
from app.core.queue import enqueue_agent_run
from app.github_app import GitHubAppError
from app.schemas.github_app import (
    GitHubAppFailedCIRequest,
    GitHubAppRepairDecisionRequest,
    GitHubAppRepairRead,
)
from app.services.github_app_repair_service import (
    GitHubAppRepairConflictError,
    GitHubAppRepairService,
)
from app.services.repo_service import RepoService


router = APIRouter(prefix="/github-app", tags=["github-app"])
ProductUser = Annotated[ProductPrincipal, Depends(get_product_principal)]


@router.post("/repairs", response_model=GitHubAppRepairRead, status_code=status.HTTP_202_ACCEPTED)
def start_failed_ci_repair(
    payload: GitHubAppFailedCIRequest,
    principal: ProductUser,
    db: Session = Depends(get_db),
):
    repository = RepoService(db).get_for_owner(payload.repo_id, principal.owner_id)
    if repository is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found")
    service = GitHubAppRepairService(db)
    try:
        repair = service.start_failed_ci_repair(
            repository=repository,
            installation_id=payload.installation_id,
            workflow_run_id=payload.workflow_run_id,
        )
    except GitHubAppRepairConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except GitHubAppError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if repair.status == "fixing":
        try:
            enqueue_agent_run(repair.run_id)
        except RedisError:
            service.mark_enqueue_failed(repair, "Failed to enqueue GitHub App repair run")
            db.refresh(repair)
    return repair


@router.get("/repairs/{repair_id}", response_model=GitHubAppRepairRead)
def get_repair(
    repair_id: str,
    principal: ProductUser,
    db: Session = Depends(get_db),
):
    repair = GitHubAppRepairService(db).get_for_owner(repair_id, principal.owner_id)
    if repair is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="GitHub App repair not found")
    return repair


@router.post("/repairs/{repair_id}/decision", response_model=GitHubAppRepairRead)
def decide_draft_pr(
    repair_id: str,
    payload: GitHubAppRepairDecisionRequest,
    principal: ProductUser,
    db: Session = Depends(get_db),
):
    service = GitHubAppRepairService(db)
    repair = service.get_for_owner(repair_id, principal.owner_id)
    if repair is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="GitHub App repair not found")
    try:
        return service.decide_draft_pr(
            repair=repair,
            approver=principal.owner_id,
            approved=payload.approved,
            note=payload.note,
        )
    except GitHubAppRepairConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

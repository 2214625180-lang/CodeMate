import json
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.agent.verification import TERMINAL_AGENT_RUN_STATUSES
from app.api.auth import (
    EvaluationPrincipal,
    ProductPrincipal,
    get_product_principal,
    require_evaluation_admin,
)
from app.core.database import SessionLocal, get_db
from app.models.agent_run import AgentRun
from app.models.agent_step import AgentStep
from app.schemas.runs import (
    AgentRunRead,
    AgentStepRead,
    AgentStepRestrictedRead,
    RunFeedbackRequest,
    RunFeedbackResponse,
)
from app.services.agent_step_service import AgentStepService

router = APIRouter(prefix="/runs", tags=["runs"])
ProductUser = Annotated[ProductPrincipal, Depends(get_product_principal)]
AdminPrincipal = Annotated[EvaluationPrincipal, Depends(require_evaluation_admin)]


def get_owned_run(
    db: Session,
    run_id: str,
    owner_id: str,
    *,
    include_steps: bool = False,
) -> AgentRun:
    statement = select(AgentRun).where(AgentRun.id == run_id).where(AgentRun.owner_id == owner_id)
    if include_steps:
        statement = statement.options(selectinload(AgentRun.steps))
    run = db.execute(statement).scalar_one_or_none()
    if run is None:
        # Match the repository boundary: no cross-user identifier oracle.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return run


@router.get("/{run_id}", response_model=AgentRunRead)
def get_run(run_id: str, principal: ProductUser, db: Session = Depends(get_db)):
    run = get_owned_run(db, run_id, principal.owner_id, include_steps=True)
    response = AgentRunRead.model_validate(run)
    steps = AgentStepService(db)
    response.steps = [
        AgentStepRead.model_validate(steps.public_dict(step)) for step in run.steps
    ]
    return response


@router.get("/{run_id}/timeline/restricted", response_model=list[AgentStepRestrictedRead])
def get_restricted_timeline(
    run_id: str,
    _principal: AdminPrincipal,
    db: Session = Depends(get_db),
):
    run = db.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    steps = (
        db.execute(
            select(AgentStep)
            .where(AgentStep.run_id == run_id)
            .order_by(AgentStep.created_at.asc())
        )
        .scalars()
        .all()
    )
    service = AgentStepService(db)
    return [service.restricted_dict(step) for step in steps]


@router.get("/{run_id}/trace")
def stream_run_trace(run_id: str, principal: ProductUser, db: Session = Depends(get_db)):
    get_owned_run(db, run_id, principal.owner_id)

    return StreamingResponse(
        _trace_events(run_id, principal.owner_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{run_id}/feedback", response_model=RunFeedbackResponse)
def submit_run_feedback(
    run_id: str,
    payload: RunFeedbackRequest,
    principal: ProductUser,
    db: Session = Depends(get_db),
):
    run = get_owned_run(db, run_id, principal.owner_id)

    run.feedback_status = payload.status
    run.feedback_note = payload.note
    run.feedback_at = datetime.now(timezone.utc)
    db.add(run)
    db.commit()
    db.refresh(run)

    return RunFeedbackResponse(
        run_id=run.id,
        feedback_status=payload.status,
        feedback_note=run.feedback_note,
    )


def _trace_events(run_id: str, owner_id: str) -> Iterator[str]:
    """Poll persisted steps and expose each public event once per SSE connection.

    Ownership is rechecked on every poll, not only when the stream is opened, so
    a long-lived connection never bypasses the same isolation rule as GET /runs.
    """
    sent_ids: set[str] = set()
    allowed_events = {
        "inspection",
        "agent_plan",
        "agent_observation",
        "agent_guardrail",
        "checkpoint_resume",
        "plan",
        "tool_call",
        "tool_result",
        "observation",
        "approval_required",
        "approval_decision",
        "mcp_execution",
        "patch",
        "baseline_test_result",
        "targeted_test_result",
        "regression_test_result",
        "test_result",
        "verification",
        "reflection",
        "final",
        "error",
    }

    while True:
        db = SessionLocal()
        try:
            run = db.execute(
                select(AgentRun)
                .where(AgentRun.id == run_id)
                .where(AgentRun.owner_id == owner_id)
            ).scalar_one_or_none()
            if run is None:
                yield _sse("error", {"message": "Run not found"})
                return

            steps = (
                db.execute(
                    select(AgentStep)
                    .where(AgentStep.run_id == run_id)
                    .order_by(AgentStep.created_at.asc())
                )
                .scalars()
                .all()
            )

            for step in steps:
                if step.id in sent_ids or step.step_type not in allowed_events:
                    continue
                sent_ids.add(step.id)
                yield _sse(step.step_type, _step_payload(step))

            if run.status in TERMINAL_AGENT_RUN_STATUSES and len(sent_ids) >= len(
                [step for step in steps if step.step_type in allowed_events]
            ):
                return
        finally:
            db.close()

        time.sleep(1)


def _step_payload(step: AgentStep) -> dict:
    payload = AgentStepService.public_dict(step)
    return {
        "id": payload["id"],
        "run_id": payload["run_id"],
        "type": payload["step_type"],
        "tool_name": payload["tool_name"],
        "input": payload["input_json"],
        "output": payload["output_json"],
        "input_classification": payload["input_classification"],
        "output_classification": payload["output_classification"],
        "duration_ms": payload["duration_ms"],
        "created_at": payload["created_at"].isoformat(),
    }


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

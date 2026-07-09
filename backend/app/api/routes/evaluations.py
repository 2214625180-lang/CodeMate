from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from redis.exceptions import RedisError
from sqlalchemy.orm import Session

from app.api.auth import (
    require_evaluation_admin,
    require_evaluation_runner,
    require_evaluation_viewer,
)
from app.core.database import get_db
from app.core.queue import enqueue_evaluation_run
from app.schemas.evaluations import (
    EvaluationDatasetCreate,
    EvaluationDatasetRead,
    EvaluationDatasetRunRequest,
    EvaluationDatasetSnapshotRead,
    EvaluationDatasetUpdate,
    EvaluationGateResultRead,
    EvaluationHistoryRead,
    EvaluationRunArtifactRead,
    EvaluationRunCompareRead,
    EvaluationRunRead,
    EvaluationSnapshotBackfillRequest,
    EvaluationSnapshotBackfillResultRead,
    FixEvaluationRunRequest,
    RetrievalEvaluationRunRequest,
)
from app.services.evaluation_dataset_service import EvaluationDatasetService
from app.services.evaluation_artifact_service import EvaluationArtifactService
from app.services.evaluation_service import EvaluationService
from app.services.evaluation_snapshot_backfill_service import EvaluationSnapshotBackfillService

router = APIRouter(
    prefix="/evaluations",
    tags=["evaluations"],
    dependencies=[Depends(require_evaluation_viewer)],
)


@router.get("", response_model=list[EvaluationRunRead])
def list_evaluation_runs(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return EvaluationService(db).list_runs(limit=limit)


@router.get("/datasets", response_model=list[EvaluationDatasetRead])
def list_evaluation_datasets(
    task_type: str | None = Query(default=None, pattern="^(retrieval|fix)$"),
    db: Session = Depends(get_db),
):
    return EvaluationDatasetService(db).list_datasets(task_type=task_type)


@router.post(
    "/datasets",
    response_model=EvaluationDatasetRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_evaluation_admin)],
)
def create_evaluation_dataset(
    payload: EvaluationDatasetCreate,
    db: Session = Depends(get_db),
):
    try:
        return EvaluationDatasetService(db).create_dataset(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post(
    "/datasets/{dataset_id}/run",
    response_model=EvaluationRunRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_evaluation_runner)],
)
def run_evaluation_dataset(
    dataset_id: str,
    payload: EvaluationDatasetRunRequest | None = None,
    db: Session = Depends(get_db),
):
    payload = payload or EvaluationDatasetRunRequest()
    try:
        dataset_service = EvaluationDatasetService(db)
        dataset = dataset_service.get_dataset(dataset_id)
        snapshot = dataset_service.current_snapshot(dataset)
        service = EvaluationService(db)
        run_name = payload.name or f"{dataset.name} candidate"
        if dataset.task_type == "retrieval":
            evaluation_run = service.create_retrieval_run(
                RetrievalEvaluationRunRequest(
                    name=run_name,
                    dataset_id=dataset.id,
                    dataset_version=snapshot.version,
                    dataset_snapshot_id=snapshot.id,
                    top_k=payload.top_k,
                    cases=snapshot.cases_json,
                )
            )
        elif dataset.task_type == "fix":
            evaluation_run = service.create_fix_run(
                FixEvaluationRunRequest(
                    name=run_name,
                    dataset_id=dataset.id,
                    dataset_version=snapshot.version,
                    dataset_snapshot_id=snapshot.id,
                    require_tests_ran=payload.require_tests_ran,
                    cases=snapshot.cases_json,
                )
            )
        else:
            raise ValueError(f"Unsupported evaluation dataset task type: {dataset.task_type}")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    try:
        enqueue_evaluation_run(evaluation_run.id)
    except RedisError as exc:
        EvaluationService(db).fail_run(evaluation_run.id, f"Failed to enqueue evaluation: {exc}")
        return EvaluationService(db).get_run(evaluation_run.id)
    return EvaluationService(db).get_run(evaluation_run.id)


@router.get(
    "/datasets/{dataset_id}/gate",
    response_model=EvaluationGateResultRead,
)
def evaluate_regression_gate(
    dataset_id: str,
    candidate_run_id: str = Query(..., min_length=1, max_length=36),
    db: Session = Depends(get_db),
):
    try:
        return EvaluationService(db).evaluate_gate(
            dataset_id=dataset_id,
            candidate_run_id=candidate_run_id,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get(
    "/datasets/{dataset_id}/snapshots",
    response_model=list[EvaluationDatasetSnapshotRead],
)
def list_evaluation_dataset_snapshots(dataset_id: str, db: Session = Depends(get_db)):
    try:
        return EvaluationDatasetService(db).list_snapshots(dataset_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/datasets/{dataset_id}/snapshots/backfill",
    response_model=EvaluationSnapshotBackfillResultRead,
    dependencies=[Depends(require_evaluation_admin)],
)
def backfill_evaluation_dataset_snapshots(
    dataset_id: str,
    payload: EvaluationSnapshotBackfillRequest | None = None,
    db: Session = Depends(get_db),
):
    payload = payload or EvaluationSnapshotBackfillRequest()
    try:
        EvaluationDatasetService(db).get_dataset(dataset_id)
        return EvaluationSnapshotBackfillService(db).backfill(
            dataset_id=dataset_id,
            run_id=payload.run_id,
            task_type=payload.task_type,
            limit=payload.limit,
            dry_run=payload.dry_run,
            create_missing_snapshots=payload.create_missing_snapshots,
            include_details=payload.include_details,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/datasets/{dataset_id}/history",
    response_model=EvaluationHistoryRead,
)
def get_evaluation_dataset_history(
    dataset_id: str,
    limit: int = Query(default=30, ge=1, le=100),
    created_after: datetime | None = Query(default=None),
    created_before: datetime | None = Query(default=None),
    status_filter: str | None = Query(
        default=None,
        alias="status",
        pattern="^(running|completed|failed)$",
    ),
    gate_status: str | None = Query(
        default=None,
        pattern="^(passed|failed|inconclusive|not_evaluated)$",
    ),
    provider: str | None = Query(default=None, max_length=128),
    model: str | None = Query(default=None, max_length=255),
    db: Session = Depends(get_db),
):
    try:
        return EvaluationService(db).dataset_history(
            dataset_id,
            limit=limit,
            created_after=created_after,
            created_before=created_before,
            status_filter=status_filter,
            gate_status_filter=gate_status,
            provider_filter=provider,
            model_filter=model,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/dataset-snapshots/{snapshot_id}",
    response_model=EvaluationDatasetSnapshotRead,
)
def get_evaluation_dataset_snapshot(snapshot_id: str, db: Session = Depends(get_db)):
    try:
        return EvaluationDatasetService(db).get_snapshot(snapshot_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/datasets/{dataset_id}", response_model=EvaluationDatasetRead)
def get_evaluation_dataset(dataset_id: str, db: Session = Depends(get_db)):
    try:
        return EvaluationDatasetService(db).get_dataset(dataset_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put(
    "/datasets/{dataset_id}",
    response_model=EvaluationDatasetRead,
    dependencies=[Depends(require_evaluation_admin)],
)
def update_evaluation_dataset(
    dataset_id: str,
    payload: EvaluationDatasetUpdate,
    db: Session = Depends(get_db),
):
    try:
        return EvaluationDatasetService(db).update_dataset(dataset_id, payload)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.delete(
    "/datasets/{dataset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_evaluation_admin)],
)
def delete_evaluation_dataset(dataset_id: str, db: Session = Depends(get_db)):
    try:
        EvaluationDatasetService(db).delete_dataset(dataset_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/compare",
    response_model=EvaluationRunCompareRead,
)
def compare_evaluation_runs(
    baseline_run_id: str = Query(..., min_length=1, max_length=36),
    candidate_run_id: str = Query(..., min_length=1, max_length=36),
    db: Session = Depends(get_db),
):
    try:
        return EvaluationService(db).compare_runs(
            baseline_run_id=baseline_run_id,
            candidate_run_id=candidate_run_id,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get(
    "/{evaluation_run_id}/artifact",
    response_model=EvaluationRunArtifactRead,
)
def get_evaluation_run_artifact(
    evaluation_run_id: str,
    include_agent_steps: bool = Query(default=True),
    max_payload_chars: int = Query(default=12000, ge=1000, le=200000),
    db: Session = Depends(get_db),
):
    try:
        return EvaluationArtifactService(db).build_run_artifact(
            evaluation_run_id,
            include_agent_steps=include_agent_steps,
            max_payload_chars=max_payload_chars,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{evaluation_run_id}", response_model=EvaluationRunRead)
def get_evaluation_run(evaluation_run_id: str, db: Session = Depends(get_db)):
    try:
        return EvaluationService(db).get_run(evaluation_run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/retrieval",
    response_model=EvaluationRunRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_evaluation_runner)],
)
def run_retrieval_evaluation(
    payload: RetrievalEvaluationRunRequest,
    db: Session = Depends(get_db),
):
    try:
        evaluation_run = EvaluationService(db).create_retrieval_run(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    try:
        enqueue_evaluation_run(evaluation_run.id)
    except RedisError as exc:
        EvaluationService(db).fail_run(evaluation_run.id, f"Failed to enqueue evaluation: {exc}")
        return EvaluationService(db).get_run(evaluation_run.id)
    return EvaluationService(db).get_run(evaluation_run.id)


@router.post(
    "/fix",
    response_model=EvaluationRunRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_evaluation_runner)],
)
def run_fix_evaluation(
    payload: FixEvaluationRunRequest,
    db: Session = Depends(get_db),
):
    try:
        evaluation_run = EvaluationService(db).create_fix_run(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    try:
        enqueue_evaluation_run(evaluation_run.id)
    except RedisError as exc:
        EvaluationService(db).fail_run(evaluation_run.id, f"Failed to enqueue evaluation: {exc}")
        return EvaluationService(db).get_run(evaluation_run.id)
    return EvaluationService(db).get_run(evaluation_run.id)

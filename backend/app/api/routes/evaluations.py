from fastapi import APIRouter, Depends, HTTPException, Query, status
from redis.exceptions import RedisError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.queue import enqueue_evaluation_run
from app.schemas.evaluations import (
    EvaluationDatasetCreate,
    EvaluationDatasetRead,
    EvaluationDatasetUpdate,
    EvaluationGateResultRead,
    EvaluationRunCompareRead,
    EvaluationRunRead,
    FixEvaluationRunRequest,
    RetrievalEvaluationRunRequest,
)
from app.services.evaluation_dataset_service import EvaluationDatasetService
from app.services.evaluation_service import EvaluationService

router = APIRouter(prefix="/evaluations", tags=["evaluations"])


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
)
def create_evaluation_dataset(
    payload: EvaluationDatasetCreate,
    db: Session = Depends(get_db),
):
    try:
        return EvaluationDatasetService(db).create_dataset(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/datasets/{dataset_id}/gate", response_model=EvaluationGateResultRead)
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


@router.get("/datasets/{dataset_id}", response_model=EvaluationDatasetRead)
def get_evaluation_dataset(dataset_id: str, db: Session = Depends(get_db)):
    try:
        return EvaluationDatasetService(db).get_dataset(dataset_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/datasets/{dataset_id}", response_model=EvaluationDatasetRead)
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


@router.delete("/datasets/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_evaluation_dataset(dataset_id: str, db: Session = Depends(get_db)):
    try:
        EvaluationDatasetService(db).delete_dataset(dataset_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/compare", response_model=EvaluationRunCompareRead)
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
)
def run_retrieval_evaluation(
    payload: RetrievalEvaluationRunRequest,
    db: Session = Depends(get_db),
):
    evaluation_run = EvaluationService(db).create_retrieval_run(payload)
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
)
def run_fix_evaluation(
    payload: FixEvaluationRunRequest,
    db: Session = Depends(get_db),
):
    evaluation_run = EvaluationService(db).create_fix_run(payload)
    try:
        enqueue_evaluation_run(evaluation_run.id)
    except RedisError as exc:
        EvaluationService(db).fail_run(evaluation_run.id, f"Failed to enqueue evaluation: {exc}")
        return EvaluationService(db).get_run(evaluation_run.id)
    return EvaluationService(db).get_run(evaluation_run.id)

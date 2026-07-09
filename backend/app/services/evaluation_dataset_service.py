from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.evaluation_dataset import EvaluationDataset
from app.models.evaluation_dataset_snapshot import EvaluationDatasetSnapshot
from app.models.evaluation_run import EvaluationRun
from app.schemas.evaluations import (
    EvaluationDatasetCreate,
    EvaluationDatasetUpdate,
    EvaluationGatePolicy,
    FixEvaluationCase,
    RetrievalEvaluationCase,
)


class EvaluationDatasetService:
    def __init__(self, db: Session):
        self.db = db

    def list_datasets(self, *, task_type: str | None = None) -> list[EvaluationDataset]:
        statement = select(EvaluationDataset).order_by(
            EvaluationDataset.updated_at.desc(),
            EvaluationDataset.created_at.desc(),
        )
        if task_type is not None:
            statement = statement.where(EvaluationDataset.task_type == task_type)
        return list(self.db.execute(statement).scalars().all())

    def get_dataset(self, dataset_id: str) -> EvaluationDataset:
        dataset = self.db.get(EvaluationDataset, dataset_id)
        if dataset is None:
            raise FileNotFoundError("Evaluation dataset not found")
        return dataset

    def create_dataset(self, request: EvaluationDatasetCreate) -> EvaluationDataset:
        cases = self._validate_cases(request.task_type, request.cases_json)
        dataset = EvaluationDataset(
            name=request.name.strip(),
            task_type=request.task_type,
            description=request.description,
            version=request.version,
            baseline_run_id=None,
            gate_policy_json=self._normalize_policy(request.gate_policy_json),
            cases_json=cases,
            metadata_json=request.metadata_json,
        )
        self.db.add(dataset)
        self.db.flush()
        if request.baseline_run_id:
            dataset.baseline_run_id = self._validate_baseline_run(
                dataset=dataset,
                baseline_run_id=request.baseline_run_id,
                task_type=dataset.task_type,
            )
        self._upsert_snapshot(dataset)
        self.db.commit()
        self.db.refresh(dataset)
        return dataset

    def update_dataset(
        self,
        dataset_id: str,
        request: EvaluationDatasetUpdate,
    ) -> EvaluationDataset:
        dataset = self.get_dataset(dataset_id)
        updated_fields = request.model_fields_set

        if "name" in updated_fields:
            if not request.name or not request.name.strip():
                raise ValueError("Dataset name is required")
            dataset.name = request.name.strip()
        if "description" in updated_fields:
            dataset.description = request.description
        if "metadata_json" in updated_fields:
            dataset.metadata_json = request.metadata_json or {}
        if "gate_policy_json" in updated_fields and request.gate_policy_json is not None:
            dataset.gate_policy_json = self._normalize_policy(request.gate_policy_json)

        task_type = (
            request.task_type
            if "task_type" in updated_fields and request.task_type
            else dataset.task_type
        )
        cases_json = dataset.cases_json
        cases_changed = "cases_json" in updated_fields
        if cases_changed:
            if not request.cases_json:
                raise ValueError("Dataset cases are required")
            cases_json = request.cases_json

        dataset.task_type = task_type
        dataset.cases_json = self._validate_cases(task_type, cases_json)
        if "baseline_run_id" in updated_fields:
            dataset.baseline_run_id = self._validate_baseline_run(
                dataset=dataset,
                baseline_run_id=request.baseline_run_id,
                task_type=task_type,
            )
        elif dataset.baseline_run_id:
            self._validate_baseline_run(
                dataset=dataset,
                baseline_run_id=dataset.baseline_run_id,
                task_type=task_type,
            )

        if cases_changed and "version" in updated_fields and request.version is not None:
            if request.version <= dataset.version:
                raise ValueError("Dataset version must increase when cases change")
            dataset.version = request.version
        elif "version" in updated_fields and request.version is not None:
            dataset.version = request.version
        elif cases_changed:
            dataset.version += 1

        self.db.add(dataset)
        self._upsert_snapshot(dataset)
        self.db.commit()
        self.db.refresh(dataset)
        return dataset

    def delete_dataset(self, dataset_id: str) -> None:
        dataset = self.get_dataset(dataset_id)
        self.db.delete(dataset)
        self.db.commit()

    def get_snapshot(self, snapshot_id: str) -> EvaluationDatasetSnapshot:
        snapshot = self.db.get(EvaluationDatasetSnapshot, snapshot_id)
        if snapshot is None:
            raise FileNotFoundError("Evaluation dataset snapshot not found")
        return snapshot

    def list_snapshots(self, dataset_id: str) -> list[EvaluationDatasetSnapshot]:
        self.get_dataset(dataset_id)
        statement = (
            select(EvaluationDatasetSnapshot)
            .where(EvaluationDatasetSnapshot.dataset_id == dataset_id)
            .order_by(
                EvaluationDatasetSnapshot.version.desc(),
                EvaluationDatasetSnapshot.created_at.desc(),
            )
        )
        return list(self.db.execute(statement).scalars().all())

    def current_snapshot(self, dataset: EvaluationDataset) -> EvaluationDatasetSnapshot:
        return self._upsert_snapshot(dataset)

    def _validate_cases(self, task_type: str, cases: list[dict]) -> list[dict]:
        limit = 200 if task_type == "retrieval" else 50
        if len(cases) > limit:
            raise ValueError(f"{task_type} datasets support at most {limit} cases")

        try:
            if task_type == "retrieval":
                return [RetrievalEvaluationCase(**case).model_dump() for case in cases]
            if task_type == "fix":
                return [FixEvaluationCase(**case).model_dump() for case in cases]
        except ValidationError as exc:
            first_error = exc.errors()[0] if exc.errors() else None
            message = first_error["msg"] if first_error else str(exc)
            raise ValueError(f"Invalid {task_type} case: {message}") from exc

        raise ValueError(f"Unsupported evaluation dataset task type: {task_type}")

    def _validate_baseline_run(
        self,
        *,
        dataset: EvaluationDataset,
        baseline_run_id: str | None,
        task_type: str,
    ) -> str | None:
        if not baseline_run_id:
            return None

        run = self.db.get(EvaluationRun, baseline_run_id)
        if run is None:
            raise ValueError("Baseline evaluation run not found")
        if run.status != "completed":
            raise ValueError("Baseline evaluation run must be completed")
        if run.task_type != task_type:
            raise ValueError("Baseline evaluation run task type must match dataset task type")
        if run.dataset_id and run.dataset_id != dataset.id:
            raise ValueError("Baseline evaluation run must belong to this benchmark dataset")
        return run.id

    def _normalize_policy(self, policy: EvaluationGatePolicy | dict | None) -> dict:
        if isinstance(policy, EvaluationGatePolicy):
            return policy.model_dump()
        return EvaluationGatePolicy(**(policy or {})).model_dump()

    def _upsert_snapshot(self, dataset: EvaluationDataset) -> EvaluationDatasetSnapshot:
        statement = select(EvaluationDatasetSnapshot).where(
            EvaluationDatasetSnapshot.dataset_id == dataset.id,
            EvaluationDatasetSnapshot.version == dataset.version,
        )
        snapshot = self.db.execute(statement).scalars().first()
        if snapshot is not None:
            if snapshot.task_type != dataset.task_type or snapshot.cases_json != dataset.cases_json:
                raise ValueError(
                    "Dataset version already has a different snapshot; bump dataset version"
                )
            return snapshot

        snapshot = EvaluationDatasetSnapshot(
            dataset_id=dataset.id,
            name=dataset.name,
            task_type=dataset.task_type,
            description=dataset.description,
            version=dataset.version,
            baseline_run_id=dataset.baseline_run_id,
            gate_policy_json=dataset.gate_policy_json,
            cases_json=dataset.cases_json,
            metadata_json=dataset.metadata_json,
        )
        self.db.add(snapshot)
        self.db.flush()
        return snapshot

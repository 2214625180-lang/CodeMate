from collections import Counter
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.evaluation_dataset import EvaluationDataset
from app.models.evaluation_dataset_snapshot import EvaluationDatasetSnapshot
from app.models.evaluation_run import EvaluationRun
from app.schemas.evaluations import FixEvaluationCase, RetrievalEvaluationCase


class EvaluationSnapshotBackfillService:
    def __init__(self, db: Session):
        self.db = db

    def backfill(
        self,
        *,
        dataset_id: str | None = None,
        run_id: str | None = None,
        task_type: str | None = None,
        limit: int | None = None,
        dry_run: bool = False,
        create_missing_snapshots: bool = True,
        include_details: bool = False,
    ) -> dict:
        details: list[dict[str, Any]] = []
        counts: Counter[str] = Counter()
        created_snapshot_ids: set[str] = set()

        runs = self._candidate_runs(
            dataset_id=dataset_id,
            run_id=run_id,
            task_type=task_type,
            limit=limit,
        )
        for run in runs:
            result = self._backfill_run(
                run,
                create_missing_snapshots=create_missing_snapshots,
            )
            counts[result["status"]] += 1
            if result.get("created_snapshot_id"):
                created_snapshot_ids.add(str(result["created_snapshot_id"]))
            if include_details or result["status"] != "backfilled":
                details.append(result)

        if dry_run:
            self.db.rollback()
        else:
            self.db.commit()

        output: dict[str, Any] = {
            "dry_run": dry_run,
            "scanned": len(runs),
            "backfilled": counts["backfilled"],
            "skipped": sum(count for status, count in counts.items() if status != "backfilled"),
            "created_snapshots": len(created_snapshot_ids),
            "status_counts": dict(sorted(counts.items())),
        }
        if include_details or details:
            output["details"] = details
        return output

    def _candidate_runs(
        self,
        *,
        dataset_id: str | None,
        run_id: str | None,
        task_type: str | None,
        limit: int | None,
    ) -> list[EvaluationRun]:
        statement = select(EvaluationRun).where(
            EvaluationRun.dataset_id.is_not(None),
            EvaluationRun.dataset_snapshot_id.is_(None),
        )
        if dataset_id:
            statement = statement.where(EvaluationRun.dataset_id == dataset_id)
        if run_id:
            statement = statement.where(EvaluationRun.id == run_id)
        if task_type:
            statement = statement.where(EvaluationRun.task_type == task_type)
        statement = statement.order_by(EvaluationRun.created_at.asc())
        if limit is not None and limit > 0:
            statement = statement.limit(limit)
        return list(self.db.execute(statement).scalars().all())

    def _backfill_run(
        self,
        run: EvaluationRun,
        *,
        create_missing_snapshots: bool,
    ) -> dict[str, Any]:
        request_json = dict(run.request_json) if isinstance(run.request_json, dict) else {}
        raw_cases = request_json.get("cases")
        if not isinstance(raw_cases, list) or not raw_cases:
            return self._skipped(run, "missing_request_cases")

        dataset = self.db.get(EvaluationDataset, run.dataset_id)
        if dataset is None:
            return self._skipped(run, "missing_dataset")
        if dataset.task_type != run.task_type:
            return self._skipped(
                run,
                "dataset_task_type_mismatch",
                dataset_task_type=dataset.task_type,
            )

        try:
            cases = self._normalize_cases(task_type=run.task_type, raw_cases=raw_cases)
        except ValueError as exc:
            return self._skipped(run, "invalid_request_cases", reason=str(exc))

        version = run.dataset_version or request_json.get("dataset_version") or dataset.version
        if not isinstance(version, int) or version < 1:
            return self._skipped(run, "invalid_dataset_version", dataset_version=version)

        snapshot = self._find_snapshot(dataset_id=dataset.id, version=version)
        created_snapshot_id = None
        if snapshot is None:
            if not create_missing_snapshots:
                return self._skipped(run, "missing_snapshot", dataset_version=version)
            snapshot = EvaluationDatasetSnapshot(
                dataset_id=dataset.id,
                name=dataset.name,
                task_type=dataset.task_type,
                description=dataset.description,
                version=version,
                baseline_run_id=dataset.baseline_run_id,
                gate_policy_json=dataset.gate_policy_json,
                cases_json=cases,
                metadata_json=self._backfill_metadata(dataset, run),
            )
            self.db.add(snapshot)
            self.db.flush()
            created_snapshot_id = snapshot.id
        else:
            try:
                snapshot_cases = self._normalize_cases(
                    task_type=snapshot.task_type,
                    raw_cases=snapshot.cases_json,
                )
            except ValueError as exc:
                return self._skipped(
                    run,
                    "invalid_snapshot_cases",
                    dataset_version=version,
                    snapshot_id=snapshot.id,
                    reason=str(exc),
                )
            if snapshot.task_type != run.task_type:
                return self._skipped(
                    run,
                    "snapshot_task_type_mismatch",
                    dataset_version=version,
                    snapshot_id=snapshot.id,
                )
            if snapshot_cases != cases:
                return self._skipped(
                    run,
                    "snapshot_cases_mismatch",
                    dataset_version=version,
                    snapshot_id=snapshot.id,
                )

        run.dataset_snapshot_id = snapshot.id
        if run.dataset_version is None:
            run.dataset_version = version
        request_json["dataset_snapshot_id"] = snapshot.id
        request_json["dataset_version"] = run.dataset_version
        run.request_json = request_json
        self.db.add(run)
        return {
            "status": "backfilled",
            "run_id": run.id,
            "dataset_id": dataset.id,
            "dataset_version": version,
            "dataset_snapshot_id": snapshot.id,
            "created_snapshot_id": created_snapshot_id,
        }

    def _normalize_cases(self, *, task_type: str, raw_cases: list[Any]) -> list[dict[str, Any]]:
        try:
            if task_type == "retrieval":
                return [RetrievalEvaluationCase(**case).model_dump() for case in raw_cases]
            if task_type == "fix":
                return [FixEvaluationCase(**case).model_dump() for case in raw_cases]
        except Exception as exc:
            raise ValueError(str(exc)) from exc
        raise ValueError(f"Unsupported evaluation task type: {task_type}")

    def _find_snapshot(
        self,
        *,
        dataset_id: str,
        version: int,
    ) -> EvaluationDatasetSnapshot | None:
        statement = select(EvaluationDatasetSnapshot).where(
            EvaluationDatasetSnapshot.dataset_id == dataset_id,
            EvaluationDatasetSnapshot.version == version,
        )
        return self.db.execute(statement).scalars().first()

    def _backfill_metadata(self, dataset: EvaluationDataset, run: EvaluationRun) -> dict[str, Any]:
        metadata = dataset.metadata_json if isinstance(dataset.metadata_json, dict) else {}
        return {
            **metadata,
            "_snapshot_backfill": {
                "source_run_id": run.id,
                "source_run_created_at": run.created_at.isoformat() if run.created_at else None,
                "backfilled_at": datetime.now(UTC).isoformat(),
                "dataset_metadata_source": "current_dataset",
            },
        }

    def _skipped(self, run: EvaluationRun, code: str, **extra: Any) -> dict[str, Any]:
        return {
            "status": code,
            "run_id": run.id,
            "dataset_id": run.dataset_id,
            "dataset_version": run.dataset_version,
            **extra,
        }

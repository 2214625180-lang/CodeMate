#!/usr/bin/env python3
"""Materialize, index, and register the CodeMate v1 benchmark in a local deployment."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(REPOSITORY_ROOT))

from app.core.database import SessionLocal, init_db  # noqa: E402
from app.models.evaluation_dataset import EvaluationDataset  # noqa: E402
from app.models.repository import Repository  # noqa: E402
from app.schemas.evaluations import (  # noqa: E402
    EvaluationGatePolicy,
    FixEvaluationCase,
    RetrievalEvaluationCase,
)
from app.services.evaluation_dataset_service import EvaluationDatasetService  # noqa: E402
from app.services.index_service import IndexService  # noqa: E402
from app.services.mcp_tenancy_service import MCPTenancyService  # noqa: E402
from scripts.benchmark_suite import (  # noqa: E402
    DATASET_PATHS,
    MANIFEST_PATH,
    load_json,
    materialize_repositories,
    validate_dataset,
)


DATASET_IDS = {
    "retrieval": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "fix": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--materialize-dir",
        default="benchmarks/.materialized",
        help="Directory for the deterministic Git fixture repositories.",
    )
    parser.add_argument(
        "--skip-index",
        action="store_true",
        help="Register repository rows and datasets without indexing source chunks.",
    )
    args = parser.parse_args()

    manifest = load_json(MANIFEST_PATH)
    target_root = (REPOSITORY_ROOT / args.materialize_dir).resolve()
    target_root.mkdir(parents=True, exist_ok=True)
    fixture_reports = materialize_repositories(
        manifest=manifest,
        target_root=target_root,
        verify_commits=True,
    )
    dataset_reports = [validate_dataset(path, manifest=manifest) for path in DATASET_PATHS]

    init_db()
    with SessionLocal() as database:
        repositories = register_repositories(
            database,
            fixture_reports=fixture_reports,
            skip_index=args.skip_index,
        )
        datasets = register_datasets(
            database,
            manifest=manifest,
            dataset_reports=dataset_reports,
        )

    print(
        json.dumps(
            {
                "status": "ready" if not args.skip_index else "registered_without_index",
                "repositories": repositories,
                "datasets": datasets,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def register_repositories(
    database: Any,
    *,
    fixture_reports: list[dict[str, str]],
    skip_index: bool,
) -> list[dict[str, Any]]:
    tenant_id = MCPTenancyService(database).default_tenant().id
    registered: list[dict[str, Any]] = []
    for fixture in fixture_reports:
        repository = database.get(Repository, fixture["repo_id"])
        if repository is None:
            repository = Repository(
                id=fixture["repo_id"],
                name=fixture["fixture"],
                repo_url=fixture["path"],
                tenant_id=tenant_id,
                status="pending",
            )
        else:
            repository.name = fixture["fixture"]
            repository.repo_url = fixture["path"]
            repository.tenant_id = repository.tenant_id or tenant_id
            repository.status = "pending"
            repository.error_message = None
        database.add(repository)
        database.commit()
        if not skip_index:
            IndexService(database).index_repository(repository.id, full=True)
            database.refresh(repository)
            if repository.status != "indexed":
                raise RuntimeError(
                    f"Failed to index fixture {repository.name}: {repository.error_message}"
                )
            if repository.last_commit_hash != fixture["commit_sha"]:
                raise RuntimeError(
                    f"Indexed commit mismatch for {repository.name}: "
                    f"expected {fixture['commit_sha']}, got {repository.last_commit_hash}"
                )
        registered.append(
            {
                "id": repository.id,
                "name": repository.name,
                "status": repository.status,
                "commit_sha": fixture["commit_sha"],
            }
        )
    return registered


def register_datasets(
    database: Any,
    *,
    manifest: dict[str, Any],
    dataset_reports: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    report_by_task = {report["task_type"]: report for report in dataset_reports}
    fixture_commits = {
        item["fixture"]: item["commit_sha"] for item in manifest.get("repositories") or []
    }
    service = EvaluationDatasetService(database)
    registered: list[dict[str, Any]] = []
    for path in DATASET_PATHS:
        payload = load_json(path)
        task_type = str(payload["task_type"])
        case_model = RetrievalEvaluationCase if task_type == "retrieval" else FixEvaluationCase
        normalized_cases = [case_model(**case).model_dump() for case in payload["cases_json"]]
        dataset_id = DATASET_IDS[task_type]
        metadata = {
            **(payload.get("metadata_json") or {}),
            "dataset_sha256": report_by_task[task_type]["sha256"],
            "fixture_commits": fixture_commits,
        }
        dataset = database.get(EvaluationDataset, dataset_id)
        if dataset is None:
            dataset = EvaluationDataset(
                id=dataset_id,
                name=payload["name"],
                task_type=task_type,
                description=payload.get("description"),
                version=int(payload["version"]),
                gate_policy_json=EvaluationGatePolicy(
                    **(payload.get("gate_policy_json") or {})
                ).model_dump(),
                cases_json=normalized_cases,
                metadata_json=metadata,
            )
            database.add(dataset)
            database.flush()
        else:
            assert_existing_dataset_matches(
                dataset,
                task_type=task_type,
                version=int(payload["version"]),
                cases=normalized_cases,
            )
            dataset.name = payload["name"]
            dataset.description = payload.get("description")
            dataset.gate_policy_json = EvaluationGatePolicy(
                **(payload.get("gate_policy_json") or {})
            ).model_dump()
            dataset.metadata_json = metadata
            database.add(dataset)
        snapshot = service.current_snapshot(dataset)
        database.commit()
        registered.append(
            {
                "id": dataset.id,
                "name": dataset.name,
                "task_type": dataset.task_type,
                "version": dataset.version,
                "snapshot_id": snapshot.id,
                "case_count": len(dataset.cases_json),
                "dataset_sha256": report_by_task[task_type]["sha256"],
            }
        )
    return registered


def assert_existing_dataset_matches(
    dataset: EvaluationDataset,
    *,
    task_type: str,
    version: int,
    cases: list[dict[str, Any]],
) -> None:
    if dataset.task_type != task_type or dataset.version != version:
        raise ValueError(
            f"Dataset {dataset.id} identity changed; create a new benchmark version instead"
        )
    if dataset.cases_json != cases:
        expected_hash = json_hash(cases)
        actual_hash = json_hash(dataset.cases_json)
        raise ValueError(
            f"Dataset {dataset.id} v{version} is immutable and differs from the database "
            f"(file={expected_hash}, database={actual_hash}); bump the dataset version"
        )


def json_hash(value: Any) -> str:
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())

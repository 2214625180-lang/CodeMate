#!/usr/bin/env python3
"""Seed the built-in interview demo repository and benchmark dataset."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal, ensure_default_mcp_tenant
from app.core.queue import enqueue_agent_run
from app.llm import get_llm_provider
from app.models.evaluation_dataset import EvaluationDataset
from app.models.evaluation_dataset_snapshot import EvaluationDatasetSnapshot
from app.models.repository import Repository
from app.schemas.evaluations import FixEvaluationCase
from app.services.agent_service import AgentService
from app.services.index_service import IndexService
from app.services.mcp_tenancy_service import MCPTenancyService


FIXTURE_COMMIT_DATE = "2026-01-01T00:00:00+00:00"
RESULT_PREFIX = "CODEMATE_DEMO_RESULT="


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import the built-in cart fixture and create its fix benchmark."
    )
    parser.add_argument(
        "--fixture-root",
        type=Path,
        default=Path("/demo/examples/demo-cart-bug"),
        help="Path containing demo.json and the fixture source tree.",
    )
    parser.add_argument(
        "--frontend-url",
        default=os.getenv("FRONTEND_URL", "http://localhost:3000"),
    )
    parser.add_argument(
        "--start-run",
        action="store_true",
        help="Create and enqueue a real-model fix run after seeding.",
    )
    return parser.parse_args()


def load_manifest(fixture_root: Path) -> dict[str, Any]:
    manifest_path = fixture_root / "demo.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Demo manifest not found: {manifest_path}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = {
        "repo_id",
        "dataset_id",
        "repository_name",
        "dataset_name",
        "dataset_version",
        "issue",
        "target_test_command",
        "regression_test_command",
        "allowed_changed_files",
        "category",
        "tags",
    }
    missing = sorted(required - payload.keys())
    if missing:
        raise ValueError(f"Demo manifest is missing fields: {', '.join(missing)}")
    return payload


def require_real_llm() -> tuple[str, str]:
    provider_name = settings.llm_provider.strip().lower().replace("_", "-")
    if provider_name == "mock":
        raise RuntimeError(
            "The interview demo refuses LLM_PROVIDER=mock. Configure a real provider "
            "and an explicit LLM_MODEL in .env."
        )
    if not settings.llm_model.strip():
        raise RuntimeError("The interview demo requires an explicit LLM_MODEL.")
    provider = get_llm_provider()
    model_name = str(getattr(provider, "model", settings.llm_model)).strip()
    return provider_name, model_name


def run_git(
    arguments: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None
) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=settings.clone_timeout_seconds,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"git {' '.join(arguments)} failed: {detail}")
    return completed.stdout.strip()


def materialize_fixture_repository(fixture_root: Path) -> tuple[Path, str]:
    workspace_root = Path(settings.workspace_dir).resolve()
    fixture_store = (workspace_root / ".demo-fixtures").resolve()
    fixture_store.mkdir(parents=True, exist_ok=True)
    source_checkout = fixture_store / "demo-cart-bug-source"
    bare_repository = fixture_store / "demo-cart-bug.git"

    for target in (source_checkout, bare_repository):
        try:
            target.resolve().relative_to(fixture_store)
        except ValueError as exc:
            raise RuntimeError(f"Unsafe demo fixture target: {target}") from exc
        if target.exists():
            shutil.rmtree(target)

    shutil.copytree(fixture_root, source_checkout)
    run_git(["init", "--initial-branch=main"], cwd=source_checkout)
    run_git(["config", "user.name", "CodeMate Demo"], cwd=source_checkout)
    run_git(["config", "user.email", "demo@codemate.local"], cwd=source_checkout)
    run_git(["add", "--all"], cwd=source_checkout)

    commit_env = os.environ.copy()
    commit_env.update(
        {
            "GIT_AUTHOR_DATE": FIXTURE_COMMIT_DATE,
            "GIT_COMMITTER_DATE": FIXTURE_COMMIT_DATE,
        }
    )
    run_git(
        ["commit", "--quiet", "-m", "Add reproducible cart checkout defect"],
        cwd=source_checkout,
        env=commit_env,
    )
    commit_sha = run_git(["rev-parse", "HEAD"], cwd=source_checkout)
    run_git(["clone", "--quiet", "--bare", str(source_checkout), str(bare_repository)])
    return bare_repository, commit_sha


class DemoIndexService(IndexService):
    """Import only the local fixture while retaining normal indexing safeguards."""

    def _clone_repository(self, repo_url: str, workspace: Path) -> None:
        fixture_store = Path(settings.workspace_dir).resolve() / ".demo-fixtures"
        expected_repository = fixture_store / "demo-cart-bug.git"
        if (
            settings.app_env != "local"
            or Path(repo_url) != expected_repository
            or expected_repository.resolve() != expected_repository
            or not expected_repository.is_dir()
        ):
            raise ValueError("Demo import requires the generated local fixture repository.")

        # This CLI-only importer permits file transport for the one generated
        # fixture. The public IndexService continues to reject local Git URLs.
        environment = self._safe_git_environment()
        environment["GIT_ALLOW_PROTOCOL"] = "file"
        run_git(
            [
                "clone", "--quiet", "--no-local", "--no-checkout",
                "--no-recurse-submodules", "--", str(expected_repository), str(workspace),
            ],
            env=environment,
        )
        self._assert_checkout_budget(workspace)
        checkout = self._run_git(workspace, ["checkout", "--force"])
        if checkout.returncode != 0:
            raise RuntimeError("Repository checkout failed.")
        self._assert_workspace_budget(workspace)


def upsert_repository(
    *,
    manifest: dict[str, Any],
    repository_url: Path,
    commit_sha: str,
) -> Repository:
    with SessionLocal() as database:
        repository = database.get(Repository, manifest["repo_id"])
        if repository is None:
            repository = Repository(id=manifest["repo_id"])
        repository.name = manifest["repository_name"]
        repository.repo_url = str(repository_url)
        repository.tenant_id = MCPTenancyService(database).default_tenant().id
        repository.status = "pending"
        repository.error_message = None
        database.add(repository)
        database.commit()

        DemoIndexService(database).index_repository(repository.id, full=True)
        database.expire_all()
        indexed_repository = database.get(Repository, repository.id)
        if indexed_repository is None or indexed_repository.status != "indexed":
            detail = (
                indexed_repository.error_message if indexed_repository else "repository missing"
            )
            raise RuntimeError(f"Demo repository indexing failed: {detail}")
        if indexed_repository.last_commit_hash != commit_sha:
            raise RuntimeError(
                "Indexed fixture commit does not match the materialized source commit."
            )
        database.expunge(indexed_repository)
        return indexed_repository


def upsert_fix_dataset(
    *,
    manifest: dict[str, Any],
    commit_sha: str,
    llm_provider: str,
    llm_model: str,
) -> EvaluationDataset:
    case = FixEvaluationCase(
        case_id="demo-cart-coupon-checkout",
        repo_id=manifest["repo_id"],
        issue=manifest["issue"],
        test_command=manifest["target_test_command"],
        expected_status="verified_success",
        allowed_changed_files=manifest["allowed_changed_files"],
        category=manifest["category"],
        tags=manifest["tags"],
    ).model_dump(mode="json")
    metadata = {
        "fixture": "examples/demo-cart-bug",
        "fixture_commit_sha": commit_sha,
        "llm_provider": llm_provider,
        "llm_model": llm_model,
        "embedding_provider": settings.embedding_provider,
        "embedding_model": settings.embedding_model,
        "target_test_command": manifest["target_test_command"],
        "regression_test_command": manifest["regression_test_command"],
        "synthetic_failure_forced": False,
    }

    with SessionLocal() as database:
        dataset = database.get(EvaluationDataset, manifest["dataset_id"])
        if dataset is None:
            dataset = EvaluationDataset(id=manifest["dataset_id"])
        dataset.name = manifest["dataset_name"]
        dataset.task_type = "fix"
        dataset.description = (
            "Real-model interview demo: reproducible baseline failure, multi-file repair, "
            "targeted verification, and full regression checks."
        )
        dataset.version = int(manifest["dataset_version"])
        dataset.baseline_run_id = None
        dataset.gate_policy_json = {
            "max_primary_metric_drop": 0.0,
            "max_regressed_cases": 0,
            "allow_incompatible": False,
            "require_matching_dataset_snapshot": True,
            "max_avg_latency_increase_sec": None,
            "max_avg_tool_call_increase": None,
        }
        dataset.cases_json = [case]
        dataset.metadata_json = metadata
        database.add(dataset)
        database.flush()

        snapshot = (
            database.execute(
                select(EvaluationDatasetSnapshot).where(
                    EvaluationDatasetSnapshot.dataset_id == dataset.id,
                    EvaluationDatasetSnapshot.version == dataset.version,
                )
            )
            .scalars()
            .first()
        )
        if snapshot is None:
            snapshot = EvaluationDatasetSnapshot(
                dataset_id=dataset.id,
                version=dataset.version,
            )
        snapshot.name = dataset.name
        snapshot.task_type = dataset.task_type
        snapshot.description = dataset.description
        snapshot.baseline_run_id = dataset.baseline_run_id
        snapshot.gate_policy_json = dataset.gate_policy_json
        snapshot.cases_json = dataset.cases_json
        snapshot.metadata_json = dataset.metadata_json
        database.add(snapshot)
        database.commit()
        database.refresh(dataset)
        database.expunge(dataset)
        return dataset


def start_agent_run(manifest: dict[str, Any], *, owner_id: str) -> str:
    with SessionLocal() as database:
        run = AgentService(database).create_fix_run(
            repo_id=manifest["repo_id"],
            owner_id=owner_id,
            issue=manifest["issue"],
            test_command=manifest["target_test_command"],
        )
        enqueue_agent_run(run.id)
        return run.id


def build_result(
    *,
    manifest: dict[str, Any],
    commit_sha: str,
    repository: Repository,
    dataset: EvaluationDataset,
    frontend_url: str,
    run_id: str | None,
    llm_provider: str,
    llm_model: str,
) -> dict[str, Any]:
    base_url = frontend_url.rstrip("/")
    fix_url = f"{base_url}/repos/{repository.id}/fix"
    if run_id:
        fix_url = f"{fix_url}?runId={run_id}"
    return {
        "repo_id": repository.id,
        "dataset_id": dataset.id,
        "run_id": run_id,
        "fixture_commit_sha": commit_sha,
        "llm_provider": llm_provider,
        "llm_model": llm_model,
        "embedding_provider": settings.embedding_provider,
        "repository_url": f"{base_url}/repos/{repository.id}",
        "fix_url": fix_url,
        "benchmark_url": f"{base_url}/evaluations/datasets",
        "target_test_command": manifest["target_test_command"],
        "regression_test_command": manifest["regression_test_command"],
    }


def main() -> int:
    args = parse_args()
    fixture_root = args.fixture_root.resolve()
    manifest = load_manifest(fixture_root)
    llm_provider, llm_model = require_real_llm()
    ensure_default_mcp_tenant()
    repository_url, commit_sha = materialize_fixture_repository(fixture_root)
    repository = upsert_repository(
        manifest=manifest,
        repository_url=repository_url,
        commit_sha=commit_sha,
    )
    dataset = upsert_fix_dataset(
        manifest=manifest,
        commit_sha=commit_sha,
        llm_provider=llm_provider,
        llm_model=llm_model,
    )
    run_id = (
        start_agent_run(manifest, owner_id=repository.owner_id)
        if args.start_run
        else None
    )
    result = build_result(
        manifest=manifest,
        commit_sha=commit_sha,
        repository=repository,
        dataset=dataset,
        frontend_url=args.frontend_url,
        run_id=run_id,
        llm_provider=llm_provider,
        llm_model=llm_model,
    )
    print(f"{RESULT_PREFIX}{json.dumps(result, sort_keys=True)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

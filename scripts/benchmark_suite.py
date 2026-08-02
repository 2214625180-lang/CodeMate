#!/usr/bin/env python3
"""Validate and materialize the reproducible CodeMate benchmark fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPOSITORY_ROOT / "benchmarks" / "fixtures"
DATASET_ROOT = REPOSITORY_ROOT / "benchmarks" / "datasets" / "v1"
MANIFEST_PATH = FIXTURE_ROOT / "manifest.json"
DATASET_PATHS = (DATASET_ROOT / "retrieval.json", DATASET_ROOT / "fix.json")
REQUIRED_RETRIEVAL_CATEGORIES = {
    "symbol_location",
    "error_stack",
    "cross_file_call",
    "reference_location",
    "configuration_error",
    "async_boundary",
    "malicious_prompt",
}
REQUIRED_FIX_CATEGORIES = {
    "symbol_location",
    "error_stack",
    "cross_file_call",
    "configuration_error",
    "async_boundary",
    "malicious_prompt",
    "not_reproduced",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--materialize-dir",
        help="Keep deterministic Git repositories in this directory instead of a temporary one.",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Validate metadata and commits without executing fixture baseline tests.",
    )
    args = parser.parse_args()

    if args.materialize_dir:
        target_root = Path(args.materialize_dir).resolve()
        target_root.mkdir(parents=True, exist_ok=True)
        report = validate_suite(target_root=target_root, run_tests=not args.skip_tests)
    else:
        with tempfile.TemporaryDirectory(prefix="codemate-benchmark-") as temporary_directory:
            report = validate_suite(
                target_root=Path(temporary_directory),
                run_tests=not args.skip_tests,
            )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def validate_suite(*, target_root: Path, run_tests: bool) -> dict[str, Any]:
    manifest = load_json(MANIFEST_PATH)
    repositories = manifest.get("repositories")
    if not isinstance(repositories, list) or len(repositories) not in range(4, 7):
        raise ValueError("Fixture manifest must define 4 to 6 repositories")

    materialized = materialize_repositories(
        manifest=manifest,
        target_root=target_root,
        verify_commits=True,
    )
    datasets = [validate_dataset(path, manifest=manifest) for path in DATASET_PATHS]
    test_reports = run_fixture_tests(manifest) if run_tests else []
    return {
        "status": "valid",
        "fixture_count": len(repositories),
        "fixtures": materialized,
        "datasets": datasets,
        "fixture_tests": test_reports,
    }


def materialize_repositories(
    *,
    manifest: dict[str, Any],
    target_root: Path,
    verify_commits: bool,
) -> list[dict[str, str]]:
    identity = manifest.get("commit_identity") or {}
    repositories = manifest.get("repositories") or []
    target_root = target_root.resolve()
    if target_root == Path(target_root.anchor):
        raise ValueError("Refusing to materialize fixtures at a filesystem root")

    reports: list[dict[str, str]] = []
    for repository in repositories:
        fixture_name = required_string(repository, "fixture")
        source = (FIXTURE_ROOT / fixture_name).resolve()
        if source.parent != FIXTURE_ROOT.resolve() or not source.is_dir():
            raise ValueError(f"Invalid fixture source: {fixture_name}")
        destination = (target_root / fixture_name).resolve()
        if destination.parent != target_root:
            raise ValueError(f"Invalid fixture destination: {destination}")
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        commit_sha = create_deterministic_commit(destination, identity=identity)
        expected_sha = required_string(repository, "commit_sha")
        if verify_commits and commit_sha != expected_sha:
            raise ValueError(
                f"Fixture {fixture_name} commit mismatch: expected {expected_sha}, got {commit_sha}"
            )
        reports.append(
            {
                "fixture": fixture_name,
                "repo_id": required_string(repository, "repo_id"),
                "path": str(destination),
                "commit_sha": commit_sha,
            }
        )
    return reports


def create_deterministic_commit(repository_path: Path, *, identity: dict[str, Any]) -> str:
    run(["git", "init", "--quiet", "--initial-branch=main"], cwd=repository_path)
    run(["git", "config", "core.autocrlf", "false"], cwd=repository_path)
    run(["git", "add", "--all"], cwd=repository_path)
    timestamp = required_string(identity, "timestamp")
    environment = {
        **os.environ,
        "GIT_AUTHOR_NAME": required_string(identity, "name"),
        "GIT_AUTHOR_EMAIL": required_string(identity, "email"),
        "GIT_AUTHOR_DATE": timestamp,
        "GIT_COMMITTER_NAME": required_string(identity, "name"),
        "GIT_COMMITTER_EMAIL": required_string(identity, "email"),
        "GIT_COMMITTER_DATE": timestamp,
    }
    run(
        [
            "git",
            "-c",
            "commit.gpgSign=false",
            "commit",
            "--quiet",
            "--no-gpg-sign",
            "--message",
            required_string(identity, "message"),
        ],
        cwd=repository_path,
        env=environment,
    )
    return run(["git", "rev-parse", "HEAD"], cwd=repository_path).stdout.strip()


def validate_dataset(path: Path, *, manifest: dict[str, Any]) -> dict[str, Any]:
    dataset = load_json(path)
    task_type = required_string(dataset, "task_type")
    cases = dataset.get("cases_json")
    expected_count = 30 if task_type == "retrieval" else 20
    if not isinstance(cases, list) or len(cases) < expected_count:
        raise ValueError(f"{path} must contain at least {expected_count} {task_type} cases")

    repositories = {
        required_string(item, "repo_id"): item for item in manifest.get("repositories") or []
    }
    case_ids: set[str] = set()
    categories: set[str] = set()
    for case in cases:
        case_id = required_string(case, "case_id")
        if case_id in case_ids:
            raise ValueError(f"Duplicate case_id in {path}: {case_id}")
        case_ids.add(case_id)
        category = required_string(case, "category")
        categories.add(category)
        repository = repositories.get(required_string(case, "repo_id"))
        if repository is None:
            raise ValueError(f"Unknown fixture repository in case {case_id}")
        fixture_root = FIXTURE_ROOT / required_string(repository, "fixture")
        if task_type == "retrieval":
            validate_retrieval_case(case, case_id=case_id, fixture_root=fixture_root)
        else:
            validate_fix_case(
                case,
                case_id=case_id,
                fixture_root=fixture_root,
                repository=repository,
            )

    required_categories = (
        REQUIRED_RETRIEVAL_CATEGORIES if task_type == "retrieval" else REQUIRED_FIX_CATEGORIES
    )
    missing_categories = sorted(required_categories - categories)
    if missing_categories:
        raise ValueError(f"{path} is missing required categories: {missing_categories}")
    canonical = json.dumps(dataset, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {
        "path": str(path.relative_to(REPOSITORY_ROOT)),
        "task_type": task_type,
        "cases": len(cases),
        "categories": sorted(categories),
        "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


def validate_retrieval_case(case: dict[str, Any], *, case_id: str, fixture_root: Path) -> None:
    expected_path = safe_fixture_file(fixture_root, required_string(case, "expected_file"))
    expected_lines = case.get("expected_lines")
    if not (
        isinstance(expected_lines, list)
        and len(expected_lines) == 2
        and all(isinstance(value, int) for value in expected_lines)
    ):
        raise ValueError(f"Retrieval case {case_id} must define [start, end] expected_lines")
    start_line, end_line = expected_lines
    line_count = len(expected_path.read_text(encoding="utf-8").splitlines())
    if start_line < 1 or end_line < start_line or end_line > line_count:
        raise ValueError(f"Retrieval case {case_id} has out-of-range expected_lines")


def validate_fix_case(
    case: dict[str, Any],
    *,
    case_id: str,
    fixture_root: Path,
    repository: dict[str, Any],
) -> None:
    test_command = required_string(case, "test_command")
    allowed_commands = {
        required_string(repository, "test_command"),
        required_string(repository, "health_test_command"),
    }
    if test_command not in allowed_commands:
        raise ValueError(f"Fix case {case_id} uses a command outside its fixture manifest")
    expected_status = required_string(case, "expected_status")
    allowed_files = case.get("allowed_changed_files")
    if not isinstance(allowed_files, list):
        raise ValueError(f"Fix case {case_id} must define allowed_changed_files")
    for relative_path in allowed_files:
        safe_fixture_file(fixture_root, str(relative_path))
    if expected_status == "verified_success" and not allowed_files:
        raise ValueError(f"Verified fix case {case_id} must restrict changed files")
    if expected_status == "not_reproduced" and allowed_files:
        raise ValueError(f"Negative-control case {case_id} cannot allow changed files")


def run_fixture_tests(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for repository in manifest.get("repositories") or []:
        fixture_name = required_string(repository, "fixture")
        fixture_root = FIXTURE_ROOT / fixture_name
        baseline = run_shell_command(
            required_string(repository, "test_command"),
            cwd=fixture_root,
        )
        health = run_shell_command(
            required_string(repository, "health_test_command"),
            cwd=fixture_root,
        )
        if baseline.returncode == 0:
            raise ValueError(f"Fixture {fixture_name} baseline unexpectedly passes")
        if health.returncode != 0:
            raise ValueError(f"Fixture {fixture_name} health control unexpectedly fails")
        reports.append(
            {
                "fixture": fixture_name,
                "baseline_reproduced": True,
                "health_control_passed": True,
            }
        )
    return reports


def safe_fixture_file(fixture_root: Path, relative_path: str) -> Path:
    root = fixture_root.resolve()
    path = (root / relative_path).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Fixture path escapes repository root: {relative_path}") from exc
    if not path.is_file():
        raise ValueError(f"Fixture file does not exist: {relative_path}")
    return path


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def required_string(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"Expected non-empty string field {key}")
    return item.strip()


def run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )


def run_shell_command(command: str, *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command.split(),
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


if __name__ == "__main__":
    raise SystemExit(main())

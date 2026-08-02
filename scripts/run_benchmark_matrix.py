#!/usr/bin/env python3
"""Run the real benchmark against separately configured ablation deployments."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from evaluation_api_client import add_api_token_argument  # noqa: E402
from export_eval_report import fetch_artifact  # noqa: E402
from run_dataset_eval_gate import create_dataset_run, wait_for_evaluation_run  # noqa: E402


MATRIX_PATH = REPOSITORY_ROOT / "benchmarks" / "ablations.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_api_token_argument(parser)
    parser.add_argument(
        "--variant",
        action="append",
        default=[],
        metavar="NAME=BASE_URL",
        help="A deployment configured exactly as the named ablation variant.",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--timeout-sec", type=int, default=3600)
    parser.add_argument("--poll-interval-sec", type=float, default=5.0)
    parser.add_argument("--output-dir", default="artifacts/benchmarks")
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Run only supplied variants; the report is marked partial and cannot prove all ablations.",
    )
    args = parser.parse_args()

    matrix = load_object(MATRIX_PATH)
    variant_urls = parse_variant_urls(args.variant)
    configured_variants = {
        variant["name"]: variant for variant in matrix.get("variants") or []
    }
    unknown = sorted(set(variant_urls) - set(configured_variants))
    if unknown:
        raise ValueError(f"Unknown ablation variants: {unknown}")
    missing = sorted(set(configured_variants) - set(variant_urls))
    if missing and not args.allow_partial:
        raise ValueError(
            "All ablation deployments are required unless --allow-partial is set. "
            f"Missing: {missing}"
        )
    if not variant_urls:
        raise ValueError("At least one --variant NAME=BASE_URL is required")

    output_root = Path(args.output_dir).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    runs = []
    for variant_name, base_url in variant_urls.items():
        variant = configured_variants[variant_name]
        run = execute_variant(
            variant=variant,
            base_url=base_url,
            top_k=args.top_k,
            timeout_sec=args.timeout_sec,
            poll_interval_sec=args.poll_interval_sec,
            api_token=args.api_token,
            output_root=output_root,
        )
        runs.append(run)

    report = {
        "schema_version": "codemate-benchmark-results/v1",
        "status": "complete" if not missing else "partial",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "matrix_sha256": canonical_sha256(matrix),
        "missing_variants": missing,
        "comparisons": matrix.get("comparisons") or [],
        "runs": runs,
    }
    json_path = output_root / "benchmark-matrix.json"
    markdown_path = output_root / "benchmark-matrix.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"json": str(json_path), "markdown": str(markdown_path)}, indent=2))
    return 0 if report["status"] == "complete" else 2


def execute_variant(
    *,
    variant: dict[str, Any],
    base_url: str,
    top_k: int,
    timeout_sec: int,
    poll_interval_sec: float,
    api_token: str | None,
    output_root: Path,
) -> dict[str, Any]:
    name = str(variant["name"])
    created = create_dataset_run(
        base_url=base_url,
        dataset_id=str(variant["dataset_id"]),
        name=f"Benchmark matrix: {name}",
        top_k=top_k,
        require_tests_ran=True,
        api_token=api_token,
    )
    completed, timed_out = wait_for_evaluation_run(
        base_url=base_url,
        evaluation_run_id=str(created["id"]),
        timeout_sec=timeout_sec,
        poll_interval_sec=poll_interval_sec,
        api_token=api_token,
    )
    if timed_out or completed.get("status") != "completed":
        raise RuntimeError(
            f"Variant {name} did not complete: status={completed.get('status')}, timeout={timed_out}"
        )
    artifact = fetch_artifact(
        base_url=base_url,
        run_id=str(created["id"]),
        include_agent_steps=True,
        max_payload_chars=12000,
        api_token=api_token,
    )
    config_snapshot = (artifact.get("run") or {}).get("config_snapshot") or {}
    assert_expected_config(
        config_snapshot,
        expected=variant.get("expected_config") or {},
        variant_name=name,
    )
    artifact_path = output_root / f"{name}-{created['id']}.json"
    artifact_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    run_metadata = artifact.get("run") or {}
    return {
        "variant": name,
        "task_type": variant["task_type"],
        "run_id": created["id"],
        "dataset_id": run_metadata.get("dataset_id"),
        "dataset_snapshot_id": run_metadata.get("dataset_snapshot_id"),
        "metrics": run_metadata.get("metrics_json") or {},
        "model": config_snapshot.get("llm_model"),
        "provider": config_snapshot.get("llm_provider"),
        "embedding_model": config_snapshot.get("embedding_model"),
        "code_commit_sha": config_snapshot.get("code_commit_sha"),
        "prompt_bundle_sha256": config_snapshot.get("prompt_bundle_sha256"),
        "dataset_cases_sha256": config_snapshot.get("dataset_cases_sha256"),
        "artifact": str(artifact_path),
    }


def assert_expected_config(
    config_snapshot: dict[str, Any],
    *,
    expected: dict[str, Any],
    variant_name: str,
) -> None:
    mismatches = []
    for dotted_path, expected_value in expected.items():
        actual_value: Any = config_snapshot
        for segment in str(dotted_path).split("."):
            actual_value = actual_value.get(segment) if isinstance(actual_value, dict) else None
        if actual_value != expected_value:
            mismatches.append(
                f"{dotted_path}: expected {expected_value!r}, got {actual_value!r}"
            )
    if mismatches:
        raise ValueError(
            f"Deployment for {variant_name} does not match the ablation config: "
            + "; ".join(mismatches)
        )


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# CodeMate Benchmark Matrix",
        "",
        f"Status: **{report['status']}**",
        "",
        "| Variant | Run | Primary metric | Value | p95 latency | Artifact |",
        "| --- | --- | --- | ---: | ---: | --- |",
    ]
    for run in report.get("runs") or []:
        metrics = run.get("metrics") or {}
        primary = metrics.get("primary_metric") or "n/a"
        value = metrics.get(primary) if isinstance(primary, str) else None
        latency = metrics.get("p95_latency_sec")
        lines.append(
            f"| {run['variant']} | {run['run_id']} | {primary} | "
            f"{format_number(value)} | {format_number(latency)} | `{run['artifact']}` |"
        )
    lines.extend(
        [
            "",
            "Every value above is copied from a completed Evaluation artifact. Missing variants "
            "remain missing; this renderer never substitutes placeholder percentages.",
            "",
        ]
    )
    return "\n".join(lines)


def format_number(value: Any) -> str:
    return f"{value:.4f}" if isinstance(value, int | float) else "n/a"


def parse_variant_urls(values: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for value in values:
        name, separator, url = value.partition("=")
        if not separator or not name.strip() or not url.strip():
            raise ValueError(f"Invalid --variant value: {value!r}; expected NAME=BASE_URL")
        if name.strip() in parsed:
            raise ValueError(f"Duplicate --variant: {name.strip()}")
        parsed[name.strip()] = url.strip().rstrip("/")
    return parsed


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def canonical_sha256(value: Any) -> str:
    import hashlib

    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Run the three retrieval ablations directly against a bootstrapped local database."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend"))

from app.core.config import settings  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.schemas.evaluations import RetrievalEvaluationRunRequest  # noqa: E402
from app.services.evaluation_artifact_service import EvaluationArtifactService  # noqa: E402
from app.services.evaluation_dataset_service import EvaluationDatasetService  # noqa: E402
from app.services.evaluation_service import EvaluationService  # noqa: E402


RETRIEVAL_DATASET_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
VARIANTS = (
    ("vector-only", "vector", False, False),
    ("hybrid", "hybrid", False, False),
    ("hybrid-rerank-context", "hybrid", True, True),
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--output",
        default="benchmarks/results/local-retrieval-latest.json",
    )
    args = parser.parse_args()
    if args.top_k < 1 or args.top_k > 20:
        raise ValueError("--top-k must be between 1 and 20")

    with SessionLocal() as database:
        dataset_service = EvaluationDatasetService(database)
        dataset = dataset_service.get_dataset(RETRIEVAL_DATASET_ID)
        snapshot = dataset_service.current_snapshot(dataset)
        runs = []
        for name, strategy, rerank_enabled, context_enabled in VARIANTS:
            settings.retrieval_strategy = strategy
            settings.retrieval_rerank_enabled = rerank_enabled
            settings.retrieval_context_expansion_enabled = context_enabled
            evaluation_service = EvaluationService(database)
            run = evaluation_service.create_retrieval_run(
                RetrievalEvaluationRunRequest(
                    name=f"Local retrieval ablation: {name}",
                    dataset_id=dataset.id,
                    dataset_version=snapshot.version,
                    dataset_snapshot_id=snapshot.id,
                    top_k=args.top_k,
                    cases=snapshot.cases_json,
                )
            )
            completed = evaluation_service.execute_run(run.id)
            artifact = EvaluationArtifactService(database).build_run_artifact(completed.id)
            runs.append(
                {
                    "variant": name,
                    "run_id": completed.id,
                    "metrics": completed.metrics_json,
                    "config_snapshot": completed.config_snapshot,
                    "artifact": artifact,
                }
            )

    output = {
        "schema_version": "codemate-local-retrieval-results/v1",
        "status": "completed",
        "certification": "engineering_smoke_only",
        "limitations": [
            "Embedding provider is the deterministic mock provider, not a production embedding model.",
            "The code worktree is dirty; code_worktree_dirty is preserved in each run artifact.",
            "Fix-agent ablations require a real LLM credential and are intentionally not inferred here.",
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset_id": RETRIEVAL_DATASET_ID,
        "top_k": args.top_k,
        "runs": runs,
    }
    output_path = (REPOSITORY_ROOT / args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(compact_report(output, output_path=output_path), ensure_ascii=False, indent=2))
    return 0


def compact_report(output: dict[str, Any], *, output_path: Path) -> dict[str, Any]:
    return {
        "status": output["status"],
        "certification": output["certification"],
        "artifact": str(output_path),
        "runs": [
            {
                "variant": run["variant"],
                "run_id": run["run_id"],
                "metrics": run["metrics"],
            }
            for run in output["runs"]
        ],
    }


if __name__ == "__main__":
    raise SystemExit(main())

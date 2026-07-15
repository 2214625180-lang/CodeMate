#!/usr/bin/env python3
import argparse
import asyncio
import hashlib
import json
import math
import os
import sys
import tempfile
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.sandbox.execution_protocol import ExecutionRequest  # noqa: E402
from app.sandbox.workload_identity import issue_assertion, load_private_key  # noqa: E402
from app.sandbox.workspace_archive import create_archive  # noqa: E402


RETRYABLE_STATUSES = {409, 502, 503, 504}


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * quantile) - 1))
    return round(ordered[index], 2)


def build_archive(sleep_seconds: float) -> tuple[str, str]:
    with tempfile.TemporaryDirectory(prefix="codemate-sandbox-probe-") as directory:
        workspace = Path(directory)
        (workspace / "package.json").write_text(
            json.dumps(
                {
                    "name": "codemate-sandbox-qualification",
                    "private": True,
                    "scripts": {"test": "node qualification.js"},
                },
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        (workspace / "qualification.js").write_text(
            f"setTimeout(() => process.exit(0), {int(max(0.0, sleep_seconds) * 1000)});\n",
            encoding="utf-8",
        )
        return create_archive(workspace, max_bytes=1024 * 1024, max_files=10)


class Probe:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.private_key = load_private_key(args.workload_key)
        self.archive, self.archive_sha256 = build_archive(args.sleep_seconds)

    def request(self, execution_id: str | None = None) -> ExecutionRequest:
        return ExecutionRequest(
            execution_id=execution_id or str(uuid.uuid4()),
            archive_base64=self.archive,
            archive_sha256=self.archive_sha256,
            command="npm test",
            shell_command="npm test",
            image=self.args.image,
            requested_runtime=self.args.runtime,
            timeout_seconds=self.args.execution_timeout_seconds,
        )

    def assertion(self, request: ExecutionRequest) -> str:
        return issue_assertion(
            private_key=self.private_key,
            issuer=self.args.issuer,
            subject=self.args.subject,
            audience=self.args.audience,
            request_hash=request.binding_hash(),
            ttl_seconds=self.args.assertion_ttl_seconds,
        )

    async def send(self, request: ExecutionRequest, assertion: str) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                verify=self.args.ca,
                cert=(self.args.cert, self.args.key),
                timeout=self.args.request_timeout_seconds,
                follow_redirects=False,
                trust_env=False,
                headers={"Connection": "close"},
            ) as client:
                response = await client.post(
                    f"{self.args.url.rstrip('/')}/v1/executions",
                    headers={"Authorization": f"Bearer {assertion}"},
                    json=request.model_dump(),
                )
            try:
                body = response.json()
            except ValueError:
                body = {"raw": response.text[:1000]}
            return {
                "status_code": response.status_code,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "instance": response.headers.get("X-CodeMate-Execution-Plane-Instance"),
                "idempotent_replay": response.headers.get("X-CodeMate-Idempotent-Replay") == "true",
                "body": body,
            }
        except Exception as exc:  # noqa: BLE001 - transport failures are probe evidence.
            return {
                "status_code": 0,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "error": f"{type(exc).__name__}: {exc}",
            }

    async def execute_with_retry(self, request: ExecutionRequest) -> dict[str, Any]:
        assertion = self.assertion(request)
        deadline = time.monotonic() + self.args.retry_timeout_seconds
        attempts: list[dict[str, Any]] = []
        started = time.perf_counter()
        while True:
            result = await self.send(request, assertion)
            attempts.append(result)
            if result["status_code"] == 200:
                result["last_attempt_latency_ms"] = result["latency_ms"]
                result["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
                result["attempt_count"] = len(attempts)
                result["attempt_instances"] = sorted(
                    {value["instance"] for value in attempts if value.get("instance")}
                )
                return result
            if (
                result["status_code"] not in RETRYABLE_STATUSES | {0}
                or time.monotonic() >= deadline
            ):
                result["last_attempt_latency_ms"] = result["latency_ms"]
                result["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
                result["attempt_count"] = len(attempts)
                result["attempt_instances"] = sorted(
                    {value["instance"] for value in attempts if value.get("instance")}
                )
                return result
            await asyncio.sleep(min(2.0, 0.2 * len(attempts)))

    def valid_execution(self, result: dict[str, Any], execution_id: str) -> bool:
        body = result.get("body") or {}
        attestation = body.get("attestation") or {}
        return bool(
            result.get("status_code") == 200
            and body.get("execution_id") == execution_id
            and body.get("archive_sha256") == self.archive_sha256
            and body.get("passed") is True
            and attestation.get("supply_chain") == "verified"
            and attestation.get("node_attestation") == "verified"
        )

    async def idempotency(self) -> dict[str, Any]:
        request = self.request()
        assertion = self.assertion(request)
        started = time.perf_counter()
        concurrent = await asyncio.gather(
            *(self.send(request, assertion) for _ in range(self.args.fanout))
        )
        cached = await self.execute_with_retry(request)
        statuses = Counter(value["status_code"] for value in concurrent)
        instances = sorted(
            {
                value["instance"]
                for value in [*concurrent, cached]
                if value.get("instance")
            }
        )
        passed = bool(
            all(value["status_code"] in {200, 409} for value in concurrent)
            and 200 in statuses
            and self.valid_execution(cached, request.execution_id)
            and cached.get("idempotent_replay") is True
            and len(instances) >= self.args.min_instances
        )
        return {
            "schema_version": 1,
            "mode": "idempotency",
            "status": "passed" if passed else "failed",
            "execution_id_sha256": hashlib.sha256(request.execution_id.encode()).hexdigest(),
            "fanout": self.args.fanout,
            "status_counts": dict(statuses),
            "serving_instances": instances,
            "cached_replay_observed": cached.get("idempotent_replay", False),
            "duration_seconds": round(time.perf_counter() - started, 3),
            "concurrent_results": concurrent,
            "cached_result": cached,
        }

    async def load(self) -> dict[str, Any]:
        semaphore = asyncio.Semaphore(self.args.concurrency)
        results: list[tuple[str, dict[str, Any]]] = []

        async def one() -> None:
            request = self.request()
            async with semaphore:
                result = await self.execute_with_retry(request)
            results.append((request.execution_id, result))

        started = time.perf_counter()
        await asyncio.gather(*(one() for _ in range(self.args.requests)))
        duration = time.perf_counter() - started
        successes = sum(self.valid_execution(result, execution_id) for execution_id, result in results)
        latencies = [float(result.get("latency_ms") or 0) for _, result in results]
        status_counts = Counter(result.get("status_code", 0) for _, result in results)
        instances = sorted(
            {
                instance
                for _, result in results
                for instance in result.get("attempt_instances", [])
                if instance
            }
        )
        success_rate = successes / self.args.requests
        p95 = percentile(latencies, 0.95)
        passed = bool(
            success_rate >= self.args.min_success_rate
            and p95 <= self.args.max_p95_ms
            and len(instances) >= self.args.min_instances
        )
        failures = [
            {"execution_id_sha256": hashlib.sha256(execution_id.encode()).hexdigest(), **result}
            for execution_id, result in results
            if not self.valid_execution(result, execution_id)
        ][:20]
        return {
            "schema_version": 1,
            "mode": "load",
            "status": "passed" if passed else "failed",
            "requests": self.args.requests,
            "concurrency": self.args.concurrency,
            "success_rate": round(success_rate, 4),
            "duration_seconds": round(duration, 3),
            "throughput_rps": round(self.args.requests / duration, 2) if duration else 0,
            "status_counts": dict(status_counts),
            "serving_instances": instances,
            "latency_ms": {
                "p50": percentile(latencies, 0.5),
                "p95": p95,
                "p99": percentile(latencies, 0.99),
                "max": round(max(latencies or [0]), 2),
            },
            "failures": failures,
        }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Probe the managed sandbox execution plane")
    value.add_argument("mode", choices=("idempotency", "load"))
    value.add_argument("--url", default=os.getenv("SANDBOX_QUALIFICATION_URL"))
    value.add_argument("--ca", default=os.getenv("SANDBOX_QUALIFICATION_CA_PATH"))
    value.add_argument("--cert", default=os.getenv("SANDBOX_QUALIFICATION_CERT_PATH"))
    value.add_argument("--key", default=os.getenv("SANDBOX_QUALIFICATION_KEY_PATH"))
    value.add_argument("--workload-key", default=os.getenv("SANDBOX_QUALIFICATION_WORKLOAD_KEY_PATH"))
    value.add_argument("--issuer", default=os.getenv("SANDBOX_WORKLOAD_IDENTITY_ISSUER", "codemate-staging"))
    value.add_argument("--subject", default=os.getenv("SANDBOX_WORKLOAD_IDENTITY_SUBJECT", "spiffe://codemate/staging/code-sandbox"))
    value.add_argument("--audience", default=os.getenv("SANDBOX_WORKLOAD_IDENTITY_AUDIENCE", "codemate-sandbox-execution-plane"))
    value.add_argument("--image", default=os.getenv("SANDBOX_NODE_IMAGE"))
    value.add_argument("--runtime", choices=("docker", "gvisor", "firecracker"), default="docker")
    value.add_argument("--requests", type=int, default=30)
    value.add_argument("--concurrency", type=int, default=10)
    value.add_argument("--fanout", type=int, default=12)
    value.add_argument("--min-instances", type=int, default=2)
    value.add_argument("--sleep-seconds", type=float, default=0.2)
    value.add_argument("--assertion-ttl-seconds", type=int, default=300)
    value.add_argument("--execution-timeout-seconds", type=int, default=60)
    value.add_argument("--request-timeout-seconds", type=float, default=90)
    value.add_argument("--retry-timeout-seconds", type=float, default=90)
    value.add_argument("--min-success-rate", type=float, default=0.99)
    value.add_argument("--max-p95-ms", type=float, default=10000)
    value.add_argument("--output", required=True)
    return value


def main() -> None:
    args = parser().parse_args()
    missing = [
        name
        for name in ("url", "ca", "cert", "key", "workload_key", "image")
        if not getattr(args, name)
    ]
    if missing:
        raise SystemExit(f"Missing sandbox probe settings: {', '.join(missing)}")
    if not args.url.startswith("https://"):
        raise SystemExit("Sandbox qualification requires an HTTPS execution-plane URL")
    args.requests = max(1, args.requests)
    args.concurrency = max(1, args.concurrency)
    args.fanout = max(2, args.fanout)
    probe = Probe(args)
    report = asyncio.run(probe.idempotency() if args.mode == "idempotency" else probe.load())
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()

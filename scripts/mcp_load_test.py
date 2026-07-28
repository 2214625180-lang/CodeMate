#!/usr/bin/env python3
import argparse
import asyncio
import json
import math
import os
import time
from collections import Counter
from pathlib import Path

import httpx


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * quantile) - 1))
    return round(ordered[index], 2)


async def run(args: argparse.Namespace) -> dict:
    semaphore = asyncio.Semaphore(args.concurrency)
    latencies: list[float] = []
    statuses: Counter[int] = Counter()
    reasons: Counter[str] = Counter()
    headers = {
        "Authorization": f"Bearer {args.api_token}",
        "X-CodeMate-Tenant-ID": args.tenant_id,
        "X-CodeMate-Tenant-Token": args.tenant_token,
        "Content-Type": "application/json",
    }
    if args.repo_id:
        headers["X-CodeMate-Repo-ID"] = args.repo_id

    async with httpx.AsyncClient(timeout=args.timeout_seconds) as client:
        async def one(index: int) -> None:
            async with semaphore:
                logical_request = index // args.idempotency_reuse
                request_headers = {
                    **headers,
                    "X-CodeMate-Idempotency-Key": f"load-{logical_request}",
                }
                started = time.perf_counter()
                try:
                    response = await client.post(
                        f"{args.base_url.rstrip('/')}/mcp-client/servers/{args.server}/call",
                        headers=request_headers,
                        json={
                            "tool_name": args.tool,
                            "arguments": {"value": f"load-{logical_request}"},
                        },
                    )
                    statuses[response.status_code] += 1
                    if response.status_code >= 400:
                        try:
                            detail = response.json().get("detail") or {}
                            reasons[str(detail.get("reason") or detail.get("code") or "unknown")] += 1
                        except Exception:
                            reasons["invalid_error_response"] += 1
                except Exception as exc:
                    statuses[0] += 1
                    reasons[type(exc).__name__] += 1
                finally:
                    latencies.append((time.perf_counter() - started) * 1000)

        started = time.perf_counter()
        await asyncio.gather(*(one(index) for index in range(args.requests)))
        duration = time.perf_counter() - started

    success = sum(count for status, count in statuses.items() if 200 <= status < 300)
    report = {
        "requests": args.requests,
        "concurrency": args.concurrency,
        "duration_seconds": round(duration, 3),
        "throughput_rps": round(args.requests / duration, 2) if duration else 0,
        "success_rate": round(success / args.requests, 4) if args.requests else 0,
        "status_counts": dict(statuses),
        "rejection_reasons": dict(reasons),
        "latency_ms": {
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "p99": percentile(latencies, 0.99),
            "max": round(max(latencies or [0]), 2),
        },
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Load test the tenant-scoped MCP Client API")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--api-token", default=os.getenv("MCP_CLIENT_API_TOKEN"))
    parser.add_argument("--tenant-id", default=os.getenv("MCP_TENANT_ID"))
    parser.add_argument("--tenant-token", default=os.getenv("MCP_TENANT_TOKEN"))
    parser.add_argument("--repo-id")
    parser.add_argument("--server", default="evidence")
    parser.add_argument("--tool", default="echo")
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--idempotency-reuse", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=float, default=30)
    parser.add_argument("--max-p95-ms", type=float, default=2000)
    parser.add_argument("--min-success-rate", type=float, default=0.95)
    parser.add_argument("--output", default="artifacts/production-evidence/load-test.json")
    args = parser.parse_args()
    missing = [
        name
        for name, value in {
            "MCP_CLIENT_API_TOKEN": args.api_token,
            "MCP_TENANT_ID": args.tenant_id,
            "MCP_TENANT_TOKEN": args.tenant_token,
        }.items()
        if not value
    ]
    if missing:
        raise SystemExit(f"Missing load-test credentials: {', '.join(missing)}")
    args.requests = max(1, args.requests)
    args.concurrency = max(1, args.concurrency)
    args.idempotency_reuse = max(1, args.idempotency_reuse)
    report = asyncio.run(run(args))
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["latency_ms"]["p95"] > args.max_p95_ms:
        raise SystemExit("P95 latency exceeded the configured gate")
    if report["success_rate"] < args.min_success_rate:
        raise SystemExit("Success rate fell below the configured gate")


if __name__ == "__main__":
    main()

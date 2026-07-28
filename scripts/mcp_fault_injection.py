#!/usr/bin/env python3
import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx


SCENARIOS = {
    "redis-restart": ("redis", "restart"),
    "postgres-restart": ("postgres", "restart"),
    "worker-crash": ("worker", "kill-start"),
}


def compose(prefix: list[str], *arguments: str) -> str:
    completed = subprocess.run(
        [*prefix, *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def health(base_url: str) -> dict:
    try:
        response = httpx.get(f"{base_url.rstrip('/')}/health/readiness", timeout=5)
        return {"status": response.status_code, "body": response.text[:500]}
    except Exception as exc:
        return {"status": 0, "error": str(exc)}


def wait_for_recovery(base_url: str, timeout_seconds: float) -> tuple[dict, float]:
    started = time.monotonic()
    last = health(base_url)
    while last.get("status") != 200 and time.monotonic() - started < timeout_seconds:
        time.sleep(1)
        last = health(base_url)
    return last, round(time.monotonic() - started, 3)


def wait_for_outage(base_url: str, timeout_seconds: float) -> tuple[dict, float]:
    started = time.monotonic()
    last = health(base_url)
    while last.get("status") == 200 and time.monotonic() - started < timeout_seconds:
        time.sleep(1)
        last = health(base_url)
    return last, round(time.monotonic() - started, 3)


def service_is_running(compose_ps: str, service: str) -> bool:
    try:
        parsed = json.loads(compose_ps)
        rows = parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        rows = [json.loads(line) for line in compose_ps.splitlines() if line.strip()]
    for row in rows:
        if row.get("Service") == service:
            return str(row.get("State") or "").lower() == "running"
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Run reversible CodeMate fault-injection drills")
    parser.add_argument("scenario", choices=sorted(SCENARIOS))
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--settle-seconds", type=float, default=5)
    parser.add_argument("--outage-timeout-seconds", type=float, default=30)
    parser.add_argument("--recovery-timeout-seconds", type=float, default=60)
    parser.add_argument("--output", default="artifacts/production-evidence/fault-injection.json")
    parser.add_argument("--compose-file", action="append", default=[])
    parser.add_argument("--env-file")
    parser.add_argument("--project-name")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Required because this command restarts or kills local Compose services.",
    )
    args = parser.parse_args()
    if not args.execute:
        raise SystemExit("Refusing to mutate Compose services without --execute")
    compose_prefix = ["docker", "compose"]
    if args.env_file:
        compose_prefix.extend(["--env-file", args.env_file])
    for compose_file in args.compose_file:
        compose_prefix.extend(["-f", compose_file])
    if args.project_name:
        compose_prefix.extend(["--project-name", args.project_name])
    service, action = SCENARIOS[args.scenario]
    evidence = {
        "scenario": args.scenario,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "before": health(args.base_url),
        "events": [],
    }
    failed = False
    try:
        if action == "restart":
            evidence["events"].append(
                {"command": f"stop {service}", "output": compose(compose_prefix, "stop", service)}
            )
            time.sleep(max(0.1, args.settle_seconds))
            evidence["during"], evidence["outage_detection_seconds"] = wait_for_outage(
                args.base_url, max(1, args.outage_timeout_seconds)
            )
            evidence["during_compose_ps"] = compose(compose_prefix, "ps", "--format", "json")
            evidence["service_down_observed"] = not service_is_running(
                evidence["during_compose_ps"], service
            )
            evidence["expected_outage_observed"] = (
                evidence["during"].get("status") != 200
                and evidence["service_down_observed"]
            )
            evidence["events"].append(
                {"command": f"start {service}", "output": compose(compose_prefix, "start", service)}
            )
        else:
            evidence["events"].append(
                {"command": f"kill {service}", "output": compose(compose_prefix, "kill", service)}
            )
            evidence["events"].append(
                {
                    "command": f"contain {service}",
                    "output": compose(compose_prefix, "stop", service),
                }
            )
            time.sleep(max(0.1, args.settle_seconds))
            evidence["during"], evidence["outage_detection_seconds"] = wait_for_outage(
                args.base_url, max(1, args.outage_timeout_seconds)
            )
            evidence["during_compose_ps"] = compose(compose_prefix, "ps", "--format", "json")
            evidence["service_down_observed"] = not service_is_running(
                evidence["during_compose_ps"], service
            )
            evidence["expected_outage_observed"] = (
                evidence["during"].get("status") != 200
                and evidence["service_down_observed"]
            )
            evidence["events"].append(
                {"command": f"start {service}", "output": compose(compose_prefix, "start", service)}
            )
        evidence["after"], evidence["recovery_seconds"] = wait_for_recovery(
            args.base_url, max(1, args.recovery_timeout_seconds)
        )
        evidence["compose_ps"] = compose(compose_prefix, "ps", "--format", "json")
        if evidence["after"].get("status") != 200:
            raise RuntimeError(f"{service} did not recover to a healthy state")
        if not evidence.get("expected_outage_observed"):
            raise RuntimeError(f"{service} fault was not observable in qualification evidence")
    except Exception as exc:  # Preserve evidence even when the drill itself fails.
        failed = True
        evidence["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            compose(compose_prefix, "start", service)
        except Exception as exc:
            failed = True
            evidence["recovery_error"] = f"{type(exc).__name__}: {exc}"
        evidence["finished_at"] = datetime.now(timezone.utc).isoformat()
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(evidence, indent=2, sort_keys=True))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

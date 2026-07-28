#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_gate(
    name: str,
    command: list[str],
    *,
    output_dir: Path,
    env: dict[str, str],
) -> dict[str, Any]:
    started = time.perf_counter()
    stdout_path = output_dir / f"{name}.stdout.log"
    stderr_path = output_dir / f"{name}.stderr.log"
    try:
        completed = subprocess.run(command, capture_output=True, text=True, env=env, check=False)
        stdout = completed.stdout
        stderr = completed.stderr
        exit_code = completed.returncode
    except OSError as exc:
        stdout = ""
        stderr = f"{type(exc).__name__}: {exc}"
        exit_code = 127
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    return {
        "name": name,
        "status": "passed" if exit_code == 0 else "failed",
        "exit_code": exit_code,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "stdout": stdout_path.name,
        "stderr": stderr_path.name,
    }


def http_gate(name: str, url: str, *, output_dir: Path) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        response = httpx.get(url, timeout=15, follow_redirects=False)
        payload = response.json()
        passed = response.status_code == 200
        result = {
            "name": name,
            "status": "passed" if passed else "failed",
            "status_code": response.status_code,
            "duration_seconds": round(time.perf_counter() - started, 3),
            "artifact": f"{name}.json",
        }
    except Exception as exc:
        payload = {"error": f"{type(exc).__name__}: {exc}"}
        result = {
            "name": name,
            "status": "failed",
            "status_code": 0,
            "duration_seconds": round(time.perf_counter() - started, 3),
            "artifact": f"{name}.json",
        }
    (output_dir / result["artifact"]).write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    return result


def compose_prefix(args: argparse.Namespace) -> list[str]:
    prefix = ["docker", "compose"]
    if args.env_file:
        prefix.extend(["--env-file", args.env_file])
    for path in args.compose_file:
        prefix.extend(["-f", path])
    if args.project_name:
        prefix.extend(["--project-name", args.project_name])
    return prefix


def write_manifest(output_dir: Path) -> None:
    entries = []
    for path in sorted(output_dir.iterdir()):
        if not path.is_file() or path.name == "manifest.sha256":
            continue
        entries.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}")
    (output_dir / "manifest.sha256").write_text("\n".join(entries) + "\n", encoding="utf-8")


def write_markdown(report: dict[str, Any], output_dir: Path) -> None:
    rows = [
        "# CodeMate Staging Qualification Report",
        "",
        f"- Decision: **{report['decision'].upper()}**",
        f"- Environment: `{report['environment']}`",
        f"- Started: `{report['started_at']}`",
        f"- Finished: `{report['finished_at']}`",
        "",
        "| Gate | Result | Duration |",
        "|---|---|---:|",
    ]
    for gate in report["gates"]:
        rows.append(
            f"| {gate['name']} | {gate['status']} | {gate.get('duration_seconds', 0)}s |"
        )
    performance = report.get("performance") or {}
    if performance:
        latency = performance.get("latency_ms") or {}
        rows.extend(
            [
                "",
                "## Load result",
                "",
                f"- Throughput: `{performance.get('throughput_rps')} RPS`",
                f"- Success rate: `{performance.get('success_rate')}`",
                f"- P50/P95/P99: `{latency.get('p50')}/{latency.get('p95')}/{latency.get('p99')} ms`",
            ]
        )
    if report.get("faults"):
        rows.extend(["", "## Recovery drills", "", "| Scenario | Recovery | Outage observed |", "|---|---:|---|"])
        for scenario, evidence in report["faults"].items():
            rows.append(
                f"| {scenario} | {evidence.get('recovery_seconds', 'n/a')}s | {evidence.get('expected_outage_observed', 'n/a')} |"
            )
    rows.extend(["", "Artifacts are integrity-bound by `manifest.sha256`.", ""])
    (output_dir / "qualification.md").write_text("\n".join(rows), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Execute the destructive, evidence-producing staging release qualification"
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--base-url", default=os.getenv("STAGING_BASE_URL"))
    parser.add_argument("--environment", default="staging")
    parser.add_argument("--server", default=os.getenv("MCP_LOAD_SERVER", "evidence"))
    parser.add_argument("--tool", default=os.getenv("MCP_LOAD_TOOL", "echo"))
    parser.add_argument("--requests", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--max-p95-ms", type=float, default=2000)
    parser.add_argument("--min-success-rate", type=float, default=0.99)
    parser.add_argument("--settle-seconds", type=float, default=10)
    parser.add_argument("--compose-file", action="append", default=[])
    parser.add_argument("--env-file")
    parser.add_argument("--project-name")
    parser.add_argument("--skip-faults", action="store_true")
    parser.add_argument("--allow-local-rehearsal", action="store_true")
    parser.add_argument(
        "--output-dir",
        default=f"artifacts/staging-qualification/{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
    )
    args = parser.parse_args()
    if not args.execute:
        raise SystemExit("Refusing to run staging load/fault gates without --execute")
    if not args.base_url:
        raise SystemExit("STAGING_BASE_URL or --base-url is required")
    if not args.allow_local_rehearsal and not args.base_url.startswith("https://"):
        raise SystemExit("A real qualification requires an HTTPS staging URL")
    required_secrets = [
        name
        for name in ("MCP_CLIENT_API_TOKEN", "MCP_TENANT_ID", "MCP_TENANT_TOKEN")
        if not os.getenv(name)
    ]
    if required_secrets:
        raise SystemExit(f"Missing staging secrets: {', '.join(required_secrets)}")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    compose = compose_prefix(args)
    started_at = utc_now()
    gates: list[dict[str, Any]] = []

    gates.append(
        run_gate(
            "compose-config",
            [*compose, "config", "--quiet"],
            output_dir=output_dir,
            env=env,
        )
    )
    container_compliance_command = [
        sys.executable,
        "scripts/mcp_container_compliance.py",
        "--output",
        str(output_dir / "mcp-container-compliance.json"),
    ]
    for path in args.compose_file:
        container_compliance_command.extend(["--compose-file", path])
    if args.env_file:
        container_compliance_command.extend(["--env-file", args.env_file])
    if args.project_name:
        container_compliance_command.extend(["--project-name", args.project_name])
    gates.append(
        run_gate(
            "mcp-container-compliance",
            container_compliance_command,
            output_dir=output_dir,
            env=env,
        )
    )
    gates.append(
        run_gate(
            "runtime-security-config",
            [
                *compose,
                "exec",
                "-T",
                "backend",
                "python",
                "-c",
                (
                    "from app.core.config import settings; "
                    "settings.validate_security_config(); "
                    f"assert settings.app_env == {args.environment!r}; "
                    "print('staging-config-verified')"
                ),
            ],
            output_dir=output_dir,
            env=env,
        )
    )
    gates.append(http_gate("readiness-before", f"{args.base_url.rstrip('/')}/health/readiness", output_dir=output_dir))
    gates.append(
        run_gate(
            "migration-head",
            [*compose, "exec", "-T", "backend", "python", "-m", "app.core.migrations", "check"],
            output_dir=output_dir,
            env=env,
        )
    )
    gates.append(
        run_gate(
            "kms-siem-s3",
            [
                *compose,
                "exec",
                "-T",
                "backend",
                "python",
                "-m",
                "app.services.security_audit_delivery_service",
                "verify",
            ],
            output_dir=output_dir,
            env=env,
        )
    )
    gates.append(
        run_gate(
            "mcp-runtime-compliance",
            [
                *compose,
                "exec",
                "-T",
                "worker",
                "python",
                "-c",
                (
                    "from app.services.mcp_compliance_service import scan_and_persist; "
                    "report=scan_and_persist(include_runtime=True); "
                    "assert report['status']=='compliant', report; "
                    "print(report['report_sha256'])"
                ),
            ],
            output_dir=output_dir,
            env=env,
        )
    )
    preflight_passed = all(gate["status"] == "passed" for gate in gates)
    if preflight_passed:
        load_gate = run_gate(
                "mcp-load",
                [
                    sys.executable,
                    "scripts/mcp_load_test.py",
                    "--base-url",
                    args.base_url,
                    "--server",
                    args.server,
                    "--tool",
                    args.tool,
                    "--requests",
                    str(max(1, args.requests)),
                    "--concurrency",
                    str(max(1, args.concurrency)),
                    "--max-p95-ms",
                    str(args.max_p95_ms),
                    "--min-success-rate",
                    str(args.min_success_rate),
                    "--output",
                    str(output_dir / "load-test.json"),
                ],
                output_dir=output_dir,
                env=env,
        )
        gates.append(load_gate)

        if args.skip_faults or load_gate["status"] != "passed":
            gates.append(
                {
                    "name": "fault-injection",
                    "status": "incomplete" if args.skip_faults else "skipped",
                    "duration_seconds": 0,
                }
            )
        else:
            scenarios = ("redis-restart", "postgres-restart", "worker-crash")
            for index, scenario in enumerate(scenarios):
                command = [
                    sys.executable,
                    "scripts/mcp_fault_injection.py",
                    scenario,
                    "--execute",
                    "--base-url",
                    args.base_url,
                    "--settle-seconds",
                    str(args.settle_seconds),
                    "--outage-timeout-seconds",
                    "30",
                    "--output",
                    str(output_dir / f"fault-{scenario}.json"),
                ]
                for path in args.compose_file:
                    command.extend(["--compose-file", path])
                if args.env_file:
                    command.extend(["--env-file", args.env_file])
                if args.project_name:
                    command.extend(["--project-name", args.project_name])
                fault_gate = run_gate(
                    f"fault-{scenario}",
                    command,
                    output_dir=output_dir,
                    env=env,
                )
                gates.append(fault_gate)
                if fault_gate["status"] != "passed":
                    gates.extend(
                        {
                            "name": f"fault-{remaining}",
                            "status": "skipped",
                            "duration_seconds": 0,
                        }
                        for remaining in scenarios[index + 1 :]
                    )
                    break
        gates.append(
            http_gate(
                "readiness-after",
                f"{args.base_url.rstrip('/')}/health/readiness",
                output_dir=output_dir,
            )
        )
    else:
        gates.extend(
            [
                {"name": "mcp-load", "status": "skipped", "duration_seconds": 0},
                {"name": "fault-injection", "status": "skipped", "duration_seconds": 0},
                {"name": "readiness-after", "status": "skipped", "duration_seconds": 0},
            ]
        )
    gates.append(
        run_gate(
            "compose-ps",
            [*compose, "ps", "--format", "json"],
            output_dir=output_dir,
            env=env,
        )
    )

    qualified = all(gate["status"] == "passed" for gate in gates)
    if args.allow_local_rehearsal:
        qualified = False
    performance = read_json_if_present(output_dir / "load-test.json")
    faults = {
        scenario: read_json_if_present(output_dir / f"fault-{scenario}.json")
        for scenario in ("redis-restart", "postgres-restart", "worker-crash")
        if (output_dir / f"fault-{scenario}.json").exists()
    }
    report = {
        "schema_version": 1,
        "decision": "qualified" if qualified else "hold",
        "environment": args.environment,
        "rehearsal": args.allow_local_rehearsal,
        "started_at": started_at,
        "finished_at": utc_now(),
        "base_url_sha256": hashlib.sha256(args.base_url.encode()).hexdigest(),
        "gates": gates,
        "performance": performance,
        "faults": faults,
        "notes": (
            []
            if not args.allow_local_rehearsal
            else ["Local/emulated rehearsal evidence cannot qualify a staging release."]
        ),
    }
    (output_dir / "qualification.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    write_markdown(report, output_dir)
    write_manifest(output_dir)
    print(json.dumps(report, indent=2, sort_keys=True))
    if not qualified:
        raise SystemExit(2)


def read_json_if_present(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


if __name__ == "__main__":
    main()

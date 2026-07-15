#!/usr/bin/env python3
import argparse
import json
import os
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx


def run(command: list[str], *, env: dict[str, str] | None = None, cwd: str | None = None) -> None:
    subprocess.run(command, check=True, env=env, cwd=cwd)


def wait_for_port(port: int, timeout_seconds: int = 30) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            time.sleep(1)
    raise RuntimeError(f"fixture on port {port} did not become ready")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the CodeMate production evidence pack")
    parser.add_argument("--keep-services", action="store_true")
    parser.add_argument("--output-dir", default="artifacts/production-evidence")
    args = parser.parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "DATABASE_URL": "postgresql+psycopg://codemate:codemate@127.0.0.1:5432/codemate",
        "REDIS_URL": "redis://127.0.0.1:6379/0",
        "RUN_MCP_E2E": "1",
    }
    started = datetime.now(timezone.utc)
    fixtures: list[subprocess.Popen] = []
    try:
        run(["docker", "compose", "up", "-d", "postgres", "redis"])
        run([".venv/bin/alembic", "-c", "alembic.ini", "upgrade", "head"], env=env, cwd="backend")
        fixtures = [
            subprocess.Popen(
                [".venv/bin/python", "-m", "tests.integration.mock_mcp_server"],
                cwd="backend",
                env=env,
            ),
            subprocess.Popen(
                [".venv/bin/python", "-m", "tests.integration.mock_identity_provider"],
                cwd="backend",
                env=env,
            ),
        ]
        wait_for_port(8765)
        wait_for_port(8766)
        if httpx.get("http://127.0.0.1:8766/docs", timeout=2).status_code != 200:
            raise RuntimeError("OAuth fixture health check failed")
        run(
            [
                "backend/.venv/bin/pytest",
                "backend/tests/integration/test_production_stack.py",
                "-q",
                f"--junitxml={output / 'integration-junit.xml'}",
            ],
            env=env,
        )
        report = {
            "status": "passed",
            "started_at": started.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "evidence": ["integration-junit.xml"],
        }
        (output / "summary.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        print(json.dumps(report, indent=2))
    finally:
        for fixture in fixtures:
            fixture.terminate()
            try:
                fixture.wait(timeout=5)
            except subprocess.TimeoutExpired:
                fixture.kill()
        if not args.keep_services:
            subprocess.run(
                ["docker", "compose", "stop", "postgres", "redis"],
                check=False,
            )


if __name__ == "__main__":
    main()

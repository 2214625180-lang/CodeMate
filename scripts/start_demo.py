#!/usr/bin/env python3
"""Start the local interview demo and print its presentation URLs."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Mapping
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BASE_COMPOSE_FILE = REPOSITORY_ROOT / "docker-compose.yml"
DEMO_COMPOSE_FILE = REPOSITORY_ROOT / "docker-compose.demo.yml"
RESULT_PREFIX = "CODEMATE_DEMO_RESULT="
SUPPORTED_REAL_PROVIDERS = {"openai", "deepseek", "openai-compatible"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch and seed the CodeMate interview demo.")
    parser.add_argument("--skip-build", action="store_true", help="Reuse existing images.")
    parser.add_argument(
        "--no-start-run",
        action="store_true",
        help="Seed the repository and benchmark without enqueueing a fix run.",
    )
    parser.add_argument(
        "--health-timeout-seconds",
        type=int,
        default=180,
        help="Maximum time to wait for the backend health endpoint.",
    )
    return parser.parse_args()


def read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def effective_environment() -> dict[str, str]:
    environment = read_dotenv(REPOSITORY_ROOT / ".env")
    environment.update(os.environ)
    return environment


def first_non_empty(environment: Mapping[str, str], *names: str) -> str | None:
    for name in names:
        value = environment.get(name, "").strip()
        if value:
            return value
    return None


def validate_real_llm(environment: Mapping[str, str]) -> tuple[str, str]:
    provider = environment.get("LLM_PROVIDER", "mock").strip().lower().replace("_", "-")
    if provider == "mock":
        raise RuntimeError(
            "Main demo blocked: LLM_PROVIDER=mock. Configure a real provider in .env; "
            "Mock remains available only for deterministic smoke tests."
        )
    if provider not in SUPPORTED_REAL_PROVIDERS:
        raise RuntimeError(f"Unsupported real LLM provider for the demo: {provider}")

    model = environment.get("LLM_MODEL", "").strip()
    if not model:
        raise RuntimeError("Main demo blocked: set an explicit LLM_MODEL in .env.")

    if provider == "openai":
        credential = first_non_empty(environment, "LLM_API_KEY", "OPENAI_API_KEY")
        required = "LLM_API_KEY or OPENAI_API_KEY"
    elif provider == "deepseek":
        credential = first_non_empty(environment, "LLM_API_KEY", "DEEPSEEK_API_KEY")
        required = "LLM_API_KEY or DEEPSEEK_API_KEY"
    else:
        credential = first_non_empty(environment, "LLM_API_KEY")
        required = "LLM_API_KEY"
        if not first_non_empty(environment, "LLM_BASE_URL"):
            raise RuntimeError("Main demo blocked: openai-compatible requires LLM_BASE_URL.")

    if not credential:
        raise RuntimeError(f"Main demo blocked: {required} is required for {provider}.")
    return provider, model


def validate_local_docker(environment: dict[str, str]) -> None:
    socket_path = Path(
        environment.get("CODEMATE_DOCKER_SOCKET", "/var/run/docker.sock")
    ).expanduser()
    if not socket_path.exists():
        raise RuntimeError(
            f"Docker socket not found at {socket_path}. Set CODEMATE_DOCKER_SOCKET to "
            "the local Docker/Colima socket used for the demo sandbox."
        )
    environment["CODEMATE_DOCKER_SOCKET"] = str(socket_path.resolve())
    completed = subprocess.run(
        ["docker", "info"],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"Docker is not ready: {detail}")


def compose_command(*arguments: str) -> list[str]:
    return [
        "docker",
        "compose",
        "-f",
        str(BASE_COMPOSE_FILE),
        "-f",
        str(DEMO_COMPOSE_FILE),
        "--profile",
        "demo",
        *arguments,
    ]


def run_checked(
    command: list[str],
    *,
    environment: Mapping[str, str],
    max_attempts: int = 1,
) -> None:
    for attempt in range(1, max_attempts + 1):
        completed = subprocess.run(
            command,
            cwd=REPOSITORY_ROOT,
            env=dict(environment),
            check=False,
        )
        if completed.returncode == 0:
            return
        if attempt < max_attempts:
            print(
                f"Command failed on attempt {attempt}/{max_attempts}; retrying in 3 seconds.",
                file=sys.stderr,
            )
            time.sleep(3)
            continue
        raise RuntimeError(
            f"Command failed with exit code {completed.returncode}: {' '.join(command)}"
        )


def wait_for_backend(*, port: int, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = "backend has not responded"
    health_url = f"http://localhost:{port}/health"
    direct_opener = build_opener(ProxyHandler({}))
    while time.monotonic() < deadline:
        try:
            with direct_opener.open(health_url, timeout=3) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if response.status == 200 and payload.get("status") == "ok":
                    return
                last_error = f"unexpected health response: {payload}"
        except (OSError, URLError, ValueError) as exc:
            last_error = str(exc)
        time.sleep(2)
    raise RuntimeError(f"Backend did not become healthy within {timeout_seconds}s: {last_error}")


def seed_demo(*, environment: Mapping[str, str], start_run: bool) -> dict:
    command = compose_command(
        "run",
        "--rm",
        "demo-seed",
        "python",
        "/demo/scripts/seed_demo.py",
        *(["--start-run"] if start_run else []),
    )
    process = subprocess.Popen(
        command,
        cwd=REPOSITORY_ROOT,
        env=dict(environment),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    result: dict | None = None
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="")
        if line.startswith(RESULT_PREFIX):
            result = json.loads(line.removeprefix(RESULT_PREFIX))
    return_code = process.wait()
    if return_code != 0:
        raise RuntimeError(f"Demo seeding failed with exit code {return_code}.")
    if result is None:
        raise RuntimeError("Demo seeding completed without a result payload.")
    return result


def print_result(result: Mapping[str, object]) -> None:
    print("\nCodeMate interview demo is ready.")
    print(f"  Real LLM:       {result['llm_provider']} / {result['llm_model']}")
    print(f"  Fixture commit: {result['fixture_commit_sha']}")
    print(f"  Repository:     {result['repository_url']}")
    print(f"  Agent timeline: {result['fix_url']}")
    print(f"  Benchmark:      {result['benchmark_url']}")
    print(f"  Targeted test:  {result['target_test_command']}")
    print(f"  Regression:     {result['regression_test_command']}")
    if result.get("embedding_provider") == "mock":
        print(
            "  Note: retrieval embeddings are deterministic Mock; planner and patch model are real."
        )


def main() -> int:
    args = parse_args()
    environment = effective_environment()
    provider, model = validate_real_llm(environment)
    validate_local_docker(environment)
    try:
        backend_port = int(environment.get("BACKEND_PORT", "8000"))
    except ValueError as exc:
        raise RuntimeError("BACKEND_PORT must be an integer.") from exc
    if not 1 <= backend_port <= 65535:
        raise RuntimeError("BACKEND_PORT must be between 1 and 65535.")
    print(f"Starting interview demo with real LLM {provider}/{model}.")
    print(
        "The local demo overlay grants only the worker access to the Docker socket for "
        "network-disabled test containers; do not use this overlay in production."
    )

    services = [
        "postgres",
        "redis",
        "qdrant",
        "migrate",
        "backend",
        "worker",
        "frontend",
    ]
    up_arguments = ["up", "-d"]
    if not args.skip_build:
        up_arguments.append("--build")
    up_arguments.extend(services)
    run_checked(
        compose_command(*up_arguments),
        environment=environment,
        max_attempts=2,
    )
    wait_for_backend(port=backend_port, timeout_seconds=args.health_timeout_seconds)
    if not args.skip_build:
        run_checked(
            compose_command("build", "demo-seed"),
            environment=environment,
            max_attempts=2,
        )

    result = seed_demo(environment=environment, start_run=not args.no_start_run)
    print_result(result)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"demo error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

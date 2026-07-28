import fnmatch
import json
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.core.config import settings


@dataclass(slots=True)
class TestResult:
    passed: bool
    exit_code: int
    stdout: str
    stderr: str
    command: str | None
    tests_ran: bool
    timed_out: bool = False
    runtime: str = "docker"
    skipped_reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "command": self.command,
            "tests_ran": self.tests_ran,
            "timed_out": self.timed_out,
            "runtime": self.runtime,
            "skipped_reason": self.skipped_reason,
        }


class SandboxService:
    IGNORED_NAMES = {
        "node_modules",
        "dist",
        "build",
        ".next",
        "coverage",
        ".env",
        ".env.local",
        ".env.development",
        ".env.production",
    }

    def create_workspace(self, *, run_id: str, source_path: str) -> Path:
        root = Path(settings.sandbox_workspace_dir)
        root.mkdir(parents=True, exist_ok=True)
        destination = root / run_id
        if destination.exists():
            shutil.rmtree(destination)

        shutil.copytree(source_path, destination, ignore=self._ignore)
        return destination

    def cleanup_workspace(self, workspace: Path) -> None:
        if workspace.exists() and workspace.is_dir():
            shutil.rmtree(workspace)

    def apply_patch(self, *, workspace: Path, diff: str) -> dict:
        if not diff.strip():
            return {"ok": False, "stdout": "", "stderr": "Empty patch"}

        patch_file = workspace / ".codemate.patch"
        patch_file.write_text(diff, encoding="utf-8")
        result = subprocess.run(
            ["git", "-C", str(workspace), "apply", str(patch_file)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        patch_file.unlink(missing_ok=True)
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode,
        }

    def git_diff(self, *, workspace: Path) -> str:
        result = subprocess.run(
            ["git", "-C", str(workspace), "diff", "--no-ext-diff"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return result.stdout if result.returncode == 0 else result.stderr

    def reset_workspace(self, *, workspace: Path) -> dict:
        reset = subprocess.run(
            ["git", "-C", str(workspace), "reset", "--hard"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        clean = subprocess.run(
            ["git", "-C", str(workspace), "clean", "-fd"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return {
            "ok": reset.returncode == 0 and clean.returncode == 0,
            "stdout": reset.stdout + clean.stdout,
            "stderr": reset.stderr + clean.stderr,
        }

    def detect_test_command(self, *, workspace: Path, requested_command: str | None) -> str | None:
        if requested_command:
            return requested_command.strip()

        package_json = workspace / "package.json"
        if package_json.exists():
            try:
                package_data = json.loads(package_json.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                package_data = {}
            if package_data.get("scripts", {}).get("test"):
                return "npm test"

        if any(workspace.rglob("*.py")):
            return "pytest"

        return None

    def run_tests(self, *, workspace: Path, command: str | None) -> TestResult:
        runtime = settings.sandbox_runtime.lower()
        if command is None:
            return TestResult(
                passed=True,
                exit_code=0,
                stdout="未检测到测试命令，未运行测试；仅完成 patch 应用校验。",
                stderr="",
                command=None,
                tests_ran=False,
                runtime=runtime,
            )

        if command not in settings.allowed_test_commands:
            return TestResult(
                passed=False,
                exit_code=126,
                stdout="",
                stderr=f"Test command is not allowed: {command}",
                command=command,
                tests_ran=False,
                runtime=runtime,
            )

        if runtime not in {"docker", "gvisor", "firecracker"}:
            return TestResult(
                passed=False,
                exit_code=126,
                stdout="",
                stderr=f"Unsupported sandbox runtime: {settings.sandbox_runtime}",
                command=command,
                tests_ran=False,
                runtime=runtime,
            )

        dependency_command = self._dependency_install_command(workspace=workspace, command=command)
        if (
            runtime in {"docker", "gvisor"}
            and settings.sandbox_network_disabled
            and dependency_command is not None
        ):
            return self._offline_dependency_skip(command=command, runtime=runtime)

        test_shell_command = self._test_shell_command(
            dependency_command=dependency_command,
            command=command,
        )
        image = self._image_for_command(command)
        if runtime == "firecracker":
            if settings.sandbox_execution_broker_url:
                return self._run_remote_docker_tests(
                    workspace=workspace,
                    command=command,
                    shell_command=test_shell_command,
                    image=image,
                    runtime=runtime,
                )
            return self._run_firecracker_tests(
                workspace=workspace,
                command=command,
                shell_command=test_shell_command,
                image=image,
            )

        return self._run_docker_tests(
            workspace=workspace,
            command=command,
            shell_command=test_shell_command,
            image=image,
            runtime=runtime,
        )

    def _run_docker_tests(
        self,
        *,
        workspace: Path,
        command: str,
        shell_command: str,
        image: str,
        runtime: str,
    ) -> TestResult:
        if settings.sandbox_execution_broker_url:
            return self._run_remote_docker_tests(
                workspace=workspace,
                command=command,
                shell_command=shell_command,
                image=image,
                runtime=runtime,
            )
        container_name = f"codemate-{uuid.uuid4().hex[:12]}"
        docker_command = [
            "docker",
            "run",
            "--rm",
            "--name",
            container_name,
            "--memory",
            "512m",
            "--cpus",
            "1.0",
            "-v",
            f"{workspace}:/workspace:rw",
            "-w",
            "/workspace",
        ]
        if runtime == "gvisor":
            docker_command.extend(["--runtime", settings.sandbox_gvisor_docker_runtime])
        if settings.sandbox_network_disabled:
            docker_command.extend(["--network", "none"])
        docker_command.extend([image, "sh", "-lc", shell_command])

        try:
            result = subprocess.run(
                docker_command,
                capture_output=True,
                text=True,
                timeout=settings.sandbox_timeout_seconds,
                check=False,
            )
            return TestResult(
                passed=result.returncode == 0,
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                command=command,
                tests_ran=True,
                runtime=runtime,
            )
        except subprocess.TimeoutExpired as exc:
            subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, check=False)
            return TestResult(
                passed=False,
                exit_code=124,
                stdout=exc.stdout or "",
                stderr=(exc.stderr or "") + "\nTest command timed out.",
                command=command,
                tests_ran=True,
                timed_out=True,
                runtime=runtime,
            )

    def _run_remote_docker_tests(
        self,
        *,
        workspace: Path,
        command: str,
        shell_command: str,
        image: str,
        runtime: str,
    ) -> TestResult:
        broker_url = (settings.sandbox_execution_broker_url or "").rstrip("/")
        token = (settings.sandbox_execution_broker_token or "").strip()
        root = Path(settings.sandbox_workspace_dir).resolve()
        try:
            relative_workspace = workspace.resolve().relative_to(root).as_posix()
        except ValueError:
            return TestResult(
                passed=False,
                exit_code=126,
                stdout="",
                stderr="Sandbox workspace is outside the broker volume",
                command=command,
                tests_ran=False,
                runtime=runtime,
            )
        try:
            response = httpx.post(
                f"{broker_url}/v1/tests",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "workspace": relative_workspace,
                    "command": command,
                    "shell_command": shell_command,
                    "image": image,
                    "runtime": runtime,
                    "timeout_seconds": settings.sandbox_timeout_seconds,
                },
                timeout=settings.sandbox_timeout_seconds + 10,
                follow_redirects=False,
                trust_env=False,
            )
            response.raise_for_status()
            return TestResult(**response.json())
        except Exception as exc:  # noqa: BLE001 - stable test result contract.
            return TestResult(
                passed=False,
                exit_code=126,
                stdout="",
                stderr=f"Sandbox execution broker failed: {exc}",
                command=command,
                tests_ran=False,
                runtime=runtime,
            )

    def _run_firecracker_tests(
        self,
        *,
        workspace: Path,
        command: str,
        shell_command: str,
        image: str,
    ) -> TestResult:
        template = settings.sandbox_firecracker_command_template
        if not template:
            return TestResult(
                passed=False,
                exit_code=126,
                stdout="",
                stderr=(
                    "SANDBOX_FIRECRACKER_COMMAND_TEMPLATE is required when "
                    "SANDBOX_RUNTIME=firecracker."
                ),
                command=command,
                tests_ran=False,
                runtime="firecracker",
            )

        try:
            argv_template = json.loads(template)
            if not isinstance(argv_template, list) or not argv_template:
                raise ValueError
            rendered_command = [
                str(item).format(
                    workspace=str(workspace),
                    image=image,
                    command=shell_command,
                    timeout=settings.sandbox_timeout_seconds,
                )
                for item in argv_template
            ]
        except (json.JSONDecodeError, ValueError):
            return TestResult(
                passed=False,
                exit_code=126,
                stdout="",
                stderr="SANDBOX_FIRECRACKER_COMMAND_TEMPLATE must be a JSON argv array.",
                command=command,
                tests_ran=False,
                runtime="firecracker",
            )
        try:
            result = subprocess.run(
                rendered_command,
                capture_output=True,
                text=True,
                timeout=settings.sandbox_timeout_seconds,
                check=False,
                shell=False,
            )
            return TestResult(
                passed=result.returncode == 0,
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                command=command,
                tests_ran=True,
                runtime="firecracker",
            )
        except subprocess.TimeoutExpired as exc:
            return TestResult(
                passed=False,
                exit_code=124,
                stdout=exc.stdout or "",
                stderr=(exc.stderr or "") + "\nTest command timed out.",
                command=command,
                tests_ran=True,
                timed_out=True,
                runtime="firecracker",
            )

    def list_files(self, *, workspace: Path, pattern: str | None = None) -> list[str]:
        files: list[str] = []
        for path in workspace.rglob("*"):
            if not path.is_file() or ".git" in path.parts:
                continue
            relative = path.relative_to(workspace).as_posix()
            if pattern and not fnmatch.fnmatch(relative, pattern):
                continue
            files.append(relative)
        return sorted(files)

    def read_file(
        self,
        *,
        workspace: Path,
        file_path: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> dict:
        root = workspace.resolve()
        absolute_path = (root / file_path).resolve()
        try:
            absolute_path.relative_to(root)
        except ValueError as exc:
            raise PermissionError("Invalid file path") from exc

        lines = absolute_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        safe_start = max(start_line or 1, 1)
        safe_end = min(end_line or len(lines), len(lines))
        content = "\n".join(lines[safe_start - 1 : safe_end])
        return {
            "file_path": file_path,
            "start_line": safe_start,
            "end_line": safe_end,
            "content": content,
        }

    def _image_for_command(self, command: str) -> str:
        if command.startswith(("npm", "pnpm", "yarn")):
            return settings.sandbox_node_image
        return settings.sandbox_python_image

    def _dependency_install_command(self, *, workspace: Path, command: str) -> str | None:
        if command.startswith(("npm", "pnpm", "yarn")):
            return self._node_dependency_install_command(workspace=workspace, command=command)
        if command in {"pytest", "python -m pytest"}:
            return self._python_dependency_install_command(workspace=workspace)
        return None

    def _node_dependency_install_command(self, *, workspace: Path, command: str) -> str | None:
        package_json = workspace / "package.json"
        if not package_json.exists():
            return None

        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

        if not self._has_node_dependencies(data):
            return None

        if command.startswith("pnpm"):
            install = "pnpm install --ignore-scripts"
            if (workspace / "pnpm-lock.yaml").exists():
                install = "pnpm install --frozen-lockfile --ignore-scripts"
            return f"corepack enable && {install}"

        if command.startswith("yarn"):
            install = "yarn install --ignore-scripts"
            if (workspace / "yarn.lock").exists():
                install = "yarn install --frozen-lockfile --ignore-scripts"
            return f"corepack enable && {install}"

        if (workspace / "package-lock.json").exists():
            return "npm ci --ignore-scripts"
        return "npm install --ignore-scripts"

    def _python_dependency_install_command(self, *, workspace: Path) -> str:
        commands = ["python -m pip install --upgrade pip"]
        requirements = workspace / "requirements.txt"
        pyproject = workspace / "pyproject.toml"

        if requirements.exists() and self._requirements_has_dependencies(requirements):
            commands.append("python -m pip install -r requirements.txt")
        if pyproject.exists():
            commands.append("python -m pip install -e .")
        commands.append("python -m pip install pytest")
        return " && ".join(commands)

    def _test_shell_command(self, *, dependency_command: str | None, command: str) -> str:
        if dependency_command is None:
            return command
        return f"{dependency_command} && {command}"

    def _offline_dependency_skip(self, *, command: str, runtime: str) -> TestResult:
        reason = (
            "Sandbox network is disabled and the test command requires dependency "
            "installation before it can run."
        )
        return TestResult(
            passed=True,
            exit_code=0,
            stdout=(
                "未运行测试：sandbox 当前禁用网络，且测试命令需要先安装依赖；"
                "仅完成 patch 应用校验。"
            ),
            stderr="",
            command=command,
            tests_ran=False,
            runtime=runtime,
            skipped_reason=reason,
        )

    def _has_node_dependencies(self, package_data: dict) -> bool:
        for key in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
            section = package_data.get(key)
            if isinstance(section, dict) and section:
                return True
        return False

    def _requirements_has_dependencies(self, path: Path) -> bool:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return False

        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                return True
        return False

    def _ignore(self, directory: str, names: list[str]) -> set[str]:
        ignored: set[str] = set()
        for name in names:
            if name in self.IGNORED_NAMES or name.startswith(".env"):
                ignored.add(name)
        return ignored

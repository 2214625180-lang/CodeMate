import json
import os
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.repository import Repository


class CIService:
    def __init__(self, db: Session):
        self.db = db

    def inspect(self, repo_id: str) -> dict:
        repository = self._get_repository(repo_id)
        root = self._workspace(repository)
        generated = self._generate(root)
        return {"repo_id": repo_id, **generated, "applied_path": None}

    def write_workflow(self, repo_id: str) -> dict:
        repository = self._get_repository(repo_id)
        root = self._workspace(repository)
        generated = self._generate(root)
        workflow_path = root / generated["workflow_path"]
        workflow_path.parent.mkdir(parents=True, exist_ok=True)
        workflow_path.write_text(generated["workflow_yaml"], encoding="utf-8")
        return {
            "repo_id": repo_id,
            **generated,
            "applied_path": generated["workflow_path"],
        }

    def _get_repository(self, repo_id: str) -> Repository:
        repository = self.db.get(Repository, repo_id)
        if repository is None:
            raise FileNotFoundError("Repository not found")
        return repository

    def _workspace(self, repository: Repository) -> Path:
        if repository.local_path is None:
            raise FileNotFoundError("Repository workspace is not available")
        root = Path(repository.local_path).resolve()
        if not root.exists():
            raise FileNotFoundError("Repository workspace is not available")
        return root

    def _generate(self, root: Path) -> dict:
        detected_configs = self._detected_configs(root)
        ecosystem = self._ecosystem(root)
        package_manager = self._package_manager(root)
        test_commands = self._test_commands(root, ecosystem, package_manager)
        workflow_path = f".github/workflows/{settings.ci_workflow_filename}"
        return {
            "detected_configs": detected_configs,
            "ecosystem": ecosystem,
            "package_manager": package_manager,
            "test_commands": test_commands,
            "workflow_path": workflow_path,
            "workflow_yaml": self._workflow_yaml(ecosystem, package_manager, test_commands),
        }

    def _detected_configs(self, root: Path) -> list[str]:
        configs = []
        workflow_dir = root / ".github" / "workflows"
        if workflow_dir.exists():
            configs.extend(
                path.relative_to(root).as_posix()
                for path in sorted(workflow_dir.glob("*.y*ml"))
                if path.is_file()
            )
        for path in [".gitlab-ci.yml", "azure-pipelines.yml", ".circleci/config.yml"]:
            if (root / path).exists():
                configs.append(path)
        return configs

    def _ecosystem(self, root: Path) -> list[str]:
        ecosystem = []
        if (root / "package.json").exists():
            ecosystem.append("node")
        if (
            (root / "pyproject.toml").exists()
            or (root / "requirements.txt").exists()
            or self._has_python_files(root)
        ):
            ecosystem.append("python")
        if (root / "Dockerfile").exists() or (root / "docker-compose.yml").exists():
            ecosystem.append("docker")
        return ecosystem or ["generic"]

    def _package_manager(self, root: Path) -> str | None:
        if (root / "pnpm-lock.yaml").exists():
            return "pnpm"
        if (root / "yarn.lock").exists():
            return "yarn"
        if (root / "package-lock.json").exists() or (root / "package.json").exists():
            return "npm"
        return None

    def _has_python_files(self, root: Path) -> bool:
        ignored_dirs = {
            ".git",
            ".hg",
            ".mypy_cache",
            ".next",
            ".pytest_cache",
            ".ruff_cache",
            ".tox",
            ".venv",
            "__pycache__",
            "build",
            "coverage",
            "dist",
            "node_modules",
            "venv",
        }
        for _current_root, dirnames, filenames in os.walk(root):
            dirnames[:] = [dirname for dirname in dirnames if dirname not in ignored_dirs]
            if any(filename.endswith(".py") for filename in filenames):
                return True
        return False

    def _test_commands(self, root: Path, ecosystem: list[str], package_manager: str | None) -> list[str]:
        commands = []
        if "node" in ecosystem:
            script = self._node_test_script(root, package_manager or "npm")
            if script:
                commands.append(script)
        if "python" in ecosystem:
            commands.append("python -m pytest")
        return commands or ["echo \"No tests configured\""]

    def _node_test_script(self, root: Path, package_manager: str) -> str | None:
        package_json = root / "package.json"
        if not package_json.exists():
            return None
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        scripts = data.get("scripts")
        if not isinstance(scripts, dict) or "test" not in scripts:
            return None
        if package_manager == "pnpm":
            return "pnpm test"
        if package_manager == "yarn":
            return "yarn test"
        return "npm test"

    def _workflow_yaml(
        self,
        ecosystem: list[str],
        package_manager: str | None,
        test_commands: list[str],
    ) -> str:
        lines = [
            "name: CodeMate CI",
            "",
            "on:",
            "  pull_request:",
            "  push:",
            "    branches: [main]",
            "",
            "jobs:",
            "  test:",
            "    runs-on: ubuntu-latest",
            "    steps:",
            "      - uses: actions/checkout@v4",
        ]
        if "node" in ecosystem:
            lines.extend(self._node_steps(package_manager or "npm"))
        if "python" in ecosystem:
            lines.extend(self._python_steps())
        for command in test_commands:
            lines.extend(["      - name: Run tests", f"        run: {command}"])
        return "\n".join(lines) + "\n"

    def _node_steps(self, package_manager: str) -> list[str]:
        install = {
            "pnpm": "pnpm install --frozen-lockfile",
            "yarn": "yarn install --frozen-lockfile",
            "npm": "npm install",
        }.get(package_manager, "npm install")
        steps = [
            "      - uses: actions/setup-node@v4",
            "        with:",
            "          node-version: '20'",
        ]
        if package_manager == "pnpm":
            steps[0:0] = [
                "      - uses: pnpm/action-setup@v4",
                "        with:",
                "          version: 9",
            ]
        steps.extend(["      - name: Install Node dependencies", f"        run: {install}"])
        return steps

    def _python_steps(self) -> list[str]:
        return [
            "      - uses: actions/setup-python@v5",
            "        with:",
            "          python-version: '3.11'",
            "      - name: Install Python dependencies",
            "        run: |",
            "          python -m pip install --upgrade pip",
            "          if [ -f requirements.txt ]; then pip install -r requirements.txt; fi",
            "          if [ -f pyproject.toml ]; then pip install -e .; fi",
            "          pip install pytest",
        ]

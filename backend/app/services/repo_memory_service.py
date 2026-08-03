import json
import re
import tomllib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.code_chunk import CodeChunk
from app.models.code_file import CodeFile
from app.models.repository import Repository


class RepoMemoryService:
    KEY_FILE_NAMES = {
        "package.json",
        "pyproject.toml",
        "requirements.txt",
        "Dockerfile",
        "docker-compose.yml",
        "next.config.mjs",
        "vite.config.ts",
        "tsconfig.json",
        "tailwind.config.ts",
    }

    def __init__(self, db: Session):
        self.db = db

    def read(self, repo_id: str) -> dict:
        repository = self._get_repository(repo_id)
        return self._response(repository)

    def refresh(self, repo_id: str) -> dict:
        repository = self._get_repository(repo_id)
        code_files = self._files(repo_id)
        chunks = self._chunks(repo_id)
        memory_data = self._build_memory_data(repository, code_files, chunks)

        repository.memory_summary = self._build_summary(repository, memory_data)
        repository.memory_data = memory_data
        repository.memory_updated_at = datetime.now(timezone.utc)
        repository.updated_at = datetime.now(timezone.utc)
        self.db.add(repository)
        self.db.commit()
        self.db.refresh(repository)
        return self._response(repository)

    def _get_repository(self, repo_id: str) -> Repository:
        repository = self.db.get(Repository, repo_id)
        if repository is None:
            raise FileNotFoundError("Repository not found")
        return repository

    def _files(self, repo_id: str) -> list[CodeFile]:
        return list(
            self.db.execute(
                select(CodeFile)
                .where(CodeFile.repo_id == repo_id)
                .order_by(CodeFile.file_path.asc())
            )
            .scalars()
            .all()
        )

    def _chunks(self, repo_id: str) -> list[CodeChunk]:
        return list(
            self.db.execute(
                select(CodeChunk)
                .where(CodeChunk.repo_id == repo_id)
                .where(CodeChunk.symbol_name.is_not(None))
                .order_by(CodeChunk.file_path.asc(), CodeChunk.start_line.asc())
                .limit(settings.repo_memory_max_symbols)
            )
            .scalars()
            .all()
        )

    def _build_memory_data(
        self,
        repository: Repository,
        code_files: list[CodeFile],
        chunks: list[CodeChunk],
    ) -> dict:
        modules = self._module_summary(code_files)
        key_files = self._key_files(code_files)
        dependencies = self._dependency_summary(repository)
        symbols = [
            {
                "name": chunk.symbol_name,
                "type": chunk.symbol_type,
                "path": chunk.file_path,
                "lines": [chunk.start_line, chunk.end_line],
            }
            for chunk in chunks
            if chunk.symbol_name
        ]
        return {
            "repository": {
                "name": repository.name,
                "url": repository.repo_url,
                "last_commit_hash": repository.last_commit_hash,
            },
            "languages": repository.language_summary or {},
            "modules": modules,
            "key_files": key_files,
            "dependencies": dependencies,
            "symbols": symbols,
        }

    def _build_summary(self, repository: Repository, memory_data: dict) -> str:
        languages = ", ".join(
            f"{language} {count}"
            for language, count in sorted(
                (repository.language_summary or {}).items(),
                key=lambda item: item[1],
                reverse=True,
            )[:4]
        )
        modules = ", ".join(module["path"] for module in memory_data["modules"][:5])
        deps = memory_data["dependencies"]
        frameworks = ", ".join(deps.get("frameworks", [])[:6]) or "no framework detected"
        return (
            f"{repository.name} contains {repository.file_count} indexed files and "
            f"{repository.chunk_count} semantic chunks. Languages: {languages or 'n/a'}. "
            f"Main modules: {modules or 'n/a'}. Detected stack: {frameworks}."
        )

    def _module_summary(self, code_files: list[CodeFile]) -> list[dict]:
        counter: Counter[str] = Counter()
        for code_file in code_files:
            parts = code_file.file_path.split("/")
            module = parts[0] if len(parts) == 1 else "/".join(parts[:2])
            counter[module] += 1
        return [
            {"path": path, "file_count": count}
            for path, count in counter.most_common(settings.repo_memory_max_files)
        ]

    def _key_files(self, code_files: list[CodeFile]) -> list[dict]:
        selected = []
        for code_file in code_files:
            path = Path(code_file.file_path)
            if path.name in self.KEY_FILE_NAMES or path.parts[:2] == (".github", "workflows"):
                selected.append(
                    {
                        "path": code_file.file_path,
                        "language": code_file.language,
                        "lines": code_file.line_count,
                        "size_bytes": code_file.size_bytes,
                    }
                )
        return selected[: settings.repo_memory_max_files]

    def _dependency_summary(self, repository: Repository) -> dict:
        if repository.local_path is None:
            return {"frameworks": [], "dependencies": []}

        root = Path(repository.local_path)
        dependencies: set[str] = set()
        package_json = root / "package.json"
        if package_json.exists():
            dependencies.update(self._package_json_dependencies(package_json))

        pyproject = root / "pyproject.toml"
        if pyproject.exists():
            dependencies.update(self._pyproject_dependencies(pyproject))

        requirements = root / "requirements.txt"
        if requirements.exists():
            dependencies.update(self._requirements_dependencies(requirements))

        return {
            "frameworks": self._frameworks(dependencies),
            "dependencies": sorted(dependencies)[:40],
        }

    def _package_json_dependencies(self, path: Path) -> set[str]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return set()
        dependencies: set[str] = set()
        for key in ("dependencies", "devDependencies"):
            section = data.get(key)
            if isinstance(section, dict):
                dependencies.update(section.keys())
        return dependencies

    def _pyproject_dependencies(self, path: Path) -> set[str]:
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError):
            return set()
        dependencies: set[str] = set()
        project_deps = data.get("project", {}).get("dependencies", [])
        if isinstance(project_deps, list):
            dependencies.update(self._dependency_name(dep) for dep in project_deps)
        return {dependency.strip() for dependency in dependencies if dependency.strip()}

    def _requirements_dependencies(self, path: Path) -> set[str]:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return set()
        dependencies = set()
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            dependencies.add(self._dependency_name(stripped))
        return dependencies

    def _dependency_name(self, dependency: str) -> str:
        return re.split(r"\s*(?:\[|==|>=|<=|~=|!=|>|<|=)", dependency, maxsplit=1)[0].strip()

    def _frameworks(self, dependencies: set[str]) -> list[str]:
        known = {
            "next",
            "react",
            "vue",
            "nuxt",
            "vite",
            "fastapi",
            "django",
            "flask",
            "pytest",
            "sqlalchemy",
            "langgraph",
        }
        return sorted(dependency for dependency in dependencies if dependency.lower() in known)

    def _response(self, repository: Repository) -> dict:
        return {
            "repo_id": repository.id,
            "summary": repository.memory_summary,
            "data": repository.memory_data or {},
            "updated_at": repository.memory_updated_at,
        }

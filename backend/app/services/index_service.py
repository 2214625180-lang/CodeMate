import hashlib
import os
import shutil
import subprocess
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.embeddings.code_text import build_chunk_embedding_text
from app.embeddings.factory import get_embedding_provider
from app.indexing.chunkers.base import ParsedFile
from app.indexing.chunkers import get_chunker
from app.indexing.filters import detect_language, iter_source_files
from app.models.code_chunk import CodeChunk
from app.models.code_file import CodeFile
from app.models.repository import Repository
from app.services.repo_memory_service import RepoMemoryService
from app.services.repo_service import validate_git_url
from app.vectorstore.qdrant_store import QdrantVectorStore, make_chunk_point


@dataclass(slots=True)
class ScannedCodeFile:
    path: Path
    relative_path: str
    language: str
    raw: bytes
    content: str
    content_hash: str
    parsed_file: ParsedFile


class IndexService:
    """Keep checkout, relational metadata and Qdrant vectors logically consistent.

    These stores cannot share one transaction.  Indexing therefore builds a
    staging checkout, tracks newly written vector IDs and uses compensating
    cleanup/restore steps when any later operation fails.
    """

    def __init__(self, db: Session):
        self.db = db
        self.embedding_provider = get_embedding_provider()
        self.vector_store = QdrantVectorStore()

    def index_repository(self, repo_id: str, *, full: bool = False) -> None:
        repository = self.db.get(Repository, repo_id)
        if repository is None:
            return

        try:
            if full or repository.local_path is None or not Path(repository.local_path).exists():
                self._index_full(repository)
            else:
                self._index_incremental(repository)
        except Exception as exc:  # noqa: BLE001 - preserve safe failure reason for UI.
            self.db.rollback()
            failed_repo = self.db.get(Repository, repo_id)
            if failed_repo is not None:
                self._update_repository(
                    failed_repo,
                    status="failed",
                    error_message=self._safe_index_error_message(exc),
                )

    def _index_full(self, repository: Repository) -> None:
        target_workspace = self._workspace_path(repository.id)
        staging_workspace = self._prepare_staging_workspace(repository.id)
        backup_workspace: Path | None = None
        workspace_replaced = False
        new_point_ids: list[str] = []

        self._update_repository(repository, status="cloning", error_message=None)
        try:
            self._clone_repository(repository.repo_url, staging_workspace)

            commit_hash = self._read_commit_hash(staging_workspace)
            self._update_repository(repository, status="parsing")

            scanned_files = self._scan_source_files(staging_workspace)
            language_summary = Counter(file.language for file in scanned_files)
            chunk_count = self._scanned_chunk_count(scanned_files)
            self._update_repository(repository, status="embedding")

            self.vector_store.ensure_collection(self.embedding_provider.dimension)
            # Keep old vector IDs until the database commit succeeds. If writing
            # the replacement fails, only the newly created points are removed.
            old_point_ids = self._chunk_point_ids(repository.id)
            self.db.execute(delete(CodeChunk).where(CodeChunk.repo_id == repository.id))
            self.db.execute(delete(CodeFile).where(CodeFile.repo_id == repository.id))
            self.db.flush()

            _, code_chunks = self._persist_scanned_files(repository.id, scanned_files)
            new_point_ids = self._write_embeddings(repository.id, code_chunks)
            backup_workspace = self._replace_workspace(
                staging=staging_workspace,
                target=target_workspace,
            )
            workspace_replaced = True
            self._set_repository_values(
                repository,
                status="indexed",
                local_path=str(target_workspace),
                last_commit_hash=commit_hash,
                file_count=len(scanned_files),
                chunk_count=chunk_count,
                language_summary=dict(language_summary),
                indexed_at=datetime.now(timezone.utc),
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            self._delete_vector_points_best_effort(new_point_ids)
            if workspace_replaced:
                self._restore_workspace(target=target_workspace, backup=backup_workspace)
            else:
                self._remove_path_best_effort(staging_workspace)
            raise

        # Retire old external state only after the new DB view is committed.
        self._remove_path_best_effort(backup_workspace)
        self._delete_vector_points_best_effort(old_point_ids)
        self._refresh_memory(repository.id)

    def _index_incremental(self, repository: Repository) -> None:
        target_workspace = Path(repository.local_path or "").resolve()
        staging_workspace = self._prepare_staging_workspace(repository.id)
        backup_workspace: Path | None = None
        workspace_replaced = False
        new_point_ids: list[str] = []

        self._update_repository(repository, status="cloning", error_message=None)
        try:
            # Keep symlinks as symlinks. Dereferencing an untrusted checkout here
            # could copy a host file into the next index even though the scanner
            # later skips symlink entries.
            shutil.copytree(target_workspace, staging_workspace, symlinks=True)
            self._update_workspace(staging_workspace)

            commit_hash = self._read_commit_hash(staging_workspace)
            self._update_repository(repository, status="parsing")

            self.vector_store.ensure_collection(self.embedding_provider.dimension)
            scanned_files = self._scan_source_files(staging_workspace)
            scanned_by_path = {file.relative_path: file for file in scanned_files}
            language_summary = Counter(file.language for file in scanned_files)
            existing_files = self._existing_files(repository.id)

            deleted_paths = sorted(set(existing_files) - set(scanned_by_path))
            changed_files = [
                scanned
                for path, scanned in scanned_by_path.items()
                if (
                    path not in existing_files
                    or existing_files[path].content_hash != scanned.content_hash
                )
            ]
            changed_paths = [file.relative_path for file in changed_files]

            self._update_repository(repository, status="embedding")

            replaced_paths = [*deleted_paths, *changed_paths]
            old_point_ids = self._chunk_point_ids(repository.id, replaced_paths)
            self._delete_indexed_files_from_db(repository.id, replaced_paths)

            _, new_chunks = self._persist_scanned_files(repository.id, changed_files)
            new_point_ids = self._write_embeddings(repository.id, new_chunks)
            backup_workspace = self._replace_workspace(
                staging=staging_workspace,
                target=target_workspace,
            )
            workspace_replaced = True
            self._set_repository_values(
                repository,
                status="indexed",
                local_path=str(target_workspace),
                last_commit_hash=commit_hash,
                file_count=len(scanned_files),
                chunk_count=self._current_chunk_count(repository.id),
                language_summary=dict(language_summary),
                indexed_at=datetime.now(timezone.utc),
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            self._delete_vector_points_best_effort(new_point_ids)
            if workspace_replaced:
                self._restore_workspace(target=target_workspace, backup=backup_workspace)
            else:
                self._remove_path_best_effort(staging_workspace)
            raise

        self._remove_path_best_effort(backup_workspace)
        self._delete_vector_points_best_effort(old_point_ids)
        self._refresh_memory(repository.id)

    def _workspace_path(self, repo_id: str) -> Path:
        settings.workspace_path.mkdir(parents=True, exist_ok=True)
        return settings.workspace_path / repo_id

    def _prepare_staging_workspace(self, repo_id: str) -> Path:
        staging = self._workspace_path(f"{repo_id}.staging")
        self._remove_path(staging)
        return staging

    def _replace_workspace(self, *, staging: Path, target: Path) -> Path | None:
        backup = target.with_name(f"{target.name}.backup")
        self._remove_path(backup)
        target.parent.mkdir(parents=True, exist_ok=True)

        if target.exists():
            target.rename(backup)
        try:
            staging.rename(target)
        except Exception:
            if backup.exists():
                backup.rename(target)
            raise

        return backup if backup.exists() else None

    def _restore_workspace(self, *, target: Path, backup: Path | None) -> None:
        self._remove_path(target)
        if backup is not None and backup.exists():
            backup.rename(target)

    def _remove_path(self, path: Path | None) -> None:
        if path is None or not path.exists():
            return
        if path.is_dir():
            shutil.rmtree(path)
            return
        path.unlink()

    def _remove_path_best_effort(self, path: Path | None) -> None:
        try:
            self._remove_path(path)
        except Exception:
            pass

    def _clone_repository(self, repo_url: str, workspace: Path) -> None:
        # Resolve immediately before the transport starts as a second DNS
        # rebinding check. The managed deployment must additionally apply its
        # egress policy at the network boundary.
        validated = validate_git_url(repo_url, resolve_host=True)
        try:
            result = subprocess.run(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "--single-branch",
                    "--filter=blob:none",
                    "--no-checkout",
                    "--no-recurse-submodules",
                    "--config",
                    "protocol.file.allow=never",
                    "--",
                    validated.normalized_url,
                    str(workspace),
                ],
                capture_output=True,
                text=True,
                timeout=settings.clone_timeout_seconds,
                check=False,
                env=self._safe_git_environment(),
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Repository clone timed out.") from exc
        if result.returncode != 0:
            raise RuntimeError("Repository clone failed. Check repository access and URL.")

        self._assert_checkout_budget(workspace)
        checkout = self._run_git(workspace, ["checkout", "--force"])
        if checkout.returncode != 0:
            raise RuntimeError("Repository checkout failed.")
        self._assert_workspace_budget(workspace)

    def _update_workspace(self, workspace: Path) -> None:
        origin = self._run_git(workspace, ["remote", "get-url", "origin"])
        if origin.returncode != 0:
            raise RuntimeError("Repository remote could not be verified.")
        validate_git_url(origin.stdout.strip(), resolve_host=True)
        fetch = self._run_git(workspace, ["fetch", "--all", "--prune", "--filter=blob:none"])
        if fetch.returncode != 0:
            raise RuntimeError("Repository fetch failed.")

        self._assert_checkout_budget(workspace, revision="FETCH_HEAD")
        merge = self._run_git(workspace, ["merge", "--ff-only", "FETCH_HEAD"])
        if merge.returncode != 0:
            raise RuntimeError("Repository update failed.")
        self._assert_workspace_budget(workspace)

    def _run_git(self, workspace: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                ["git", "-C", str(workspace), "-c", "protocol.file.allow=never", *args],
                capture_output=True,
                text=True,
                timeout=settings.clone_timeout_seconds,
                check=False,
                env=self._safe_git_environment(),
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Repository Git operation timed out.") from exc

    def _read_commit_hash(self, workspace: Path) -> str | None:
        result = subprocess.run(
            ["git", "-C", str(workspace), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()

    def _scan_codebase(
        self,
        repo_id: str,
        workspace: Path,
    ) -> tuple[list[CodeFile], list[CodeChunk]]:
        return self._persist_scanned_files(repo_id, self._scan_source_files(workspace))

    def _scan_source_files(self, workspace: Path) -> list[ScannedCodeFile]:
        root = workspace.resolve()
        scanned_files: list[ScannedCodeFile] = []
        for path in iter_source_files(root):
            if path.is_symlink():
                continue
            resolved_path = path.resolve()
            try:
                resolved_path.relative_to(root)
            except ValueError:
                continue
            language = detect_language(path)
            if language is None:
                continue

            raw = resolved_path.read_bytes()
            content = raw.decode("utf-8", errors="ignore")
            relative_path = resolved_path.relative_to(root).as_posix()
            parsed_file = get_chunker(language, resolved_path).parse(resolved_path, content)
            scanned_files.append(
                ScannedCodeFile(
                    path=resolved_path,
                    relative_path=relative_path,
                    language=language,
                    raw=raw,
                    content=content,
                    content_hash=hashlib.sha256(raw).hexdigest(),
                    parsed_file=parsed_file,
                )
            )
        return scanned_files

    def _assert_checkout_budget(self, workspace: Path, *, revision: str = "HEAD") -> None:
        tree = self._run_git(workspace, ["ls-tree", "-r", "-l", "-z", revision])
        if tree.returncode != 0:
            raise RuntimeError("Repository contents could not be inspected.")

        file_count = 0
        total_bytes = 0
        for record in tree.stdout.split("\0"):
            if not record:
                continue
            metadata, separator, _path = record.partition("\t")
            if not separator:
                raise RuntimeError("Repository contents could not be inspected.")
            parts = metadata.split()
            if len(parts) != 4:
                raise RuntimeError("Repository contents could not be inspected.")
            mode, object_type, _object_id, size = parts
            if mode == "160000" or object_type == "commit":
                raise RuntimeError("Repositories containing submodules are not supported.")
            if object_type != "blob":
                continue
            try:
                object_size = int(size)
            except ValueError as exc:
                raise RuntimeError("Repository contents could not be inspected.") from exc
            file_count += 1
            total_bytes += object_size
            if (
                file_count > settings.repository_max_clone_files
                or total_bytes > settings.repository_max_clone_bytes
            ):
                raise RuntimeError("Repository exceeds the configured clone budget.")

    def _assert_workspace_budget(self, workspace: Path) -> None:
        file_count = 0
        total_bytes = 0
        for root, _directories, filenames in os.walk(workspace, followlinks=False):
            for filename in filenames:
                path = Path(root, filename)
                try:
                    stat = path.lstat()
                except OSError as exc:
                    raise RuntimeError("Repository workspace could not be inspected.") from exc
                if path.is_symlink():
                    continue
                file_count += 1
                total_bytes += stat.st_size
                if (
                    file_count > settings.repository_max_clone_files
                    or total_bytes > settings.repository_max_clone_bytes
                ):
                    raise RuntimeError("Repository exceeds the configured clone budget.")

    @staticmethod
    def _safe_git_environment() -> dict[str, str]:
        allowed_protocols = "https:ssh"
        if settings.repository_allow_http:
            allowed_protocols = f"http:{allowed_protocols}"
        return {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LANG": "C.UTF-8",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": os.devnull,
            "GIT_LFS_SKIP_SMUDGE": "1",
            "GIT_ALLOW_PROTOCOL": allowed_protocols,
            "GIT_SSH_COMMAND": (
                "ssh -oBatchMode=yes -oStrictHostKeyChecking=yes "
                "-oProxyCommand=none"
            ),
        }

    def _persist_scanned_files(
        self,
        repo_id: str,
        scanned_files: list[ScannedCodeFile],
    ) -> tuple[list[CodeFile], list[CodeChunk]]:
        code_files: list[CodeFile] = []
        code_chunks: list[CodeChunk] = []
        for scanned in scanned_files:
            code_file = CodeFile(
                repo_id=repo_id,
                file_path=scanned.relative_path,
                language=scanned.language,
                content_hash=scanned.content_hash,
                line_count=self._count_lines(scanned.content),
                size_bytes=len(scanned.raw),
                imports=scanned.parsed_file.imports,
                exports=scanned.parsed_file.exports,
            )
            self.db.add(code_file)
            self.db.flush()
            code_files.append(code_file)

            for chunk_data in scanned.parsed_file.chunks:
                code_chunk = CodeChunk(
                    repo_id=repo_id,
                    file_id=code_file.id,
                    file_path=scanned.relative_path,
                    language=scanned.language,
                    symbol_name=chunk_data.symbol_name,
                    symbol_type=chunk_data.symbol_type,
                    start_line=chunk_data.start_line,
                    end_line=chunk_data.end_line,
                    content=chunk_data.content,
                    content_hash=chunk_data.content_hash,
                    imports=chunk_data.imports,
                    exports=chunk_data.exports,
                )
                self.db.add(code_chunk)
                code_chunks.append(code_chunk)

        self.db.flush()
        return code_files, code_chunks

    def _existing_files(self, repo_id: str) -> dict[str, CodeFile]:
        statement = select(CodeFile).where(CodeFile.repo_id == repo_id)
        return {
            code_file.file_path: code_file
            for code_file in self.db.execute(statement).scalars().all()
        }

    def _chunk_point_ids(self, repo_id: str, file_paths: list[str] | None = None) -> list[str]:
        if file_paths is not None and not file_paths:
            return []

        statement = select(CodeChunk.id, CodeChunk.embedding_id).where(CodeChunk.repo_id == repo_id)
        if file_paths is not None:
            statement = statement.where(CodeChunk.file_path.in_(file_paths))

        rows = self.db.execute(statement).all()
        return [embedding_id or chunk_id for chunk_id, embedding_id in rows]

    def _delete_indexed_files_from_db(self, repo_id: str, file_paths: list[str]) -> None:
        if not file_paths:
            return

        self.db.execute(
            delete(CodeChunk)
            .where(CodeChunk.repo_id == repo_id)
            .where(CodeChunk.file_path.in_(file_paths))
        )
        self.db.execute(
            delete(CodeFile)
            .where(CodeFile.repo_id == repo_id)
            .where(CodeFile.file_path.in_(file_paths))
        )
        self.db.flush()

    def _current_chunk_count(self, repo_id: str) -> int:
        return len(
            self.db.execute(
                select(CodeChunk.id).where(CodeChunk.repo_id == repo_id)
            ).scalars().all()
        )

    def _scanned_chunk_count(self, scanned_files: list[ScannedCodeFile]) -> int:
        return sum(len(file.parsed_file.chunks) for file in scanned_files)

    def _refresh_memory(self, repo_id: str) -> None:
        try:
            RepoMemoryService(self.db).refresh(repo_id)
        except Exception:  # noqa: BLE001 - memory should not fail a successful index.
            self.db.rollback()

    def _write_embeddings(self, repo_id: str, chunks: list[CodeChunk]) -> list[str]:
        if not chunks:
            return []

        texts = [build_chunk_embedding_text(chunk) for chunk in chunks]
        vectors = self.embedding_provider.embed_texts(texts)
        points = []
        point_ids = []

        for chunk, vector in zip(chunks, vectors, strict=True):
            chunk.embedding_id = chunk.id
            point_ids.append(chunk.id)
            points.append(
                make_chunk_point(
                    point_id=chunk.id,
                    vector=vector,
                    repo_id=repo_id,
                    chunk_id=chunk.id,
                    file_path=chunk.file_path,
                    language=chunk.language,
                    symbol_name=chunk.symbol_name,
                    symbol_type=chunk.symbol_type,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    content_hash=chunk.content_hash,
                )
            )

        self.db.add_all(chunks)
        self.db.flush()

        upserted_point_ids: list[str] = []
        for start in range(0, len(points), 64):
            batch = points[start : start + 64]
            batch_point_ids = point_ids[start : start + 64]
            try:
                self.vector_store.upsert_chunks(batch)
            except Exception:
                self._delete_vector_points_best_effort([*upserted_point_ids, *batch_point_ids])
                raise
            upserted_point_ids.extend(batch_point_ids)

        return point_ids

    def _delete_vector_points_best_effort(self, point_ids: list[str]) -> None:
        if not point_ids:
            return
        try:
            self.vector_store.delete_points(point_ids)
        except Exception:
            pass

    @staticmethod
    def _safe_index_error_message(exc: Exception) -> str:
        """Expose only errors authored by repository guardrails.

        Git servers and embedding providers can include remote URLs, request
        headers, or credentials in their exception text. Those diagnostics are
        intentionally not stored on a user-visible Repository row.
        """
        message = str(exc).strip()
        if message.startswith("Repository "):
            return message
        return "Repository indexing failed. Check repository contents and configuration."

    @staticmethod
    def _count_lines(content: str) -> int:
        if not content:
            return 0
        return content.count("\n") + (0 if content.endswith("\n") else 1)

    def _set_repository_values(self, repository: Repository, **values) -> None:
        for key, value in values.items():
            setattr(repository, key, value)
        repository.updated_at = datetime.now(timezone.utc)
        self.db.add(repository)

    def _update_repository(self, repository: Repository, **values) -> None:
        self._set_repository_values(repository, **values)
        self.db.commit()
        self.db.refresh(repository)

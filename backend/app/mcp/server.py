from collections.abc import Callable
from datetime import datetime

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.agent_run import AgentRun
from app.models.repository import Repository
from app.services.ci_service import CIService
from app.services.file_service import FileService
from app.services.repo_memory_service import RepoMemoryService
from app.services.repo_service import RepoService
from app.services.retrieval_service import RetrievalService

SessionFactory = Callable[[], Session]
READ_ONLY_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)


def create_mcp_server(
    *,
    session_factory: SessionFactory = SessionLocal,
    allowed_repo_ids: set[str] | None = None,
    max_file_lines: int | None = None,
) -> FastMCP:
    """Build the read-only CodeMate MCP server.

    An empty repository scope means all repositories. A non-empty scope is
    enforced by every tool, including run lookups.
    """

    repository_scope = set(
        settings.mcp_repository_scope if allowed_repo_ids is None else allowed_repo_ids
    )
    file_line_limit = max(1, max_file_lines or settings.mcp_max_file_lines)
    mcp = FastMCP(
        "CodeMate",
        instructions=(
            "Read-only access to CodeMate's indexed repositories. "
            "The server cannot modify files, apply patches, or execute commands."
        ),
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
    )

    def require_repository(db: Session, repo_id: str) -> Repository:
        if repository_scope and repo_id not in repository_scope:
            raise ToolError("Repository not available")
        repository = db.get(Repository, repo_id)
        if repository is None:
            raise ToolError("Repository not available")
        return repository

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    def list_repositories() -> list[dict[str, object]]:
        """List repositories visible to this MCP credential."""

        with session_factory() as db:
            repositories = RepoService(db).list()
            if repository_scope:
                repositories = [repo for repo in repositories if repo.id in repository_scope]
            return [serialize_repository(repository) for repository in repositories]

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    def search_code(repo_id: str, query: str, top_k: int = 8) -> list[dict[str, object]]:
        """Search indexed code semantically and return cited code chunks."""

        normalized_query = query.strip()
        if not normalized_query:
            raise ToolError("query must not be empty")
        if not 1 <= top_k <= 20:
            raise ToolError("top_k must be between 1 and 20")

        with session_factory() as db:
            repository = require_repository(db, repo_id)
            if repository.status != "indexed":
                raise ToolError("Repository must be indexed before searching")
            results = RetrievalService(db).retrieve(
                repo_id=repo_id,
                query=normalized_query,
                top_k=top_k,
            )
            return [
                {
                    "chunk_id": result.chunk.id,
                    "file_path": result.chunk.file_path,
                    "language": result.chunk.language,
                    "symbol_name": result.chunk.symbol_name,
                    "symbol_type": result.chunk.symbol_type,
                    "start_line": result.chunk.start_line,
                    "end_line": result.chunk.end_line,
                    "score": result.score,
                    "source": result.source,
                    "content": (result.chunk.content or "")[:4000],
                }
                for result in results
            ]

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    def list_files(repo_id: str, limit: int = 200) -> list[dict[str, object]]:
        """List indexed files and basic metadata for one repository."""

        if not 1 <= limit <= 500:
            raise ToolError("limit must be between 1 and 500")
        with session_factory() as db:
            require_repository(db, repo_id)
            files = FileService(db).list_files(repo_id)[:limit]
            return [
                {
                    "file_path": code_file.file_path,
                    "language": code_file.language,
                    "line_count": code_file.line_count,
                    "size_bytes": code_file.size_bytes,
                }
                for code_file in files
            ]

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    def read_file(
        repo_id: str,
        path: str,
        start_line: int = 1,
        end_line: int | None = None,
    ) -> dict[str, object]:
        """Read a bounded line range from an indexed repository file."""

        normalized_path = path.strip()
        if not normalized_path:
            raise ToolError("path must not be empty")
        if start_line < 1:
            raise ToolError("start_line must be at least 1")
        requested_end = end_line if end_line is not None else start_line + file_line_limit - 1
        if requested_end < start_line:
            raise ToolError("end_line must not be before start_line")
        if requested_end - start_line + 1 > file_line_limit:
            raise ToolError(f"A file read is limited to {file_line_limit} lines")

        with session_factory() as db:
            require_repository(db, repo_id)
            try:
                code_file, safe_start, safe_end, content = FileService(db).read_content(
                    repo_id=repo_id,
                    file_path=normalized_path,
                    start_line=start_line,
                    end_line=requested_end,
                )
            except (FileNotFoundError, PermissionError) as exc:
                raise ToolError(str(exc)) from exc
            if code_file is None:
                raise ToolError("File not found in repository index")
            if code_file.line_count and safe_start > code_file.line_count:
                raise ToolError("start_line is beyond the end of the file")
            return {
                "file_path": normalized_path,
                "language": code_file.language,
                "start_line": safe_start,
                "end_line": safe_end,
                "line_count": code_file.line_count,
                "truncated": safe_end < code_file.line_count,
                "content": content,
            }

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    def get_repo_memory(repo_id: str) -> dict[str, object]:
        """Return CodeMate's cached structural summary for a repository."""

        with session_factory() as db:
            require_repository(db, repo_id)
            try:
                memory = RepoMemoryService(db).read(repo_id)
            except FileNotFoundError as exc:
                raise ToolError(str(exc)) from exc
            memory["updated_at"] = isoformat(memory.get("updated_at"))
            return memory

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    def inspect_ci(repo_id: str) -> dict[str, object]:
        """Inspect CI configuration and preview CodeMate's generated workflow."""

        with session_factory() as db:
            require_repository(db, repo_id)
            try:
                return CIService(db).inspect(repo_id)
            except FileNotFoundError as exc:
                raise ToolError(str(exc)) from exc

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
    def get_run_status(run_id: str) -> dict[str, object]:
        """Read status and summary for an existing CodeMate agent run."""

        with session_factory() as db:
            run = db.get(AgentRun, run_id)
            if run is None:
                raise ToolError("Run not available")
            require_repository(db, run.repo_id)
            return {
                "id": run.id,
                "repo_id": run.repo_id,
                "task_type": run.task_type,
                "status": run.status,
                "final_summary": run.final_summary,
                "failure_reason": run.failure_reason,
                "test_result": run.test_result,
                "iterations": run.iterations,
                "created_at": isoformat(run.created_at),
                "updated_at": isoformat(run.updated_at),
                "finished_at": isoformat(run.finished_at),
            }

    return mcp


def serialize_repository(repository: Repository) -> dict[str, object]:
    return {
        "id": repository.id,
        "name": repository.name,
        "status": repository.status,
        "language_summary": repository.language_summary or {},
        "file_count": repository.file_count,
        "chunk_count": repository.chunk_count,
        "last_commit_hash": repository.last_commit_hash,
        "indexed_at": isoformat(repository.indexed_at),
        "updated_at": isoformat(repository.updated_at),
    }


def isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None

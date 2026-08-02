from pathlib import Path
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.code_chunk import CodeChunk
from app.sandbox import SandboxService
from app.services.agent_step_service import AgentStepService
from app.services.retrieval_service import RetrievalService


class AgentTools:
    def __init__(
        self,
        *,
        db: Session,
        run_id: str,
        repo_id: str,
        workspace: Path,
        sandbox: SandboxService,
    ):
        self.db = db
        self.run_id = run_id
        self.repo_id = repo_id
        self.workspace = workspace
        self.sandbox = sandbox
        self.steps = AgentStepService(db)

    def search_code(self, query: str, top_k: int = 6) -> list[dict]:
        def _call():
            results = RetrievalService(self.db).retrieve(
                repo_id=self.repo_id,
                query=query,
                top_k=top_k,
            )
            return [
                {
                    "chunk_id": result.chunk.id,
                    "file_path": result.chunk.file_path,
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

        return self.steps.record_tool(
            run_id=self.run_id,
            tool_name="search_code",
            input_json={"query": query, "repo_id": self.repo_id, "top_k": top_k},
            fn=_call,
        )

    def read_file(
        self,
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> dict:
        return self.steps.record_tool(
            run_id=self.run_id,
            tool_name="read_file",
            input_json={"path": path, "start_line": start_line, "end_line": end_line},
            fn=lambda: self.sandbox.read_file(
                workspace=self.workspace,
                file_path=path,
                start_line=start_line,
                end_line=end_line,
            ),
        )

    def list_files(self, pattern: str | None = None) -> list[str]:
        return self.steps.record_tool(
            run_id=self.run_id,
            tool_name="list_files",
            input_json={"pattern": pattern},
            fn=lambda: self.sandbox.list_files(workspace=self.workspace, pattern=pattern),
        )

    def find_symbol(self, symbol: str, limit: int = 12) -> list[dict]:
        def _call() -> list[dict]:
            chunks = (
                self.db.execute(
                    select(CodeChunk)
                    .where(
                        CodeChunk.repo_id == self.repo_id,
                        CodeChunk.symbol_name == symbol,
                    )
                    .order_by(CodeChunk.file_path, CodeChunk.start_line)
                    .limit(limit)
                )
                .scalars()
                .all()
            )
            return [self._chunk_result(chunk, symbol) for chunk in chunks]

        return self.steps.record_tool(
            run_id=self.run_id,
            tool_name="find_symbol",
            input_json={"symbol": symbol, "repo_id": self.repo_id, "limit": limit},
            fn=_call,
        )

    def find_references(self, symbol: str, limit: int = 20) -> list[dict]:
        def _call() -> list[dict]:
            candidates = (
                self.db.execute(
                    select(CodeChunk)
                    .where(
                        CodeChunk.repo_id == self.repo_id,
                        CodeChunk.content.ilike(f"%{self._escape_like(symbol)}%", escape="\\"),
                    )
                    .order_by(CodeChunk.file_path, CodeChunk.start_line)
                    .limit(limit * 4)
                )
                .scalars()
                .all()
            )
            boundary = re.compile(rf"(?<![\w$]){re.escape(symbol)}(?![\w$])")
            references = [
                self._chunk_result(chunk, symbol)
                for chunk in candidates
                if boundary.search(chunk.content or "")
            ]
            return references[:limit]

        return self.steps.record_tool(
            run_id=self.run_id,
            tool_name="find_references",
            input_json={"symbol": symbol, "repo_id": self.repo_id, "limit": limit},
            fn=_call,
        )

    def apply_patch(self, diff: str) -> dict:
        return self.steps.record_tool(
            run_id=self.run_id,
            tool_name="apply_patch",
            input_json={"diff_preview": diff[:1000], "length": len(diff)},
            fn=lambda: self.sandbox.apply_patch(workspace=self.workspace, diff=diff),
        )

    def inspect_repository(self, requested_test_command: str | None) -> dict:
        def _call() -> dict:
            files = self.sandbox.list_files(workspace=self.workspace)
            detected_test_command = self.sandbox.detect_test_command(
                workspace=self.workspace,
                requested_command=None,
            )
            resolved_test_command = self.sandbox.detect_test_command(
                workspace=self.workspace,
                requested_command=requested_test_command,
            )
            return {
                "file_count": len(files),
                "requested_test_command": requested_test_command,
                "detected_test_command": detected_test_command,
                "resolved_test_command": resolved_test_command,
                "regression_test_command": detected_test_command or resolved_test_command,
            }

        return self.steps.record_tool(
            run_id=self.run_id,
            tool_name="inspect_repository",
            input_json={"requested_test_command": requested_test_command},
            fn=_call,
        )

    def run_tests(self, command: str | None = None, *, phase: str) -> dict:
        detected = self.sandbox.detect_test_command(
            workspace=self.workspace,
            requested_command=command,
        )
        result = self.steps.record_tool(
            run_id=self.run_id,
            tool_name="run_tests",
            input_json={"command": detected, "phase": phase},
            fn=lambda: self.sandbox.run_tests(workspace=self.workspace, command=detected).to_dict(),
        )
        result["phase"] = phase
        return result

    def git_diff(self) -> str:
        return self.steps.record_tool(
            run_id=self.run_id,
            tool_name="git_diff",
            input_json={},
            fn=lambda: self.sandbox.git_diff(workspace=self.workspace),
        )

    def reset_workspace(self) -> dict:
        return self.steps.record_tool(
            run_id=self.run_id,
            tool_name="reset_workspace",
            input_json={},
            fn=lambda: self.sandbox.reset_workspace(workspace=self.workspace),
        )

    @staticmethod
    def _escape_like(value: str) -> str:
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    @staticmethod
    def _chunk_result(chunk: CodeChunk, symbol: str) -> dict:
        content = chunk.content or ""
        match = re.search(re.escape(symbol), content)
        if match:
            start = max(0, match.start() - 600)
            end = min(len(content), match.end() + 1_400)
            preview = content[start:end]
        else:
            preview = content[:2_000]
        return {
            "chunk_id": chunk.id,
            "file_path": chunk.file_path,
            "symbol_name": chunk.symbol_name,
            "symbol_type": chunk.symbol_type,
            "start_line": chunk.start_line,
            "end_line": chunk.end_line,
            "content": preview,
        }

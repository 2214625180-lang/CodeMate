from pathlib import Path

from sqlalchemy.orm import Session

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

    def apply_patch(self, diff: str) -> dict:
        return self.steps.record_tool(
            run_id=self.run_id,
            tool_name="apply_patch",
            input_json={"diff_preview": diff[:1000], "length": len(diff)},
            fn=lambda: self.sandbox.apply_patch(workspace=self.workspace, diff=diff),
        )

    def run_tests(self, command: str | None = None) -> dict:
        detected = self.sandbox.detect_test_command(
            workspace=self.workspace,
            requested_command=command,
        )
        result = self.steps.record_tool(
            run_id=self.run_id,
            tool_name="run_tests",
            input_json={"command": detected},
            fn=lambda: self.sandbox.run_tests(workspace=self.workspace, command=detected).to_dict(),
        )
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

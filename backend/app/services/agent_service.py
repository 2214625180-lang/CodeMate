import re
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.agent.graph import build_fix_graph
from app.agent.state import FixAgentState
from app.agent.tools import AgentTools
from app.core.config import settings
from app.llm import get_llm_provider
from app.models.agent_run import AgentRun
from app.models.agent_step import AgentStep
from app.models.repository import Repository
from app.sandbox import SandboxService
from app.services.agent_step_service import AgentStepService


class AgentService:
    def __init__(self, db: Session):
        self.db = db
        self.sandbox = SandboxService()
        self.llm = get_llm_provider()

    def create_fix_run(
        self,
        *,
        repo_id: str,
        issue: str,
        test_command: str | None,
    ) -> AgentRun:
        run = AgentRun(
            repo_id=repo_id,
            user_input=issue,
            test_command=test_command,
            status="pending",
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def run_fix(self, run_id: str) -> None:
        run = self.db.get(AgentRun, run_id)
        if run is None:
            return

        repository = self.db.get(Repository, run.repo_id)
        if repository is None or repository.local_path is None:
            self._finish_failed(run, "Repository workspace is not available.")
            return

        workspace: Path | None = None
        try:
            run.status = "running"
            run.updated_at = datetime.utcnow()
            self.db.add(run)
            self.db.commit()

            workspace = self.sandbox.create_workspace(
                run_id=run.id,
                source_path=repository.local_path,
            )
            tools = AgentTools(
                db=self.db,
                run_id=run.id,
                repo_id=run.repo_id,
                workspace=workspace,
                sandbox=self.sandbox,
            )
            steps = AgentStepService(self.db)
            graph = build_fix_graph(self._nodes(run, tools, steps))
            final_state = graph.invoke(
                {
                    "run_id": run.id,
                    "repo_id": run.repo_id,
                    "user_input": run.user_input,
                    "test_command": run.test_command,
                    "iterations": 0,
                    "files": {},
                    "max_iterations": settings.max_agent_iterations,
                }
            )
            self._persist_final_state(run.id, final_state)
        except Exception as exc:  # noqa: BLE001 - store user-visible run failure.
            failed_run = self.db.get(AgentRun, run_id)
            if failed_run is not None:
                self._finish_failed(failed_run, str(exc))
        finally:
            if workspace is not None:
                self.sandbox.cleanup_workspace(workspace)

    def _nodes(self, run: AgentRun, tools: AgentTools, steps: AgentStepService) -> dict:
        def parse_issue(state: FixAgentState) -> FixAgentState:
            issue = state["user_input"]
            parsed = {
                "error_terms": re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*(?:Error|Exception)\b", issue),
                "file_paths": re.findall(r"[\w./@-]+\.(?:ts|tsx|js|jsx|py|vue)", issue),
                "keywords": re.findall(r"\b[A-Za-z_$][A-Za-z0-9_$]{2,}\b", issue)[:20],
            }
            steps.record(
                run_id=run.id,
                step_type="plan",
                input_json={"issue_preview": issue[:1200]},
                output_json={"parsed_issue": parsed},
            )
            return {"parsed_issue": parsed}

        def retrieve_context(state: FixAgentState) -> FixAgentState:
            query = self._build_query(state)
            chunks = tools.search_code(query, top_k=6)
            return {"retrieved_chunks": chunks}

        def read_files(state: FixAgentState) -> FixAgentState:
            files: dict[str, str] = dict(state.get("files") or {})
            file_paths = []
            for chunk in state.get("retrieved_chunks", []):
                path = chunk.get("file_path")
                if isinstance(path, str) and path not in file_paths:
                    file_paths.append(path)
                if len(file_paths) >= 3:
                    break

            if not file_paths:
                listed = tools.list_files()
                file_paths = listed[:3]

            for path in file_paths:
                if path in files:
                    continue
                content = tools.read_file(path)
                files[path] = content["content"]

            return {"files": files}

        def diagnose(state: FixAgentState) -> FixAgentState:
            files = state.get("files") or {}
            diagnosis = (
                f"根据问题描述和检索结果，优先检查 {', '.join(files.keys()) or '相关文件'}。"
                "本地 Mock 诊断会使用确定性规则生成最小 patch。"
            )
            steps.record(
                run_id=run.id,
                step_type="observation",
                output_json={"diagnosis": diagnosis},
            )
            return {"diagnosis": diagnosis}

        def generate_patch(state: FixAgentState) -> FixAgentState:
            patch = self.llm.generate_patch(
                issue=state["user_input"],
                diagnosis=state.get("diagnosis", ""),
                files=state.get("files") or {},
                previous_failure=(state.get("test_result") or {}).get("stderr"),
            )
            steps.record(
                run_id=run.id,
                step_type="patch",
                output_json={"diff": patch, "length": len(patch)},
            )
            return {"patch": patch}

        def apply_patch(state: FixAgentState) -> FixAgentState:
            return {"apply_result": tools.apply_patch(state.get("patch", ""))}

        def run_tests(state: FixAgentState) -> FixAgentState:
            apply_result = state.get("apply_result") or {}
            if not apply_result.get("ok"):
                test_result = {
                    "passed": False,
                    "exit_code": apply_result.get("exit_code", 1),
                    "stdout": apply_result.get("stdout", ""),
                    "stderr": apply_result.get("stderr", "Patch did not apply."),
                    "command": None,
                    "tests_ran": False,
                }
            else:
                test_result = tools.run_tests(state.get("test_command"))

            steps.record(
                run_id=run.id,
                step_type="test_result",
                output_json=test_result,
            )
            return {
                "test_result": test_result,
                "iterations": state.get("iterations", 0) + 1,
            }

        def reflect(state: FixAgentState) -> FixAgentState:
            reflection = self.llm.reflect(
                issue=state["user_input"],
                patch=state.get("patch", ""),
                test_result=state.get("test_result") or {},
                iteration=state.get("iterations", 0),
            )
            reset_result = tools.reset_workspace()
            reflection["reset_workspace"] = reset_result
            steps.record(
                run_id=run.id,
                step_type="reflection",
                output_json=reflection,
            )
            return {"reflection": reflection, "apply_result": {}, "patch": ""}

        def final_answer(state: FixAgentState) -> FixAgentState:
            diff = tools.git_diff()
            test_result = state.get("test_result") or {}
            passed = bool(test_result.get("passed"))
            if passed and test_result.get("tests_ran"):
                summary = "Patch 已应用并且测试通过。"
            elif passed and test_result.get("skipped_reason"):
                summary = "Patch 已应用；测试因 sandbox 离线且依赖未安装而未运行，仅完成 patch 校验。"
            elif passed:
                summary = "Patch 已应用；未检测到测试命令，未运行测试，仅完成 patch 校验。"
            else:
                summary = "Agent 未能在最大重试次数内生成通过测试的 patch。"
            return {
                "final_diff": diff,
                "final_summary": summary,
                "status": "success" if passed else "failed",
            }

        return {
            "parse_issue": parse_issue,
            "retrieve_context": retrieve_context,
            "read_files": read_files,
            "diagnose": diagnose,
            "generate_patch": generate_patch,
            "apply_patch": apply_patch,
            "run_tests": run_tests,
            "reflect": reflect,
            "final_answer": final_answer,
        }

    def _build_query(self, state: FixAgentState) -> str:
        parsed = state.get("parsed_issue") or {}
        pieces = [
            state.get("user_input", ""),
            " ".join(parsed.get("file_paths") or []),
            " ".join(parsed.get("error_terms") or []),
            " ".join(parsed.get("keywords") or []),
            (state.get("reflection") or {}).get("summary", ""),
        ]
        return "\n".join(piece for piece in pieces if piece)

    def _persist_final_state(self, run_id: str, state: FixAgentState) -> None:
        run = self.db.get(AgentRun, run_id)
        if run is None:
            return

        run.status = state.get("status", "failed")
        run.final_diff = state.get("final_diff")
        run.final_summary = state.get("final_summary")
        run.test_result = state.get("test_result")
        run.iterations = state.get("iterations", 0)
        run.failure_reason = None if run.status == "success" else run.final_summary
        run.finished_at = datetime.utcnow()
        run.updated_at = datetime.utcnow()
        self.db.add(run)
        self.db.add(
            AgentStep(
                run_id=run.id,
                step_type="final",
                output_json={
                    "summary": run.final_summary,
                    "passed": run.status == "success",
                },
                created_at=run.finished_at,
            )
        )
        self.db.commit()

    def _finish_failed(self, run: AgentRun, reason: str) -> None:
        now = datetime.utcnow()
        run.status = "failed"
        run.failure_reason = reason
        run.final_summary = reason
        run.finished_at = now
        run.updated_at = now
        self.db.add(run)
        self.db.add(
            AgentStep(
                run_id=run.id,
                step_type="error",
                output_json={"message": reason},
                created_at=now,
            )
        )
        self.db.commit()

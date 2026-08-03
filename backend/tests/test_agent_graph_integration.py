import subprocess

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agent.actions import FindSymbol, GeneratePatch, ReadFile, SearchCode
from app.core.config import settings
from app.core.database import Base
from app.models.agent_run import AgentRun
from app.models.code_chunk import CodeChunk
from app.models.code_file import CodeFile
from app.models.repository import Repository
from app.sandbox.runner import TestResult as SandboxTestResult
from app.services.agent_service import AgentService


class ReflectionScenarioLLM:
    """Deterministic planner that forces a failed patch before a reflected retry."""

    def __init__(self) -> None:
        self.plan_calls = 0
        self.patch_calls = 0

    def plan_next_action(self, *, issue: str, context: dict):
        del issue, context
        actions = [
            SearchCode(
                action="SearchCode",
                hypothesis="The indexed symbol can identify the implementation.",
                rationale="Search before opening the source file.",
                query="add math.py",
                top_k=4,
            ),
            ReadFile(
                action="ReadFile",
                hypothesis="The source confirms the faulty arithmetic operator.",
                rationale="Read the implementation before generating a patch.",
                path="math.py",
                start_line=1,
                end_line=2,
            ),
            GeneratePatch(
                action="GeneratePatch",
                hypothesis="The operator can be corrected with a minimal diff.",
                rationale="Evidence is sufficient for the first patch attempt.",
            ),
            FindSymbol(
                action="FindSymbol",
                hypothesis="The failed attempt requires a second evidence path.",
                rationale="Reconfirm the affected symbol after reflection.",
                symbol="add",
            ),
            GeneratePatch(
                action="GeneratePatch",
                hypothesis="The reflected evidence supports a corrected retry.",
                rationale="Generate a distinct patch after the failed verification.",
            ),
        ]
        action = actions[self.plan_calls]
        self.plan_calls += 1
        return action, 25

    def generate_patch(self, **_kwargs) -> str:
        self.patch_calls += 1
        replacement = "a * b" if self.patch_calls == 1 else "a + b"
        return (
            "--- a/math.py\n"
            "+++ b/math.py\n"
            "@@ -1,2 +1,2 @@\n"
            " def add(a, b):\n"
            "-    return a - b\n"
            f"+    return {replacement}\n"
        )

    def consume_llm_usage(self) -> dict[str, int | bool]:
        return {"total_tokens": 25, "input_tokens": 10, "output_tokens": 15, "estimated": True}


def test_full_agent_graph_retrieves_reflects_and_verifies_a_distinct_retry(tmp_path, monkeypatch):
    repository_path = tmp_path / "repository"
    repository_path.mkdir()
    source = "def add(a, b):\n    return a - b\n"
    (repository_path / "math.py").write_text(source, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repository_path, check=True)
    subprocess.run(["git", "add", "math.py"], cwd=repository_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=CodeMate Tests",
            "-c",
            "user.email=tests@codemate.local",
            "commit",
            "-qm",
            "initial",
        ],
        cwd=repository_path,
        check=True,
    )

    engine = create_engine(f"sqlite:///{tmp_path / 'agent-graph.db'}")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    repository = Repository(
        id="repo-agent-graph",
        name="agent-graph",
        repo_url="https://example.com/agent-graph.git",
        local_path=str(repository_path),
        status="indexed",
    )
    code_file = CodeFile(
        id="file-agent-graph",
        repo_id=repository.id,
        file_path="math.py",
        language="python",
        content_hash="math-hash",
        line_count=2,
        size_bytes=len(source),
    )
    code_chunk = CodeChunk(
        id="chunk-agent-graph",
        repo_id=repository.id,
        file_id=code_file.id,
        file_path="math.py",
        language="python",
        symbol_name="add",
        symbol_type="function",
        start_line=1,
        end_line=2,
        content=source,
        content_hash="chunk-hash",
    )
    run = AgentRun(
        id="run-agent-graph",
        repo_id=repository.id,
        user_input="Fix the incorrect addition result in math.py",
        test_command="pytest",
        status="pending",
    )
    db.add_all([repository, code_file, code_chunk, run])
    db.commit()

    monkeypatch.setattr(settings, "agent_planner_mode", "adaptive")
    monkeypatch.setattr(settings, "max_agent_iterations", 3)
    monkeypatch.setattr(settings, "mcp_tool_router_enabled", False)
    monkeypatch.setattr(settings, "sandbox_workspace_dir", str(tmp_path / "sandboxes"))
    service = AgentService(db)
    service.llm = ReflectionScenarioLLM()  # type: ignore[assignment]

    def deterministic_tests(*, workspace, command):
        del command
        fixed = "return a + b" in (workspace / "math.py").read_text(encoding="utf-8")
        return SandboxTestResult(
            passed=fixed,
            exit_code=0 if fixed else 1,
            stdout="1 passed" if fixed else "1 failed",
            stderr="" if fixed else "addition is still incorrect",
            command="pytest",
            tests_ran=True,
        )

    monkeypatch.setattr(service.sandbox, "run_tests", deterministic_tests)
    service.run_fix(run.id)

    db.refresh(run)
    targeted_results = [
        step.output_json
        for step in run.steps
        if step.step_type == "targeted_test_result"
    ]
    step_types = [step.step_type for step in run.steps]

    assert run.status == "verified_success"
    assert run.iterations == 2
    assert len(targeted_results) == 2
    assert [result["exit_code"] for result in targeted_results] == [1, 0]
    assert "reflection" in step_types
    assert "search_code" in [step.tool_name for step in run.steps if step.step_type == "tool_call"]
    assert "find_symbol" in [step.tool_name for step in run.steps if step.step_type == "tool_call"]
    assert "return a + b" in (run.final_diff or "")

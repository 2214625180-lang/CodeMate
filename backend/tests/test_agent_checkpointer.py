import subprocess
import json
from typing import TypedDict

import pytest
from langgraph.graph import END, StateGraph
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agent.checkpointer import SQLAlchemyCheckpointSaver
from app.core.database import Base
from app.models.agent_checkpoint import AgentCheckpoint
from app.models.agent_step import AgentStep
from app.models.agent_run import AgentRun
from app.models.repository import Repository
from app.sandbox.runner import TestResult as SandboxTestResult
from app.services.agent_service import AgentService
from app.core.config import settings


class RecoveryState(TypedDict, total=False):
    value: int


def test_sqlalchemy_checkpointer_resumes_from_last_completed_node(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'checkpoints.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory.begin() as db:
        repository = Repository(
            id="repo-checkpoint",
            name="checkpoint-repo",
            repo_url="https://example.com/checkpoint.git",
            status="indexed",
        )
        run = AgentRun(
            id="run-checkpoint",
            repo_id=repository.id,
            user_input="recover",
            status="running",
        )
        db.add_all([repository, run])

    should_fail = {"value": True}

    def increment(state: RecoveryState) -> RecoveryState:
        return {"value": int(state.get("value", 0)) + 1}

    def maybe_fail(state: RecoveryState) -> RecoveryState:
        if should_fail["value"]:
            raise RuntimeError("simulated worker failure")
        return {"value": int(state.get("value", 0)) + 1}

    def compile_graph():
        builder = StateGraph(RecoveryState)
        builder.add_node("Increment", increment)
        builder.add_node("MaybeFail", maybe_fail)
        builder.set_entry_point("Increment")
        builder.add_edge("Increment", "MaybeFail")
        builder.add_edge("MaybeFail", END)
        return builder.compile(checkpointer=SQLAlchemyCheckpointSaver(session_factory))

    config = {
        "configurable": {
            "thread_id": "run-checkpoint",
        }
    }
    first_graph = compile_graph()
    with pytest.raises(RuntimeError, match="simulated worker failure"):
        first_graph.invoke({"value": 0}, config=config)

    snapshot = first_graph.get_state(config)
    assert snapshot.values["value"] == 1
    assert snapshot.next == ("MaybeFail",)

    should_fail["value"] = False
    recovered = compile_graph().invoke(None, config=config)

    assert recovered["value"] == 2
    history = list(compile_graph().get_state_history(config))
    assert len(history) >= 3
    assert history[0].values["value"] == 2


def test_full_fix_run_uses_controlled_loop_and_persists_checkpoints(tmp_path, monkeypatch):
    repository_path = tmp_path / "repository"
    repository_path.mkdir()
    (repository_path / "math.py").write_text(
        "def add(a, b):\n    return a - b\n",
        encoding="utf-8",
    )
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

    engine = create_engine(f"sqlite:///{tmp_path / 'agent.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = session_factory()
    repository = Repository(
        id="repo-loop",
        name="loop-repo",
        repo_url="https://example.com/loop.git",
        local_path=str(repository_path),
        status="indexed",
    )
    run = AgentRun(
        id="run-loop",
        repo_id=repository.id,
        user_input="Fix the addition bug in math.py",
        test_command="pytest",
        status="pending",
    )
    db.add_all([repository, run])
    db.commit()

    monkeypatch.setattr(settings, "llm_provider", "mock")
    monkeypatch.setattr(settings, "sandbox_workspace_dir", str(tmp_path / "sandboxes"))
    service = AgentService(db)

    def deterministic_tests(*, workspace, command):
        fixed = "return a + b" in (workspace / "math.py").read_text(encoding="utf-8")
        return SandboxTestResult(
            passed=fixed,
            exit_code=0 if fixed else 1,
            stdout="1 passed" if fixed else "1 failed",
            stderr="" if fixed else "assertion failed",
            command=command,
            tests_ran=True,
        )

    monkeypatch.setattr(service.sandbox, "run_tests", deterministic_tests)
    service.run_fix(run.id)

    db.refresh(run)
    assert run.status == "verified_success", json.dumps(
        [(step.step_type, step.tool_name, step.output_json) for step in run.steps],
        default=str,
        indent=2,
    )
    assert "return a + b" in (run.final_diff or "")
    step_types = [step.step_type for step in run.steps]
    assert step_types.count("agent_plan") >= 2
    assert "agent_observation" in step_types
    plans_before_restore = db.query(AgentStep).filter_by(
        run_id=run.id,
        step_type="agent_plan",
    ).count()
    restored_final_state = service._invoke_fix_graph(run, service._initial_state(run))
    plans_after_restore = db.query(AgentStep).filter_by(
        run_id=run.id,
        step_type="agent_plan",
    ).count()
    assert restored_final_state["status"] == "verified_success"
    assert plans_after_restore == plans_before_restore
    assert db.query(AgentStep).filter_by(
        run_id=run.id,
        step_type="checkpoint_resume",
    ).count() == 1
    with session_factory() as checkpoint_db:
        checkpoint_count = checkpoint_db.query(AgentCheckpoint).count()
    assert checkpoint_count > 0
    db.close()

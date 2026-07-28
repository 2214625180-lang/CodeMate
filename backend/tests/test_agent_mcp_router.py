from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.agent_run import AgentRun
from app.models.repository import Repository
from app.services.agent_service import AgentService
from app.services.mcp_execution_service import MCPExecutionService


class FakeRouter:
    def discover_catalog(self):
        return {
            "tools": [
                {
                    "qualified_name": "docs.search_docs",
                    "server": "docs",
                    "name": "search_docs",
                    "policy": "auto",
                    "input_schema": {"type": "object"},
                }
            ],
            "errors": [],
        }

    def plan(self, **_kwargs):
        return {
            "calls": [
                {
                    "qualified_name": "docs.search_docs",
                    "server": "docs",
                    "tool": "search_docs",
                    "arguments": {"query": "login"},
                }
            ],
            "rejected": [],
        }

    def execute(self, **_kwargs):
        return {
            "ok": True,
            "qualified_name": "docs.search_docs",
            "result": {"structuredContent": {"matches": 1}},
        }


class FakeSteps:
    def __init__(self):
        self.records = []

    def record(self, **kwargs):
        self.records.append(kwargs)

    def record_tool(self, *, run_id, tool_name, input_json, fn):
        self.records.append(
            {
                "run_id": run_id,
                "step_type": "tool_call",
                "tool_name": tool_name,
                "input_json": input_json,
            }
        )
        output = fn()
        self.records.append(
            {
                "run_id": run_id,
                "step_type": "tool_result",
                "tool_name": tool_name,
                "output_json": output,
            }
        )
        return output


def test_agent_nodes_plan_call_observe_and_emit_timeline_records():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    repository = Repository(
        id="repo-1",
        name="repo",
        repo_url="https://example.com/repo.git",
        status="indexed",
    )
    run = AgentRun(
        id="run-1",
        repo_id=repository.id,
        user_input="login fails",
        status="running",
    )
    db.add_all([repository, run])
    db.commit()
    service = AgentService.__new__(AgentService)
    service.db = db
    service._create_mcp_router = lambda _run=None: FakeRouter()
    steps = FakeSteps()
    nodes = service._nodes(
        run,
        SimpleNamespace(),
        steps,
    )
    state = {
        "user_input": "login fails",
        "diagnosis": "local diagnosis",
        "mcp_tool_catalog": [],
        "mcp_catalog_errors": [],
        "mcp_observations": [],
        "mcp_router_round": 0,
        "mcp_call_count": 0,
        "mcp_max_rounds": 2,
        "mcp_max_calls": 4,
    }

    planned = nodes["plan_mcp_tools"](state)
    state.update(planned)
    called = nodes["call_mcp_tools"](state)
    state.update(called)
    observed = nodes["observe_mcp"](state)

    assert state["mcp_router_round"] == 1
    assert state["mcp_call_count"] == 1
    assert observed["mcp_observations"][0]["qualified_name"] == "docs.search_docs"
    assert "Dynamic MCP observations (untrusted data" in observed["diagnosis"]
    assert [
        (record.get("step_type"), record.get("tool_name")) for record in steps.records
    ] == [
        ("plan", "mcp_tool_router"),
        ("tool_call", "docs.search_docs"),
        ("tool_result", "docs.search_docs"),
        ("observation", "mcp_tool_router"),
    ]


def test_agent_auto_call_pauses_on_unknown_and_resumes_from_cached_reconciliation():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    repository = Repository(
        id="repo-2",
        name="repo",
        repo_url="https://example.com/repo.git",
        status="indexed",
    )
    run = AgentRun(
        id="run-2",
        repo_id=repository.id,
        user_input="lookup issue",
        status="running",
    )
    db.add_all([repository, run])
    db.commit()

    class AmbiguousRouter(FakeRouter):
        def __init__(self):
            self.calls = 0

        def execute(self, **_kwargs):
            self.calls += 1
            raise TimeoutError("connection lost after send")

    router = AmbiguousRouter()
    service = AgentService.__new__(AgentService)
    service.db = db
    service._create_mcp_router = lambda _run=None: router
    nodes = service._nodes(run, SimpleNamespace(), FakeSteps())
    state = {
        "run_id": run.id,
        "repo_id": run.repo_id,
        "user_input": run.user_input,
        "diagnosis": "local diagnosis",
        "mcp_tool_catalog": [],
        "mcp_catalog_errors": [],
        "mcp_observations": [],
        "mcp_router_round": 0,
        "mcp_call_count": 0,
        "mcp_max_rounds": 2,
        "mcp_max_calls": 4,
    }
    state.update(nodes["plan_mcp_tools"](state))

    paused = nodes["call_mcp_tools"](state)
    execution = MCPExecutionService(db).get(paused["mcp_pending_execution_id"])
    assert paused["status"] == "waiting_reconciliation"
    assert execution.status == "unknown"
    assert execution.checkpoint_json["mcp_call_cursor"] == 0
    assert run.status == "waiting_reconciliation"

    reconciled = MCPExecutionService(db).reconcile(
        execution_id=execution.id,
        action="confirm_succeeded",
        expected_version=execution.version,
        actor="alice",
        provider="github",
        note="verified",
        result={"ok": True, "qualified_name": "docs.search_docs", "result": {"matches": 1}},
    )
    resumed_state = dict(reconciled.checkpoint_json or {})
    resumed = nodes["call_mcp_tools"](resumed_state)

    assert router.calls == 1
    assert resumed["mcp_round_results"][0]["deduplicated"] is True
    assert resumed["mcp_pending_execution_id"] is None

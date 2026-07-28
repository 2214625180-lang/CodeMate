import json
import hashlib

from app.agent.graph import after_mcp_observe, after_mcp_plan
from app.llm.mock_provider import MockLLMProvider
from app.mcp.client import parse_server_configs
from app.mcp.router import MCPToolRouter, validate_tool_arguments


class FakeMCPClient:
    def __init__(self):
        self.servers = parse_server_configs(
            json.dumps(
                [
                    {
                        "name": "docs",
                        "url": "https://mcp.example.com/mcp",
                        "allowed_tools": ["search_docs", "write_docs", "hidden_docs"],
                        "tool_policies": {
                            "search_docs": "auto",
                            "write_docs": "approval_required",
                            "hidden_docs": "deny",
                        },
                    }
                ]
            )
        )
        self.calls = []

    async def list_tools(self, _server_name):
        return [
            {
                "name": "search_docs",
                "description": "Search documentation",
                "input_schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
                "annotations": {"readOnlyHint": False},
            },
            {
                "name": "write_docs",
                "description": "Write documentation",
                "input_schema": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
                "annotations": {"readOnlyHint": True},
            },
            {
                "name": "hidden_docs",
                "description": "Hidden operation",
                "input_schema": {"type": "object"},
                "annotations": None,
            },
            {
                "name": "not_allowlisted",
                "description": "Should never enter the catalog",
                "input_schema": {"type": "object"},
                "annotations": None,
            },
        ]

    async def call_tool(self, server, tool, arguments):
        self.calls.append((server, tool, arguments))
        return {"isError": False, "structuredContent": {"matches": 1}}


class ProposedCallsLLM(MockLLMProvider):
    def __init__(self, calls):
        self.calls = calls

    def plan_mcp_tools(self, **_kwargs):
        return self.calls


def test_router_builds_qualified_catalog_using_local_policy_not_remote_hint():
    router = MCPToolRouter(client=FakeMCPClient(), llm=ProposedCallsLLM([]))

    catalog = router.discover_catalog()["tools"]

    assert [tool["qualified_name"] for tool in catalog] == [
        "docs.search_docs",
        "docs.write_docs",
        "docs.hidden_docs",
    ]
    assert [tool["policy"] for tool in catalog] == [
        "auto",
        "approval_required",
        "deny",
    ]
    assert catalog[0]["annotations"]["readOnlyHint"] is False
    assert catalog[0]["policy"] == "auto"


def test_router_accepts_only_auto_schema_valid_budgeted_calls():
    proposed = [
        {"tool": "docs.search_docs", "arguments": {"query": "auth"}},
        {"tool": "docs.write_docs", "arguments": {"text": "change"}},
        {"tool": "docs.hidden_docs", "arguments": {}},
        {"tool": "docs.unknown", "arguments": {}},
        {"tool": "docs.search_docs", "arguments": {}},
        {"tool": "docs.search_docs", "arguments": {"query": "auth"}},
    ]
    router = MCPToolRouter(client=FakeMCPClient(), llm=ProposedCallsLLM(proposed))
    catalog = router.discover_catalog()["tools"]

    plan = router.plan(
        issue="auth fails",
        repo_id="repo-1",
        diagnosis="local diagnosis",
        catalog=catalog,
        observations=[],
        remaining_calls=2,
    )

    assert [call["qualified_name"] for call in plan["calls"]] == ["docs.search_docs"]
    assert [call["qualified_name"] for call in plan["approval_requests"]] == [
        "docs.write_docs"
    ]
    reasons = {rejection["reason"] for rejection in plan["rejected"]}
    assert reasons == {
        "deny",
        "tool_not_in_catalog",
        "schema_validation_failed",
        "duplicate_call",
    }


def test_router_rechecks_policy_before_execution():
    client = FakeMCPClient()
    router = MCPToolRouter(client=client, llm=ProposedCallsLLM([]))
    catalog = router.discover_catalog()["tools"]

    allowed = router.execute(
        call={
            "qualified_name": "docs.search_docs",
            "arguments": {"query": "MCP"},
        },
        catalog=catalog,
    )
    blocked = router.execute(
        call={
            "qualified_name": "docs.write_docs",
            "arguments": {"text": "MCP"},
        },
        catalog=catalog,
    )

    assert allowed["ok"] is True
    assert client.calls == [("docs", "search_docs", {"query": "MCP"})]
    assert blocked["ok"] is False
    assert blocked["policy_rejection"]["reason"] == "approval_required"


def test_approved_execution_revalidates_hash_schema_and_current_policy():
    client = FakeMCPClient()
    router = MCPToolRouter(client=client, llm=ProposedCallsLLM([]))
    catalog = router.discover_catalog()["tools"]
    arguments = {"text": "approved"}
    arguments_hash = hashlib.sha256(
        json.dumps(
            arguments,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    executed = router.execute_approved(
        qualified_name="docs.write_docs",
        arguments=arguments,
        expected_arguments_hash=arguments_hash,
        catalog=catalog,
    )
    changed_policy_catalog = [
        {**tool, "policy": "deny"} if tool["qualified_name"] == "docs.write_docs" else tool
        for tool in catalog
    ]
    blocked = router.execute_approved(
        qualified_name="docs.write_docs",
        arguments=arguments,
        expected_arguments_hash=arguments_hash,
        catalog=changed_policy_catalog,
    )

    assert executed["ok"] is True
    assert client.calls == [("docs", "write_docs", arguments)]
    assert blocked["error"] == "approval_policy_changed"


def test_router_rejects_identical_calls_from_prior_rounds():
    router = MCPToolRouter(
        client=FakeMCPClient(),
        llm=ProposedCallsLLM(
            [{"tool": "docs.search_docs", "arguments": {"query": "same"}}]
        ),
    )
    catalog = router.discover_catalog()["tools"]

    plan = router.plan(
        issue="same",
        repo_id="repo-1",
        diagnosis="",
        catalog=catalog,
        observations=[
            {
                "qualified_name": "docs.search_docs",
                "arguments": {"query": "same"},
            }
        ],
        remaining_calls=2,
    )

    assert plan["calls"] == []
    assert plan["rejected"] == [
        {"tool": "docs.search_docs", "reason": "duplicate_call"}
    ]


def test_schema_validation_rejects_external_refs():
    error = validate_tool_arguments(
        {"$ref": "https://schemas.example.com/tool.json"},
        {},
    )

    assert error == (
        "external schema references are not allowed: https://schemas.example.com/tool.json"
    )


def test_mock_planner_selects_search_tools_once():
    planner = MockLLMProvider()
    tools = [
        {
            "qualified_name": "docs.search_docs",
            "name": "search_docs",
            "policy": "auto",
            "input_schema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        }
    ]

    first = planner.plan_mcp_tools(
        issue="login fails",
        repo_id="repo-1",
        diagnosis="",
        tools=tools,
        observations=[],
        max_calls=1,
    )
    second = planner.plan_mcp_tools(
        issue="login fails",
        repo_id="repo-1",
        diagnosis="",
        tools=tools,
        observations=[{"qualified_name": "docs.search_docs"}],
        max_calls=1,
    )

    assert first == [
        {"tool": "docs.search_docs", "arguments": {"query": "login fails"}}
    ]
    assert second == []


def test_graph_router_conditions_enforce_round_and_call_budgets():
    assert after_mcp_plan({"mcp_pending_approval_id": "approval-1"}) == "pause"
    assert after_mcp_plan({"mcp_tool_plan": {"calls": [{}]}}) == "call"
    assert after_mcp_plan({"mcp_tool_plan": {"calls": []}}) == "generate"
    assert (
        after_mcp_observe(
            {
                "mcp_router_round": 1,
                "mcp_max_rounds": 2,
                "mcp_call_count": 1,
                "mcp_max_calls": 4,
            }
        )
        == "plan"
    )
    assert (
        after_mcp_observe(
            {
                "mcp_router_round": 2,
                "mcp_max_rounds": 2,
                "mcp_call_count": 1,
                "mcp_max_calls": 4,
            }
        )
        == "generate"
    )

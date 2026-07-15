from typing import Any, TypedDict


class FixAgentState(TypedDict, total=False):
    run_id: str
    repo_id: str
    user_input: str
    test_command: str | None
    parsed_issue: dict[str, Any]
    retrieved_chunks: list[dict[str, Any]]
    files: dict[str, str]
    external_context: list[dict[str, Any]]
    mcp_tool_catalog: list[dict[str, Any]]
    mcp_catalog_errors: list[dict[str, Any]]
    mcp_tool_plan: dict[str, Any]
    mcp_round_results: list[dict[str, Any]]
    mcp_observations: list[dict[str, Any]]
    mcp_router_round: int
    mcp_call_count: int
    mcp_max_rounds: int
    mcp_max_calls: int
    mcp_pending_approval_id: str | None
    mcp_pending_execution_id: str | None
    mcp_call_cursor: int
    resume_from: str | None
    diagnosis: str
    patch: str
    apply_result: dict[str, Any]
    test_result: dict[str, Any]
    reflection: dict[str, Any]
    iterations: int
    max_iterations: int
    final_diff: str
    final_summary: str
    status: str

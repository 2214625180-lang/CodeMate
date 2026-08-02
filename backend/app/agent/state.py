from typing import Any, TypedDict


class FixAgentState(TypedDict, total=False):
    run_id: str
    repo_id: str
    user_input: str
    test_command: str | None
    resolved_test_command: str | None
    regression_test_command: str | None
    inspection_result: dict[str, Any]
    baseline_test_result: dict[str, Any]
    diagnostic_test_result: dict[str, Any]
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
    current_action: dict[str, Any]
    action_outcome: dict[str, Any]
    action_history: list[dict[str, Any]]
    hypotheses: list[str]
    evidence: list[dict[str, Any]]
    evidence_fingerprints: list[str]
    local_action_fingerprints: list[str]
    patch_fingerprints: list[str]
    local_tool_call_count: int
    local_planner_call_count: int
    local_planner_token_count: int
    agent_loop_started_at: str
    agent_loop_deadline_at: str
    no_progress_count: int
    finish_reason: str | None
    patch_is_duplicate: bool
    patch: str
    apply_result: dict[str, Any]
    test_result: dict[str, Any]
    targeted_test_result: dict[str, Any]
    regression_test_result: dict[str, Any]
    verification_result: dict[str, Any]
    reflection: dict[str, Any]
    iterations: int
    max_iterations: int
    final_diff: str
    final_summary: str
    status: str

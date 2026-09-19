from typing import Any, TypedDict


class FixAgentState(TypedDict, total=False):
    """Durable state shared by every LangGraph node in one repair run.

    Nodes return partial updates, which is why every field is optional. Keep
    this type organized by lifecycle rather than by the node that happens to
    write a field. Checkpoints persist these values between worker retries, so
    a field is part of the recovery contract as well as an in-memory type.
    """

    # Stable request identity and commands resolved before the model loop starts.
    run_id: str
    repo_id: str
    user_input: str
    test_command: str | None
    resolved_test_command: str | None
    regression_test_command: str | None
    inspection_result: dict[str, Any]
    baseline_test_result: dict[str, Any]
    diagnostic_test_result: dict[str, Any]

    # Repository evidence supplied to the investigation planner.
    parsed_issue: dict[str, Any]
    repo_memory: dict[str, Any]
    retrieved_chunks: list[dict[str, Any]]
    code_graphs: list[dict[str, Any]]
    # Explicit ReadFile results are the only source text passed directly to the
    # patch generator, alongside diagnosis and the selected failure evidence.
    files: dict[str, str]
    external_context: list[dict[str, Any]]

    # Optional MCP sub-loop, including durable pause/resume cursors.
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

    # Controlled local loop audit trail and deterministic budget counters.
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

    # Patch and verification evidence.  These fields, not planner prose, decide
    # whether the terminal status is allowed to become ``verified_success``.
    patch: str
    apply_result: dict[str, Any]
    test_result: dict[str, Any]
    targeted_test_result: dict[str, Any]
    regression_test_result: dict[str, Any]
    verification_result: dict[str, Any]
    reflection: dict[str, Any]
    iterations: int
    max_iterations: int

    # User-facing projection persisted on AgentRun when the graph terminates.
    final_diff: str
    final_summary: str
    status: str

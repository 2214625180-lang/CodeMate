from app.agent.state import FixAgentState


def should_continue(state: FixAgentState) -> str:
    test_result = state.get("test_result") or {}
    if test_result.get("passed"):
        return "final"
    if state.get("iterations", 0) >= state.get("max_iterations", 3):
        return "final"
    return "reflect"


def after_reflect(state: FixAgentState) -> str:
    next_action = (state.get("reflection") or {}).get("next_action")
    if next_action == "read_more_context":
        return "retrieve"
    if next_action == "stop":
        return "final"
    return "generate"


def after_mcp_plan(state: FixAgentState) -> str:
    if state.get("mcp_pending_approval_id"):
        return "pause"
    if (state.get("mcp_tool_plan") or {}).get("calls"):
        return "call"
    return "generate"


def after_mcp_observe(state: FixAgentState) -> str:
    if state.get("mcp_router_round", 0) >= state.get("mcp_max_rounds", 0):
        return "generate"
    if state.get("mcp_call_count", 0) >= state.get("mcp_max_calls", 0):
        return "generate"
    return "plan"


def after_mcp_call(state: FixAgentState) -> str:
    if state.get("mcp_pending_execution_id"):
        return "pause"
    return "observe"


def graph_entry(state: FixAgentState) -> str:
    if state.get("resume_from") == "mcp_call":
        return "call"
    if state.get("resume_from") == "mcp_observe":
        return "observe"
    return "start"


def build_fix_graph(nodes: dict):
    from langgraph.graph import END, StateGraph

    graph = StateGraph(FixAgentState)
    graph.add_node("ParseIssue", nodes["parse_issue"])
    graph.add_node("RetrieveContext", nodes["retrieve_context"])
    graph.add_node("ReadFiles", nodes["read_files"])
    graph.add_node("Diagnose", nodes["diagnose"])
    graph.add_node("PlanMCPTools", nodes["plan_mcp_tools"])
    graph.add_node("CallMCPTools", nodes["call_mcp_tools"])
    graph.add_node("ObserveMCP", nodes["observe_mcp"])
    graph.add_node("PauseForApproval", nodes["pause_for_approval"])
    graph.add_node("PauseForReconciliation", nodes["pause_for_reconciliation"])
    graph.add_node("GeneratePatch", nodes["generate_patch"])
    graph.add_node("ApplyPatch", nodes["apply_patch"])
    graph.add_node("RunTests", nodes["run_tests"])
    graph.add_node("Reflect", nodes["reflect"])
    graph.add_node("FinalAnswer", nodes["final_answer"])

    graph.set_conditional_entry_point(
        graph_entry,
        {"start": "ParseIssue", "call": "CallMCPTools", "observe": "ObserveMCP"},
    )
    graph.add_edge("ParseIssue", "RetrieveContext")
    graph.add_edge("RetrieveContext", "ReadFiles")
    graph.add_edge("ReadFiles", "Diagnose")
    graph.add_edge("Diagnose", "PlanMCPTools")
    graph.add_conditional_edges(
        "PlanMCPTools",
        after_mcp_plan,
        {
            "call": "CallMCPTools",
            "pause": "PauseForApproval",
            "generate": "GeneratePatch",
        },
    )
    graph.add_edge("PauseForApproval", END)
    graph.add_conditional_edges(
        "CallMCPTools",
        after_mcp_call,
        {"pause": "PauseForReconciliation", "observe": "ObserveMCP"},
    )
    graph.add_edge("PauseForReconciliation", END)
    graph.add_conditional_edges(
        "ObserveMCP",
        after_mcp_observe,
        {"plan": "PlanMCPTools", "generate": "GeneratePatch"},
    )
    graph.add_edge("GeneratePatch", "ApplyPatch")
    graph.add_edge("ApplyPatch", "RunTests")
    graph.add_conditional_edges(
        "RunTests",
        should_continue,
        {"reflect": "Reflect", "final": "FinalAnswer"},
    )
    graph.add_conditional_edges(
        "Reflect",
        after_reflect,
        {"retrieve": "RetrieveContext", "generate": "GeneratePatch", "final": "FinalAnswer"},
    )
    graph.add_edge("FinalAnswer", END)
    return graph.compile()

from app.agent.state import FixAgentState
from app.agent.verification import (
    route_after_regression_checks,
    route_after_reproduction,
    route_after_targeted_tests,
)


def after_reflect(state: FixAgentState) -> str:
    if state.get("finish_reason"):
        return "final"
    return "plan"


def after_local_action(state: FixAgentState) -> str:
    route = (state.get("action_outcome") or {}).get("route")
    if route == "generate":
        return "mcp"
    if route == "final":
        return "final"
    return "plan"


def after_patch_generation(state: FixAgentState) -> str:
    if state.get("patch_is_duplicate"):
        return "plan"
    return "apply"


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


def build_fix_graph(nodes: dict, *, checkpointer=None):
    from langgraph.graph import END, StateGraph

    graph = StateGraph(FixAgentState)
    graph.add_node("InspectRepository", nodes["inspect_repository"])
    graph.add_node("ReproduceFailure", nodes["reproduce_failure"])
    graph.add_node("InitializeAgentLoop", nodes["initialize_agent_loop"])
    graph.add_node("PlanNextAction", nodes["plan_next_action"])
    graph.add_node("ExecuteLocalAction", nodes["execute_local_action"])
    graph.add_node("PlanMCPTools", nodes["plan_mcp_tools"])
    graph.add_node("CallMCPTools", nodes["call_mcp_tools"])
    graph.add_node("ObserveMCP", nodes["observe_mcp"])
    graph.add_node("PauseForApproval", nodes["pause_for_approval"])
    graph.add_node("PauseForReconciliation", nodes["pause_for_reconciliation"])
    graph.add_node("GeneratePatch", nodes["generate_patch"])
    graph.add_node("ApplyPatch", nodes["apply_patch"])
    graph.add_node("TargetedTests", nodes["targeted_tests"])
    graph.add_node("RegressionChecks", nodes["regression_checks"])
    graph.add_node("Reflect", nodes["reflect"])
    graph.add_node("FinalAnswer", nodes["final_answer"])

    graph.set_conditional_entry_point(
        graph_entry,
        {"start": "InspectRepository", "call": "CallMCPTools", "observe": "ObserveMCP"},
    )
    graph.add_edge("InspectRepository", "ReproduceFailure")
    graph.add_conditional_edges(
        "ReproduceFailure",
        route_after_reproduction,
        {"continue": "InitializeAgentLoop", "final": "FinalAnswer"},
    )
    graph.add_edge("InitializeAgentLoop", "PlanNextAction")
    graph.add_edge("PlanNextAction", "ExecuteLocalAction")
    graph.add_conditional_edges(
        "ExecuteLocalAction",
        after_local_action,
        {"plan": "PlanNextAction", "mcp": "PlanMCPTools", "final": "FinalAnswer"},
    )
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
    graph.add_conditional_edges(
        "GeneratePatch",
        after_patch_generation,
        {"apply": "ApplyPatch", "plan": "PlanNextAction"},
    )
    graph.add_edge("ApplyPatch", "TargetedTests")
    graph.add_conditional_edges(
        "TargetedTests",
        route_after_targeted_tests,
        {
            "regression": "RegressionChecks",
            "reflect": "Reflect",
            "final": "FinalAnswer",
        },
    )
    graph.add_conditional_edges(
        "RegressionChecks",
        route_after_regression_checks,
        {"reflect": "Reflect", "final": "FinalAnswer"},
    )
    graph.add_conditional_edges(
        "Reflect",
        after_reflect,
        {"plan": "PlanNextAction", "final": "FinalAnswer"},
    )
    graph.add_edge("FinalAnswer", END)
    return graph.compile(checkpointer=checkpointer)

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


def build_fix_graph(nodes: dict):
    from langgraph.graph import END, StateGraph

    graph = StateGraph(FixAgentState)
    graph.add_node("ParseIssue", nodes["parse_issue"])
    graph.add_node("RetrieveContext", nodes["retrieve_context"])
    graph.add_node("ReadFiles", nodes["read_files"])
    graph.add_node("Diagnose", nodes["diagnose"])
    graph.add_node("GeneratePatch", nodes["generate_patch"])
    graph.add_node("ApplyPatch", nodes["apply_patch"])
    graph.add_node("RunTests", nodes["run_tests"])
    graph.add_node("Reflect", nodes["reflect"])
    graph.add_node("FinalAnswer", nodes["final_answer"])

    graph.set_entry_point("ParseIssue")
    graph.add_edge("ParseIssue", "RetrieveContext")
    graph.add_edge("RetrieveContext", "ReadFiles")
    graph.add_edge("ReadFiles", "Diagnose")
    graph.add_edge("Diagnose", "GeneratePatch")
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

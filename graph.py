from langgraph.graph import END, StateGraph

from agents.context_agent import context_agent
from agents.editor_agent import editor_agent
from agents.planner_agent import planner_agent
from agents.pr_agent import pr_agent
from agents.security_cost_agent import security_cost_agent
from agents.validator_agent import validator_agent
from state import InfraAIState


def route_after_planner(state: InfraAIState) -> str:
    intent = state.get("intent")
    return intent if intent in ("question", "ambiguous") else "change"


def route_after_validator(state: InfraAIState) -> str:
    if state["validation_result"].get("valid"):
        return "pass"
    if state.get("retry_count", 0) >= 3:
        return "escalate"
    return "retry"


def build_graph():
    graph = StateGraph(InfraAIState)

    graph.add_node("context", context_agent)
    graph.add_node("planner", planner_agent)
    graph.add_node("editor", editor_agent)
    graph.add_node("validator", validator_agent)
    graph.add_node("security_cost", security_cost_agent)
    graph.add_node("pr", pr_agent)

    graph.set_entry_point("context")
    graph.add_edge("context", "planner")
    graph.add_conditional_edges(
        "planner",
        route_after_planner,
        {"change": "editor", "question": END, "ambiguous": END},
    )
    graph.add_edge("editor", "validator")
    graph.add_conditional_edges(
        "validator",
        route_after_validator,
        {"pass": "security_cost", "retry": "editor", "escalate": END},
    )
    graph.add_edge("security_cost", "pr")
    graph.add_edge("pr", END)

    return graph.compile()


graph = build_graph()

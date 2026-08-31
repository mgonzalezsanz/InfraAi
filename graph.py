from functools import partial

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


def build_graph(
    repo_path=None,
    planner_llm=None,
    editor_llm=None,
    validate_fn=None,
    plan_fn=None,
    checkov_fn=None,
    infracost_fn=None,
    target_repo=None,
    open_pr_fn=None,
):
    graph = StateGraph(InfraAIState)

    graph.add_node("context", partial(context_agent, repo_path=repo_path))
    graph.add_node("planner", partial(planner_agent, llm=planner_llm))
    graph.add_node("editor", partial(editor_agent, llm=editor_llm))
    graph.add_node("validator", partial(validator_agent, validate=validate_fn, plan=plan_fn))
    graph.add_node("security_cost", partial(security_cost_agent, checkov=checkov_fn, infracost=infracost_fn))
    graph.add_node("pr", partial(pr_agent, target_repo=target_repo, open_pr=open_pr_fn))

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

from functools import partial

from langgraph.graph import END, StateGraph

from agents.context_agent import context_agent
from agents.editor_agent import editor_agent
from agents.planner_agent import planner_agent
from agents.pr_agent import pr_agent
from agents.security_cost_agent import security_cost_agent
from agents.validator_agent import validator_agent
from state import InfraAIState, validation_errors


def route_after_planner(state: InfraAIState) -> str:
    intent = state.get("intent")
    return intent if intent in ("question", "ambiguous") else "change"


def route_after_validator(state: InfraAIState) -> str:
    if state["validation_result"].get("valid"):
        return "pass"
    if state.get("retry_count", 0) >= 3:
        return "escalate"
    return "retry"


def escalate(state: InfraAIState) -> dict:
    """Terminal node: the editor/validator loop failed 3 times. Hand off to a human
    — with the last attempt's terraform errors — instead of looping forever."""
    errors = validation_errors(state.get("validation_result", {}))
    detail = "\n".join(f"- {e}" for e in errors) if errors else "- (no specific terraform error was captured)"
    return {
        "status": "needs_human",
        "agent_message": (
            "I couldn't reach a valid Terraform plan after 3 attempts, so I'm handing this "
            "to a human. The last attempt failed with:\n\n"
            f"{detail}\n\n"
            "Start a new conversation with a more specific request."
        ),
    }


def build_graph(
    repo_path=None,
    target_repo=None,
    ref="main",
    api_key=None,
    branch_key=None,
    planner_llm=None,
    editor_llm=None,
    validate_fn=None,
    plan_fn=None,
    checkov_fn=None,
    infracost_fn=None,
    open_pr_fn=None,
):
    graph = StateGraph(InfraAIState)

    graph.add_node("context", partial(context_agent, repo_path=repo_path, target_repo=target_repo, ref=ref))
    graph.add_node("planner", partial(planner_agent, llm=planner_llm, api_key=api_key))
    graph.add_node("editor", partial(editor_agent, llm=editor_llm, api_key=api_key))
    graph.add_node("validator", partial(validator_agent, validate=validate_fn, plan=plan_fn))
    graph.add_node("security_cost", partial(security_cost_agent, checkov=checkov_fn, infracost=infracost_fn))
    graph.add_node("pr", partial(pr_agent, target_repo=target_repo, open_pr=open_pr_fn, branch_key=branch_key))
    graph.add_node("escalate", escalate)

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
        {"pass": "security_cost", "retry": "editor", "escalate": "escalate"},
    )
    graph.add_edge("security_cost", "pr")
    graph.add_edge("pr", END)
    graph.add_edge("escalate", END)

    return graph.compile()


graph = build_graph()

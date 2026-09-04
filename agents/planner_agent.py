from state import InfraAIState
from tools.llm import get_planner_llm

_STATUS_BY_INTENT = {
    "change": "editing",
    "question": "answered",
    "ambiguous": "needs_clarification",
}


def _build_prompt(user_request: str, repo_context: dict) -> str:
    variables = repo_context.get('variables', [])
    has_prefix = 'resource_name_prefix' in variables
    prefix_note = (
        "When naming resources (bucket names, role names, etc.), prepend the "
        "value of var.resource_name_prefix to ensure they stay within the "
        "deployment scope. E.g., bucket should be named \"${var.resource_name_prefix}-app-logs\", not \"app-logs\".\n\n"
        if has_prefix else ""
    )

    return (
        "You are the Planner agent in InfraAI, a system that turns natural-language "
        "infrastructure requests into reviewed Terraform changes.\n\n"
        "Be reliable and trustworthy: base every answer and plan strictly on the repo "
        "context given below — never invent resources, variables, or state that aren't "
        "listed there. If you're not confident a request maps cleanly to one intent, "
        "classify it as \"ambiguous\" rather than guessing.\n\n"
        f"{prefix_note}"
        "Classify the user's request as exactly one of:\n"
        '- "change": a concrete infrastructure change to make. Produce a change_plan: '
        "one or more file-level steps (file, action, detail).\n"
        '- "question": a question about the existing infrastructure, answerable from the '
        "repo context below. Produce an agent_message with the answer.\n"
        '- "ambiguous": too vague to plan or answer. Produce an agent_message asking a '
        "clarifying question.\n\n"
        "Existing repo context:\n"
        f"- files: {list(repo_context.get('files', {}).keys())}\n"
        f"- resources: {repo_context.get('resources', [])}\n"
        f"- variables: {variables}\n"
        f"- conventions: {repo_context.get('conventions', {})}\n\n"
        f"User request: {user_request}"
    )


def planner_agent(state: InfraAIState, *, llm=None) -> dict:
    """Classifies intent and produces a plan, answer, or clarifying question."""
    llm = llm or get_planner_llm()
    result = llm.invoke(_build_prompt(state["user_request"], state.get("repo_context", {})))

    update = {"intent": result.intent, "status": _STATUS_BY_INTENT[result.intent]}
    if result.intent == "change":
        update["change_plan"] = [step.model_dump() for step in result.change_plan]
    else:
        update["agent_message"] = result.agent_message
    return update

import re

from state import InfraAIState
from tools.llm import get_planner_llm

_STATUS_BY_INTENT = {
    "change": "editing",
    "question": "answered",
    "ambiguous": "needs_clarification",
}

# The model sometimes leaks its structured-output scaffolding into a string field
# (e.g. a trailing "</agent_message> </invoke>"). Strip a trailing run of tags
# whose names are known scaffolding words — nothing a real answer would end with.
_SCAFFOLD_TAIL = re.compile(
    r"(?:\s*</?(?:antml:)?(?:invoke|parameter|function_calls|agent_message|change_plan|tool_call)\b[^>]*>)+\s*$",
    re.IGNORECASE,
)


def _clean_message(text: str | None) -> str | None:
    if not text:
        return text
    stripped = _SCAFFOLD_TAIL.sub("", text).strip()
    return stripped or text


def _resources_by_file(repo_context: dict) -> str:
    resource_files = repo_context.get("resource_files", {})
    if not resource_files:
        return "  (no resources defined yet)"
    return "\n".join(f"  - {path}: {', '.join(addrs)}" for path, addrs in resource_files.items())


def _history_block(messages: list[dict]) -> str:
    if len(messages) <= 1:
        return ""
    thread = "\n".join(f"{m['role']}: {m['content']}" for m in messages[:-1])
    return (
        f"Conversation so far:\n{thread}\n\n"
        "The user's latest message below continues this conversation — it may answer "
        "a question you asked or add detail. Fold it into your plan or answer; don't "
        "ask again for something already given above.\n\n"
    )


def _build_prompt(messages: list[dict], repo_context: dict) -> str:
    user_request = messages[-1]["content"] if messages else ""
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
        f"{_history_block(messages)}"
        f"{prefix_note}"
        "File layout: group resources into a file named for their AWS service — an "
        "`aws_s3_bucket` (and its versioning/lifecycle) goes in `s3.tf`, an "
        "`aws_iam_role` in `iam.tf`, an `aws_lambda_function` in `lambda.tf`, and so "
        "on. Reuse the service file if it already exists in the layout below; name a "
        "new one if it doesn't. Don't pile new resources into `main.tf`. Each "
        "change_plan step's `file` is that target file.\n\n"
        "Classify the user's request as exactly one of:\n"
        '- "change": a concrete infrastructure change to make. Produce a change_plan: '
        "one or more file-level steps (file, action, detail).\n"
        '- "question": a question about the existing infrastructure, answerable from the '
        "repo context below. Produce an agent_message with the answer.\n"
        '- "ambiguous": too vague to plan or answer. Produce an agent_message asking a '
        "clarifying question.\n\n"
        "agent_message is plain prose or short Markdown (a sentence or two, or a bullet "
        "list) — never wrap it in XML/HTML tags.\n\n"
        "Existing repo context:\n"
        f"- files: {list(repo_context.get('files', {}).keys())}\n"
        f"- resources by file:\n{_resources_by_file(repo_context)}\n"
        f"- variables: {variables}\n"
        f"- conventions: {repo_context.get('conventions', {})}\n\n"
        f"User request: {user_request}"
    )


def planner_agent(state: InfraAIState, *, llm=None, api_key=None) -> dict:
    """Classifies intent and produces a plan, answer, or clarifying question."""
    llm = llm or get_planner_llm(api_key)
    messages = state.get("messages") or [{"role": "user", "content": state["user_request"]}]
    result = llm.invoke(_build_prompt(messages, state.get("repo_context", {})))

    update = {"intent": result.intent, "status": _STATUS_BY_INTENT[result.intent]}
    if result.intent == "change":
        update["change_plan"] = [step.model_dump() for step in result.change_plan]
    else:
        update["agent_message"] = _clean_message(result.agent_message)
    return update

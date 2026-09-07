import os

from dotenv import load_dotenv

from state import InfraAIState
from tools.github_tools import branch_name_for
from tools.github_tools import open_or_update_pr as _open_or_update_pr

try:
    load_dotenv()
except UnicodeDecodeError:
    pass  # malformed .env (e.g. wrong encoding) shouldn't crash imports

DEFAULT_TARGET_REPO = os.environ.get("INFRAI_TARGET_REPO")


def _budget_note(cost: dict) -> str:
    ceiling = cost.get("budget_ceiling_usd_per_month")
    if ceiling is None:
        return "no budget ceiling configured"
    if cost.get("within_budget"):
        return f"within the ${ceiling:g}/mo ceiling"
    return f"**⚠️ OVER the ${ceiling:g}/mo ceiling**"


def _tf_plan_line(state: InfraAIState) -> str:
    summary = (state.get("validation_result", {}).get("plan") or {}).get("summary", {})
    return (
        f"{summary.get('add', 0)} to add, "
        f"{summary.get('change', 0)} to change, "
        f"{summary.get('destroy', 0)} to destroy"
    )


def _pr_body(state: InfraAIState) -> str:
    findings = state.get("security_findings", [])
    findings_desc = "\n".join(f"- `{f['check_id']}` {f['check_name']} ({f['resource']})" for f in findings) or "None"
    plan_desc = "\n".join(f"- {s['file']}: {s['action']} — {s['detail']}" for s in state.get("change_plan", []))
    cost = state.get("cost_estimate", {})

    return (
        f"**Request:** {state['user_request']}\n\n"
        f"**Plan:**\n{plan_desc}\n\n"
        f"**Terraform plan:** {_tf_plan_line(state)}\n\n"
        f"**Diff:**\n```diff\n{state.get('diff', '')}\n```\n\n"
        f"**Security & policy findings:**\n{findings_desc}\n\n"
        f"**Cost delta:** ${cost.get('delta_usd', 0):.2f}/mo — {_budget_note(cost)}\n\n"
        "_Opened by InfraAI. This branch is rebuilt from the base branch on every "
        "run — review the change in this PR, and don't push commits to the branch "
        "(they'll be overwritten)._"
    )


def pr_agent(state: InfraAIState, *, target_repo: str | None = None, open_pr=None) -> dict:
    """Opens a branch + PR with a full summary, idempotent on repeated requests."""
    open_pr = open_pr or _open_or_update_pr
    branch = branch_name_for(state["user_request"])

    url = open_pr(
        repo=target_repo or DEFAULT_TARGET_REPO,
        branch=branch,
        files=state.get("repo_context", {}).get("files", {}),
        title=f"InfraAI: {state['user_request']}"[:72],
        body=_pr_body(state),
        base_files=state.get("base_files") or None,
    )

    return {"pr_url": url, "status": "pr_open"}

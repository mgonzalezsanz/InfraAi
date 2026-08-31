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


def _pr_body(state: InfraAIState) -> str:
    findings = state.get("security_findings", [])
    findings_desc = "\n".join(f"- `{f['check_id']}` {f['check_name']} ({f['resource']})" for f in findings) or "None"
    plan_desc = "\n".join(f"- {s['file']}: {s['action']} — {s['detail']}" for s in state.get("change_plan", []))
    cost = state.get("cost_estimate", {})

    return (
        f"**Request:** {state['user_request']}\n\n"
        f"**Plan:**\n{plan_desc}\n\n"
        f"**Diff:**\n```diff\n{state.get('diff', '')}\n```\n\n"
        f"**Security findings (Checkov):**\n{findings_desc}\n\n"
        f"**Cost delta:** ${cost.get('delta_usd', 0):.2f}/mo "
        f"({'within' if cost.get('within_budget') else 'over'} budget)\n\n"
        "_Opened by InfraAI._"
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
    )

    return {"pr_url": url, "status": "pr_open"}

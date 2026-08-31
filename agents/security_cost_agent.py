from state import InfraAIState
from tools.security_tools import run_checkov, run_infracost


def security_cost_agent(state: InfraAIState, *, checkov=None, infracost=None) -> dict:
    """Runs Checkov + Infracost against the diffed files."""
    checkov = checkov or run_checkov
    infracost = infracost or run_infracost
    files = state.get("repo_context", {}).get("files", {})

    return {
        "security_findings": checkov(files),
        "cost_estimate": infracost(files),
        "status": "ready_for_pr",
    }

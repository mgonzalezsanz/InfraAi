from state import InfraAIState


def security_cost_agent(state: InfraAIState) -> dict:
    """Phase 0 stub. Real version runs Checkov/tfsec + Infracost against the diff (FR-5)."""
    return {
        "security_findings": [],
        "cost_estimate": {"delta_usd": 0.0, "within_budget": True},
        "status": "ready_for_pr",
    }

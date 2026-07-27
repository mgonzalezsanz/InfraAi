from state import InfraAIState


def pr_agent(state: InfraAIState) -> dict:
    """Phase 0 stub. Real version opens/updates a GitHub branch + PR idempotently (FR-6, FR-7)."""
    return {
        "pr_url": "https://github.com/mock-org/mock-target-repo/pull/1",
        "status": "pr_open",
    }

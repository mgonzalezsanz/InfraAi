from state import InfraAIState


def validator_agent(state: InfraAIState) -> dict:
    """Phase 0 stub. Always reports a passing plan; real version runs terraform validate/plan
    against a temp checkout using infrai-plan-role, and loops back to the editor on failure (FR-4)."""
    return {
        "validation_result": {"valid": True, "plan_summary": "mock plan: 1 to add, 0 to change, 0 to destroy"},
        "status": "scanning",
    }

from state import InfraAIState


def editor_agent(state: InfraAIState) -> dict:
    """Phase 0 stub. Real version produces a minimal diff via LLM, re-invoked on validator failure (FR-3)."""
    plan = state.get("change_plan", [])
    diff = "\n".join(f"+ # mock change for: {step['detail']}" for step in plan) or "+ # mock diff"
    return {"diff": diff, "status": "validating"}

from state import InfraAIState


def planner_agent(state: InfraAIState) -> dict:
    """Phase 0 stub. Classifies intent with simple heuristics; real version uses an LLM (FR-2, FR-12)."""
    request = state["user_request"].strip()

    if not request or len(request.split()) < 3:
        return {
            "intent": "ambiguous",
            "agent_message": "Can you give me more detail — which resource, and what should change?",
            "status": "needs_clarification",
        }

    if request.endswith("?"):
        return {
            "intent": "question",
            "agent_message": f"(mock answer) Based on repo_context, here's what I found for: {request}",
            "status": "answered",
        }

    return {
        "intent": "change",
        "change_plan": [{"file": "main.tf", "action": "add_resource", "detail": request}],
        "status": "editing",
    }

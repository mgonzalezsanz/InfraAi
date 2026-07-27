from graph import build_graph, route_after_planner, route_after_validator
from state import create_initial_state


def test_change_request_reaches_pr_open():
    result = build_graph().invoke(create_initial_state("Add an S3 bucket with versioning enabled"))
    assert result["status"] == "pr_open"
    assert result["pr_url"]
    assert result["intent"] == "change"


def test_question_request_ends_answered_without_pr():
    result = build_graph().invoke(create_initial_state("What instance type is the app server?"))
    assert result["status"] == "answered"
    assert result["agent_message"]
    assert result["pr_url"] is None


def test_ambiguous_request_ends_needs_clarification():
    result = build_graph().invoke(create_initial_state("fix it"))
    assert result["status"] == "needs_clarification"
    assert result["agent_message"]
    assert result["pr_url"] is None


def test_route_after_planner_change():
    assert route_after_planner({"intent": "change"}) == "change"


def test_route_after_planner_question():
    assert route_after_planner({"intent": "question"}) == "question"


def test_route_after_planner_ambiguous():
    assert route_after_planner({"intent": "ambiguous"}) == "ambiguous"


def test_route_after_validator_pass():
    assert route_after_validator({"validation_result": {"valid": True}, "retry_count": 0}) == "pass"


def test_route_after_validator_retry_below_cap():
    assert route_after_validator({"validation_result": {"valid": False}, "retry_count": 1}) == "retry"


def test_route_after_validator_escalates_at_retry_cap():
    assert route_after_validator({"validation_result": {"valid": False}, "retry_count": 3}) == "escalate"

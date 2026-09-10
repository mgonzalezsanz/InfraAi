from graph import build_graph, route_after_planner, route_after_validator
from state import create_initial_state
from tools.llm import ChangeStep, EditorOutput, FileEdit, PlannerOutput


class _FakeLLM:
    """Stands in for a real ChatAnthropic structured-output call in tests."""

    def __init__(self, result):
        self._result = result

    def invoke(self, prompt):
        return self._result


def test_change_request_reaches_pr_open():
    planner_llm = _FakeLLM(
        PlannerOutput(
            intent="change",
            change_plan=[ChangeStep(file="main.tf", action="add_resource", detail="add versioning")],
        )
    )
    editor_llm = _FakeLLM(EditorOutput(file_edits=[FileEdit(path="main.tf", content="# updated\n")]))
    graph = build_graph(
        planner_llm=planner_llm,
        editor_llm=editor_llm,
        validate_fn=lambda files: {"valid": True, "errors": []},
        plan_fn=lambda files: {"valid": True, "summary": {"add": 1, "change": 0, "destroy": 0}, "errors": []},
        checkov_fn=lambda files: [],
        infracost_fn=lambda files: {"delta_usd": 0.0, "within_budget": True},
        open_pr_fn=lambda **kwargs: "https://github.com/mock-org/mock-repo/pull/1",
    )

    result = graph.invoke(create_initial_state("Add an S3 bucket with versioning enabled"))
    assert result["status"] == "pr_open"
    assert result["pr_url"]
    assert result["intent"] == "change"


def test_question_request_ends_answered_without_pr():
    planner_llm = _FakeLLM(PlannerOutput(intent="question", agent_message="It's eu-west-3."))
    graph = build_graph(planner_llm=planner_llm)

    result = graph.invoke(create_initial_state("What instance type is the app server?"))
    assert result["status"] == "answered"
    assert result["agent_message"]
    assert result["pr_url"] is None


def test_ambiguous_request_ends_needs_clarification():
    planner_llm = _FakeLLM(PlannerOutput(intent="ambiguous", agent_message="Which resource do you mean?"))
    graph = build_graph(planner_llm=planner_llm)

    result = graph.invoke(create_initial_state("fix it"))
    assert result["status"] == "needs_clarification"
    assert result["agent_message"]
    assert result["pr_url"] is None


def test_change_request_escalates_to_needs_human_after_three_failed_validations():
    planner_llm = _FakeLLM(
        PlannerOutput(
            intent="change",
            change_plan=[ChangeStep(file="main.tf", action="add_resource", detail="add a bucket")],
        )
    )
    editor_llm = _FakeLLM(EditorOutput(file_edits=[FileEdit(path="main.tf", content="# still broken\n")]))
    graph = build_graph(
        planner_llm=planner_llm,
        editor_llm=editor_llm,
        validate_fn=lambda files: {"valid": False, "errors": ["syntax error near line 1"]},
        open_pr_fn=lambda **kwargs: "should-never-be-called",
    )

    result = graph.invoke(create_initial_state("Add a bucket"))
    assert result["status"] == "needs_human"
    assert result["retry_count"] == 3
    assert result["pr_url"] is None
    # the handoff carries the last attempt's terraform error, not just a bare status
    assert "syntax error near line 1" in result["agent_message"]


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

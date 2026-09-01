from agents.context_agent import context_agent
from agents.editor_agent import editor_agent
from agents.planner_agent import planner_agent
from agents.pr_agent import pr_agent
from agents.security_cost_agent import security_cost_agent
from agents.validator_agent import validator_agent
from state import create_initial_state
from tools.llm import ChangeStep, EditorOutput, FileEdit, PlannerOutput


class _FakeLLM:
    """Stands in for a real ChatAnthropic structured-output call in tests."""

    def __init__(self, result):
        self._result = result

    def invoke(self, prompt):
        return self._result


def test_context_agent_returns_repo_context():
    result = context_agent(create_initial_state("anything"))
    assert "aws_s3_bucket.app_data" in result["repo_context"]["resources"]
    assert "region" in result["repo_context"]["variables"]


def test_planner_agent_classifies_change_intent():
    fake = _FakeLLM(
        PlannerOutput(
            intent="change",
            change_plan=[ChangeStep(file="main.tf", action="add_resource", detail="add a bucket")],
        )
    )
    result = planner_agent(create_initial_state("Add a new S3 bucket for logs"), llm=fake)
    assert result["intent"] == "change"
    assert result["status"] == "editing"
    assert result["change_plan"]


def test_planner_agent_classifies_question_intent():
    fake = _FakeLLM(PlannerOutput(intent="question", agent_message="It's eu-west-3."))
    result = planner_agent(create_initial_state("What region is this deployed in?"), llm=fake)
    assert result["intent"] == "question"
    assert result["status"] == "answered"
    assert result["agent_message"]


def test_planner_agent_classifies_ambiguous_intent():
    fake = _FakeLLM(PlannerOutput(intent="ambiguous", agent_message="Which resource do you mean?"))
    result = planner_agent(create_initial_state("help"), llm=fake)
    assert result["intent"] == "ambiguous"
    assert result["status"] == "needs_clarification"
    assert result["agent_message"]


def test_editor_agent_produces_diff_from_plan():
    state = create_initial_state("Add a bucket")
    state["repo_context"] = {"files": {"main.tf": 'resource "aws_s3_bucket" "old" {}\n'}}
    state["change_plan"] = [{"file": "main.tf", "action": "add_resource", "detail": "Add a bucket"}]
    fake = _FakeLLM(
        EditorOutput(
            file_edits=[
                FileEdit(
                    path="main.tf",
                    content='resource "aws_s3_bucket" "old" {}\nresource "aws_s3_bucket" "new" {}\n',
                )
            ]
        )
    )
    result = editor_agent(state, llm=fake)
    assert result["status"] == "validating"
    assert "new" in result["diff"]
    assert "new" in result["repo_context"]["files"]["main.tf"]


def test_validator_agent_reports_valid_plan():
    fake_validate = lambda files: {"valid": True, "errors": []}
    fake_plan = lambda files: {"valid": True, "summary": {"add": 1, "change": 0, "destroy": 0}, "errors": []}
    result = validator_agent(create_initial_state("Add a bucket"), validate=fake_validate, plan=fake_plan)
    assert result["validation_result"]["valid"] is True
    assert result["status"] == "scanning"


def test_validator_agent_increments_retry_on_invalid_syntax():
    state = create_initial_state("Add a bucket")
    result = validator_agent(state, validate=lambda files: {"valid": False, "errors": ["bad syntax"]})
    assert result["validation_result"]["valid"] is False
    assert result["retry_count"] == 1
    assert result["status"] == "editing"


def test_validator_agent_increments_retry_on_plan_failure():
    fake_validate = lambda files: {"valid": True, "errors": []}
    fake_plan = lambda files: {"valid": False, "summary": {}, "errors": ["AccessDenied"]}
    result = validator_agent(create_initial_state("Add a bucket"), validate=fake_validate, plan=fake_plan)
    assert result["validation_result"]["valid"] is False
    assert result["retry_count"] == 1
    assert result["status"] == "editing"


def test_security_cost_agent_returns_findings_and_cost():
    fake_checkov = lambda files: [{"check_id": "CKV_AWS_1", "check_name": "mock check", "resource": "x"}]
    fake_infracost = lambda files: {"delta_usd": 4.2, "within_budget": True}
    result = security_cost_agent(
        create_initial_state("Add a bucket"), checkov=fake_checkov, infracost=fake_infracost
    )
    assert result["security_findings"]
    assert result["cost_estimate"]["delta_usd"] == 4.2
    assert result["status"] == "ready_for_pr"


def test_pr_agent_returns_pr_url():
    fake_open_pr = lambda **kwargs: "https://github.com/mock-org/mock-repo/pull/1"
    result = pr_agent(create_initial_state("Add a bucket"), open_pr=fake_open_pr)
    assert result["pr_url"].startswith("https://")
    assert result["status"] == "pr_open"

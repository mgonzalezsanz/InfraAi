from agents.context_agent import context_agent
from agents.editor_agent import editor_agent
from agents.planner_agent import _build_prompt, planner_agent
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


def test_context_agent_loads_target_repo_config():
    result = context_agent(create_initial_state("anything"))
    assert result["config"]["budget_ceiling_usd_per_month"] == 100
    assert "aws_s3_bucket" in result["config"]["allowed_resource_types"]


def test_context_agent_reads_target_repo_over_the_api(monkeypatch):
    import agents.context_agent as ca

    fetched = {
        "main.tf": 'resource "aws_s3_bucket" "logs" {\n  bucket = "x"\n}\n',
        "infrai.config.yaml": "budget_ceiling_usd_per_month: 7\nallowed_resource_types: [aws_s3_bucket]\n",
    }
    monkeypatch.setattr(ca, "fetch_repo_files", lambda repo, ref: fetched)

    result = ca.context_agent(create_initial_state("x"), target_repo="acme/infra")
    assert "aws_s3_bucket.logs" in result["repo_context"]["resources"]
    assert result["config"]["budget_ceiling_usd_per_month"] == 7
    assert "infrai.config.yaml" not in result["repo_context"]["files"]  # never in the terraform fileset


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


def test_planner_prompt_instructs_resource_name_prefix_when_configured():
    prompt = _build_prompt("add a bucket", {"variables": ["resource_name_prefix", "region"]})
    assert "var.resource_name_prefix" in prompt


def test_planner_prompt_omits_prefix_instruction_when_not_configured():
    prompt = _build_prompt("add a bucket", {"variables": ["region"]})
    assert "resource_name_prefix" not in prompt


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
    fake_infracost = lambda files: {"delta_usd": 4.2}
    result = security_cost_agent(
        create_initial_state("Add a bucket"), checkov=fake_checkov, infracost=fake_infracost
    )
    assert result["security_findings"]
    assert result["cost_estimate"]["delta_usd"] == 4.2
    assert result["status"] == "ready_for_pr"


def _state_with(config, files=None, resources=None):
    state = create_initial_state("Add something")
    state["config"] = config
    state["repo_context"] = {"files": files or {}, "resources": resources or []}
    return state


def test_security_cost_agent_flags_over_budget():
    result = security_cost_agent(
        _state_with({"budget_ceiling_usd_per_month": 10}),
        checkov=lambda f: [],
        infracost=lambda f: {"delta_usd": 42.0},
    )
    assert result["cost_estimate"]["within_budget"] is False
    assert result["cost_estimate"]["budget_ceiling_usd_per_month"] == 10


def test_security_cost_agent_within_budget():
    result = security_cost_agent(
        _state_with({"budget_ceiling_usd_per_month": 100}),
        checkov=lambda f: [],
        infracost=lambda f: {"delta_usd": 42.0},
    )
    assert result["cost_estimate"]["within_budget"] is True


def test_security_cost_agent_no_config_is_permissive():
    result = security_cost_agent(
        _state_with({}),
        checkov=lambda f: [],
        infracost=lambda f: {"delta_usd": 9999.0},
    )
    assert result["cost_estimate"]["within_budget"] is True
    assert result["security_findings"] == []


def test_security_cost_agent_flags_resource_type_not_in_allowlist():
    files = {
        "main.tf": (
            'resource "aws_s3_bucket" "app" {\n  bucket = "x"\n}\n'
            'resource "aws_instance" "web" {\n  ami = "ami-1"\n  instance_type = "t3.micro"\n}\n'
        )
    }
    result = security_cost_agent(
        _state_with(
            {"allowed_resource_types": ["aws_s3_bucket"]},
            files=files,
            resources=["aws_s3_bucket.app"],  # aws_instance is new
        ),
        checkov=lambda f: [],
        infracost=lambda f: {"delta_usd": 0.0},
    )
    ids = [f["check_id"] for f in result["security_findings"]]
    assert ids == ["INFRAI_ALLOWED_RESOURCE_TYPES"]
    assert result["security_findings"][0]["resource"] == "aws_instance"


def test_security_cost_agent_ignores_preexisting_disallowed_types():
    files = {"main.tf": 'resource "aws_instance" "web" {\n  ami = "ami-1"\n  instance_type = "t3.micro"\n}\n'}
    result = security_cost_agent(
        _state_with(
            {"allowed_resource_types": ["aws_s3_bucket"]},
            files=files,
            resources=["aws_instance.web"],  # already there before this change
        ),
        checkov=lambda f: [],
        infracost=lambda f: {"delta_usd": 0.0},
    )
    assert result["security_findings"] == []


def test_pr_agent_returns_pr_url():
    fake_open_pr = lambda **kwargs: "https://github.com/mock-org/mock-repo/pull/1"
    result = pr_agent(create_initial_state("Add a bucket"), open_pr=fake_open_pr)
    assert result["pr_url"].startswith("https://")
    assert result["status"] == "pr_open"

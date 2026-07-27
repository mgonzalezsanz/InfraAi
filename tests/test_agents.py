from agents.context_agent import context_agent
from agents.editor_agent import editor_agent
from agents.planner_agent import planner_agent
from agents.pr_agent import pr_agent
from agents.security_cost_agent import security_cost_agent
from agents.validator_agent import validator_agent
from state import create_initial_state


def test_context_agent_returns_repo_context():
    result = context_agent(create_initial_state("anything"))
    assert "resources" in result["repo_context"]


def test_planner_agent_classifies_change_intent():
    result = planner_agent(create_initial_state("Add a new S3 bucket for logs"))
    assert result["intent"] == "change"
    assert result["change_plan"]


def test_planner_agent_classifies_question_intent():
    result = planner_agent(create_initial_state("What region is this deployed in?"))
    assert result["intent"] == "question"
    assert result["agent_message"]


def test_planner_agent_classifies_ambiguous_intent():
    result = planner_agent(create_initial_state("help"))
    assert result["intent"] == "ambiguous"
    assert result["agent_message"]


def test_editor_agent_produces_diff_from_plan():
    state = create_initial_state("Add a bucket")
    state["change_plan"] = [{"file": "main.tf", "action": "add_resource", "detail": "Add a bucket"}]
    result = editor_agent(state)
    assert result["diff"]


def test_validator_agent_reports_valid_plan():
    result = validator_agent(create_initial_state("Add a bucket"))
    assert result["validation_result"]["valid"] is True


def test_security_cost_agent_returns_findings_and_cost():
    result = security_cost_agent(create_initial_state("Add a bucket"))
    assert result["security_findings"] == []
    assert "delta_usd" in result["cost_estimate"]


def test_pr_agent_returns_pr_url():
    result = pr_agent(create_initial_state("Add a bucket"))
    assert result["pr_url"].startswith("https://")

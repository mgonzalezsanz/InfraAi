"""Sanity checks on templates/target-repo-setup/ — files this repo SHIPS but never
executes. These only validate syntax/shape, nothing here runs the workflow or
touches AWS."""

import json
from pathlib import Path

import yaml

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "target-repo-setup"


def test_apply_role_mutating_access_is_resource_scoped():
    policy = json.loads((TEMPLATE_DIR / "apply-role.json").read_text())
    mutating_statement = next(s for s in policy["Statement"] if s["Sid"] == "ScopedMutatingAccess")

    assert mutating_statement["Effect"] == "Allow"
    assert mutating_statement["Action"]  # has at least one mutating action
    assert all(a.startswith("s3:") for a in mutating_statement["Action"])  # S3 only
    # scoped to a name prefix, never a blanket allow on every bucket. (Not tag-
    # scoped: aws:ResourceTag can't be evaluated for s3:CreateBucket.)
    resources = mutating_statement["Resource"]
    assert isinstance(resources, list) and resources
    assert all(r != "*" and r.startswith("arn:aws:s3:::") for r in resources)


def test_apply_role_state_backend_statement_is_scoped():
    policy = json.loads((TEMPLATE_DIR / "apply-role.json").read_text())
    state_statement = next(s for s in policy["Statement"] if s["Sid"] == "TerraformStateBackend")

    assert state_statement["Effect"] == "Allow"
    # write access to the state object only — never a blanket allow
    assert state_statement["Resource"] != "*"
    assert set(state_statement["Action"]) <= {"s3:PutObject", "s3:DeleteObject"}


def test_plan_workflow_is_automatic_ungated_and_read_only():
    workflow = yaml.safe_load((TEMPLATE_DIR / "plan.yml").read_text())

    assert list(workflow[True].keys()) == ["push"]  # PyYAML parses bare `on:` as boolean True
    assert workflow[True]["push"]["branches"] == ["main"]
    assert workflow["permissions"]["id-token"] == "write"  # OIDC, no static keys

    plan = workflow["jobs"]["plan"]
    assert "environment" not in plan  # ungated -> GitHub issues a `ref:` subject
    steps = yaml.safe_dump(plan["steps"])
    assert "INFRAI_PLAN_ROLE_ARN" in steps
    assert "INFRAI_APPLY_ROLE_ARN" not in steps  # the mutating role never reaches the plan job
    assert "-lock=false" in steps  # plan never writes state -> plan role stays read-only


def test_apply_workflow_is_manual_and_applies_the_reviewed_plan():
    workflow = yaml.safe_load((TEMPLATE_DIR / "apply.yml").read_text())

    assert list(workflow[True].keys()) == ["workflow_dispatch"]  # the human dispatch is the gate
    assert workflow["permissions"]["id-token"] == "write"

    apply = workflow["jobs"]["apply"]
    assert apply["environment"] == "production"  # scopes the OIDC sub + pins to main
    steps = yaml.safe_dump(apply["steps"])
    assert "INFRAI_APPLY_ROLE_ARN" in steps
    assert "plan-artifact/tfplan" in steps  # applies the downloaded plan, not a fresh one
    assert "-auto-approve" not in steps
    assert "stale" in steps.lower()  # has the "main moved" guard


def test_plan_and_apply_pin_the_same_terraform_version():
    plan = yaml.safe_load((TEMPLATE_DIR / "plan.yml").read_text())
    apply = yaml.safe_load((TEMPLATE_DIR / "apply.yml").read_text())

    def tf_versions(wf):
        return {
            step["with"]["terraform_version"]
            for job in wf["jobs"].values()
            for step in job["steps"]
            if isinstance(step.get("uses"), str)
            and step["uses"].startswith("hashicorp/setup-terraform")
        }

    versions = tf_versions(plan) | tf_versions(apply)
    assert len(versions) == 1, f"plan/apply must pin one Terraform version, got {versions}"


def test_config_example_has_budget_and_allowed_resources():
    config = yaml.safe_load((TEMPLATE_DIR / "infrai.config.yaml.example").read_text())

    assert isinstance(config["budget_ceiling_usd_per_month"], (int, float))
    assert config["allowed_resource_types"]

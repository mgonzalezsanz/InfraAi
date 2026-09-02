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


def test_apply_workflow_triggers_only_on_main_push():
    workflow = yaml.safe_load((TEMPLATE_DIR / "apply.yml").read_text())

    assert list(workflow[True].keys()) == ["push"]  # PyYAML parses bare `on:` as boolean True
    assert workflow[True]["push"]["branches"] == ["main"]
    assert workflow["permissions"]["id-token"] == "write"  # OIDC, no static keys
    assert workflow["jobs"]["apply"]["environment"] == "production"


def test_config_example_has_budget_and_allowed_resources():
    config = yaml.safe_load((TEMPLATE_DIR / "infrai.config.yaml.example").read_text())

    assert isinstance(config["budget_ceiling_usd_per_month"], (int, float))
    assert config["allowed_resource_types"]

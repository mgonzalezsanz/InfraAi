"""Sanity checks on templates/target-repo-setup/ — files this repo SHIPS but never
executes. These only validate syntax/shape, nothing here runs the workflow or
touches AWS."""

import json
from pathlib import Path

import yaml

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "target-repo-setup"


def test_apply_role_policy_is_valid_and_tag_scoped():
    policy = json.loads((TEMPLATE_DIR / "apply-role.json").read_text())
    mutating_statement = next(s for s in policy["Statement"] if s["Sid"] == "ScopedMutatingAccess")

    assert mutating_statement["Effect"] == "Allow"
    assert mutating_statement["Action"]  # has at least one mutating action
    # apply-role must be scoped, not a blanket allow on every resource
    assert "Condition" in mutating_statement


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

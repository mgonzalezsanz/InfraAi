import json
from pathlib import Path

import pytest

_MUTATING_PREFIXES = ("Create", "Update", "Delete", "Put")

_ROOT = Path(__file__).resolve().parent.parent

# Every read-only policy document InfraAI ships. None may ever allow a
# mutating IAM action, and each must Deny them as a backstop.
#   - policies/plan-role.json                     -> infrai-plan-role (this repo's runtime)
#   - templates/target-repo-setup/plan-role.json  -> infrai-target-plan-role (target CI plan job)
READ_ONLY_POLICIES = {
    "plan-role": _ROOT / "policies" / "plan-role.json",
    "target-plan-role": _ROOT / "templates" / "target-repo-setup" / "plan-role.json",
}


def _actions(policy: dict, effect: str) -> list[str]:
    actions: list[str] = []
    for statement in policy["Statement"]:
        if statement["Effect"] == effect:
            action = statement["Action"]
            actions.extend(action if isinstance(action, list) else [action])
    return actions


def _verb(action: str) -> str:
    """Strips the IAM service prefix (e.g. "s3:Get*" -> "Get*") so the mutating-verb
    check works regardless of which service(s) the policy is scoped to."""
    return action.split(":", 1)[-1]


@pytest.mark.parametrize("policy_path", READ_ONLY_POLICIES.values(), ids=READ_ONLY_POLICIES.keys())
def test_read_only_role_has_no_mutating_allow_actions(policy_path):
    policy = json.loads(policy_path.read_text())
    for action in _actions(policy, "Allow"):
        assert not _verb(action).startswith(_MUTATING_PREFIXES), (
            f"{policy_path.name} allows mutating action: {action}"
        )


@pytest.mark.parametrize("policy_path", READ_ONLY_POLICIES.values(), ids=READ_ONLY_POLICIES.keys())
def test_read_only_role_denies_mutating_actions_as_backstop(policy_path):
    policy = json.loads(policy_path.read_text())
    denied = [_verb(a) for a in _actions(policy, "Deny")]
    for prefix in _MUTATING_PREFIXES:
        assert any(v.startswith(prefix) for v in denied), (
            f"{policy_path.name} missing explicit Deny for {prefix}*"
        )

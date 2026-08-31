import json
from pathlib import Path

_MUTATING_PREFIXES = ("Create", "Update", "Delete", "Put")

PLAN_ROLE_POLICY = json.loads(
    Path(__file__).resolve().parent.parent.joinpath("policies", "plan-role.json").read_text()
)


def _actions(effect: str) -> list[str]:
    actions = []
    for statement in PLAN_ROLE_POLICY["Statement"]:
        if statement["Effect"] == effect:
            action = statement["Action"]
            actions.extend(action if isinstance(action, list) else [action])
    return actions


def _verb(action: str) -> str:
    """Strips the IAM service prefix (e.g. "s3:Get*" -> "Get*") so the mutating-verb
    check works regardless of which service(s) the policy is scoped to."""
    return action.split(":", 1)[-1]


def test_plan_role_has_no_mutating_allow_actions():
    """infrai-plan-role must never allow a mutating IAM action."""
    for action in _actions("Allow"):
        assert not _verb(action).startswith(_MUTATING_PREFIXES), f"plan-role allows mutating action: {action}"


def test_plan_role_denies_mutating_actions_as_backstop():
    denied = [_verb(a) for a in _actions("Deny")]
    for prefix in _MUTATING_PREFIXES:
        assert any(v.startswith(prefix) for v in denied), f"plan-role missing explicit Deny for {prefix}*"

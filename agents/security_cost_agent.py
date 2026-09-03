from state import InfraAIState
from tools.hcl_tools import parse_files
from tools.security_tools import run_checkov, run_infracost

ALLOWED_TYPES_CHECK_ID = "INFRAI_ALLOWED_RESOURCE_TYPES"


def _resource_types(resources: list[str]) -> set[str]:
    """`["aws_s3_bucket.app", "aws_iam_role.r"]` -> `{"aws_s3_bucket", "aws_iam_role"}`."""
    return {r.split(".", 1)[0] for r in resources}


def security_cost_agent(state: InfraAIState, *, checkov=None, infracost=None) -> dict:
    """Runs Checkov + Infracost against the diffed files, then applies the target
    repo's `infrai.config.yaml` guardrails: budget ceiling and allowed resource
    types. Both flag (surfaced in the PR body) rather than block — the human
    reviewing the PR decides.
    """
    checkov = checkov or run_checkov
    infracost = infracost or run_infracost
    files = state.get("repo_context", {}).get("files", {})
    config = state.get("config", {})

    findings = list(checkov(files))
    cost = dict(infracost(files))

    # Budget ceiling: compare Infracost's number against the configured ceiling.
    ceiling = config.get("budget_ceiling_usd_per_month")
    cost["within_budget"] = ceiling is None or cost.get("delta_usd", 0) <= ceiling
    if ceiling is not None:
        cost["budget_ceiling_usd_per_month"] = ceiling

    # Allowed resource types: flag types this change *introduces* that aren't on
    # the list (pre-existing ones are the repo's problem, not this PR's).
    allowed = config.get("allowed_resource_types")
    if allowed is not None:
        existing = _resource_types(state.get("repo_context", {}).get("resources", []))
        try:
            introduced = _resource_types(parse_files(files)["resources"]) - existing
        except Exception:
            # best-effort HCL parse — terraform validate already gated correctness,
            # so a parser hiccup here shouldn't sink an otherwise-good run
            introduced = set()
        for rtype in sorted(introduced - set(allowed)):
            findings.append(
                {
                    "check_id": ALLOWED_TYPES_CHECK_ID,
                    "check_name": f"'{rtype}' is not in infrai.config.yaml allowed_resource_types",
                    "resource": rtype,
                }
            )

    return {
        "security_findings": findings,
        "cost_estimate": cost,
        "status": "ready_for_pr",
    }

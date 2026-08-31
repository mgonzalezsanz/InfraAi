from state import InfraAIState
from tools.terraform_tools import run_plan, run_validate


def validator_agent(state: InfraAIState, *, validate=None, plan=None) -> dict:
    """Runs terraform validate + plan. Plan uses infrai-plan-role credentials
    and only runs once validate has already passed, to avoid an unnecessary AWS
    call on a plain syntax error."""
    validate = validate or run_validate
    plan = plan or run_plan
    files = state.get("repo_context", {}).get("files", {})

    validate_result = validate(files)
    if not validate_result["valid"]:
        return {
            "validation_result": {"valid": False, "validate": validate_result, "plan": None},
            "retry_count": state.get("retry_count", 0) + 1,
            "status": "editing",
        }

    plan_result = plan(files)
    result = {"valid": plan_result["valid"], "validate": validate_result, "plan": plan_result}

    if not plan_result["valid"]:
        return {"validation_result": result, "retry_count": state.get("retry_count", 0) + 1, "status": "editing"}

    return {"validation_result": result, "status": "scanning"}

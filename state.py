from typing import Literal, TypedDict


class InfraAIState(TypedDict):
    user_request: str
    repo_context: dict          # existing resources, variables, conventions (files mutate as the editor works)
    base_files: dict            # frozen snapshot of the repo's files at context time, for drift detection
    config: dict                # target repo's infrai.config.yaml: budget ceiling, allowed resource types
    intent: Literal["change", "question", "ambiguous"] | None   # set by planner agent
    change_plan: list[dict]     # planner's file-level plan
    diff: str                   # current proposed diff
    validation_result: dict     # terraform validate/plan output
    security_findings: list[dict]
    cost_estimate: dict         # infracost delta vs. budget ceiling
    retry_count: int            # validator loop-back counter, cap at 3
    status: Literal[
        "planning",
        "editing",
        "validating",
        "scanning",
        "ready_for_pr",
        "needs_human",
        "needs_clarification",
        "answered",
        "pr_open",
    ]
    pr_url: str | None
    agent_message: str | None   # clarifying question or direct answer, when no PR is opened


def create_initial_state(user_request: str) -> InfraAIState:
    return InfraAIState(
        user_request=user_request,
        repo_context={},
        base_files={},
        config={},
        intent=None,
        change_plan=[],
        diff="",
        validation_result={},
        security_findings=[],
        cost_estimate={},
        retry_count=0,
        status="planning",
        pr_url=None,
        agent_message=None,
    )

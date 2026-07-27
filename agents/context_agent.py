from state import InfraAIState


def context_agent(state: InfraAIState) -> dict:
    """Phase 0 stub. Real version fetches only relevant files via the GitHub API (FR-1)."""
    return {
        "repo_context": {
            "resources": ["aws_s3_bucket.example", "aws_vpc.main"],
            "variables": ["region", "environment"],
            "conventions": {"naming": "snake_case", "tagging": ["Project", "Environment"]},
        },
        "status": "planning",
    }

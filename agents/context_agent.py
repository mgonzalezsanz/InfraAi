from pathlib import Path

from state import InfraAIState
from tools.config import load_config
from tools.hcl_tools import parse_repo

DEFAULT_FIXTURE_REPO = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "sample_repo"


def context_agent(state: InfraAIState, *, repo_path: str | None = None) -> dict:
    """Parses Terraform under `repo_path` into a structured summary, and loads the
    target repo's `infrai.config.yaml` guardrails.

    Reads a local checkout; wiring the real GitHub API fetch (still no full clone)
    is deferred.
    """
    path = repo_path or str(DEFAULT_FIXTURE_REPO)
    return {
        "repo_context": parse_repo(path),
        "config": load_config(path),
        "status": "planning",
    }

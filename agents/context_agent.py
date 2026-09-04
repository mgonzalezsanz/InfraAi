from pathlib import Path

from state import InfraAIState
from tools.config import CONFIG_FILENAME, load_config, parse_config
from tools.github_tools import fetch_repo_files
from tools.hcl_tools import parse_files, parse_repo

DEFAULT_FIXTURE_REPO = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "sample_repo"


def context_agent(
    state: InfraAIState,
    *,
    repo_path: str | None = None,
    target_repo: str | None = None,
    ref: str = "main",
) -> dict:
    """Builds the structured repo summary + loads the target repo's guardrails.

    `target_repo` ("owner/repo") is read over the GitHub API — no clone. Falls
    back to a local checkout (`repo_path`, else the bundled fixture) when it isn't
    given.
    """
    if target_repo:
        fetched = fetch_repo_files(target_repo, ref)
        tf_files = {p: c for p, c in fetched.items() if p.endswith(".tf")}
        config_text = next(
            (c for p, c in fetched.items() if p.split("/")[-1] == CONFIG_FILENAME), None
        )
        repo_context = parse_files(tf_files)
        config = parse_config(config_text)
    else:
        path = repo_path or str(DEFAULT_FIXTURE_REPO)
        repo_context = parse_repo(path)
        config = load_config(path)

    return {
        "repo_context": repo_context,
        "config": config,
        "status": "planning",
    }
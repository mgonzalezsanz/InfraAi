import base64
import hashlib
import json
import re
import subprocess
import tempfile

from tools.config import CONFIG_FILENAME
from tools.hcl_tools import materialize


def branch_name_for(user_request: str) -> str:
    """Deterministic branch name so re-running the same request maps to the same
    branch/PR instead of creating a duplicate."""
    slug = re.sub(r"[^a-z0-9]+", "-", user_request.lower()).strip("-")[:40]
    digest = hashlib.sha1(user_request.encode()).hexdigest()[:8]
    return f"infrai/{slug}-{digest}"


def _run(cmd, cwd=None):
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed: {result.stderr.strip()}")
    return result


def _gh_api(path: str) -> dict:
    return json.loads(_run(["gh", "api", path]).stdout)


def fetch_repo_files(repo: str, ref: str = "main") -> dict[str, str]:
    """Reads a target repo's Terraform files + `infrai.config.yaml` over the
    GitHub API — one recursive tree call plus one blob call per file, no clone.

    Returns `{path: content}`. Raises RuntimeError if `gh` fails (missing repo,
    bad ref, no auth) rather than returning a misleading empty dict.
    """
    tree = _gh_api(f"repos/{repo}/git/trees/{ref}?recursive=1")
    wanted = [
        entry["path"]
        for entry in tree.get("tree", [])
        if entry["type"] == "blob"
        and (entry["path"].endswith(".tf") or entry["path"].split("/")[-1] == CONFIG_FILENAME)
    ]

    files: dict[str, str] = {}
    for path in wanted:
        blob = _gh_api(f"repos/{repo}/contents/{path}?ref={ref}")
        files[path] = base64.b64decode(blob.get("content", "")).decode("utf-8")
    return files


def open_or_update_pr(repo: str, branch: str, files: dict[str, str], title: str, body: str) -> str:
    """Opens a branch + PR against `repo` (base: main), or pushes to the existing
    branch of an already-open PR instead of creating a duplicate.
    Shells out to `gh` — reuses the already-authenticated CLI, no PAT/App needed.

    Raises RuntimeError on any step that actually fails (a silently empty pr_url
    would otherwise look identical to a real success in state).
    """
    existing_urls = json.loads(
        _run(["gh", "pr", "list", "--repo", repo, "--head", branch, "--state", "open", "--json", "url"]).stdout
        or "[]"
    )

    with tempfile.TemporaryDirectory(prefix="infrai-pr-") as tmpdir:
        _run(["gh", "repo", "clone", repo, tmpdir])
        if existing_urls:
            _run(["git", "fetch", "origin", branch], cwd=tmpdir)
            _run(["git", "checkout", branch], cwd=tmpdir)
        else:
            _run(["git", "checkout", "-b", branch], cwd=tmpdir)

        materialize(files, tmpdir)
        _run(["git", "add", "-A"], cwd=tmpdir)
        subprocess.run(["git", "commit", "-m", title], cwd=tmpdir, capture_output=True, text=True)
        _run(["git", "push", "-u", "origin", branch], cwd=tmpdir)

    if existing_urls:
        return existing_urls[0]["url"]

    return _run(
        ["gh", "pr", "create", "--repo", repo, "--head", branch, "--base", "main", "--title", title, "--body", body]
    ).stdout.strip()

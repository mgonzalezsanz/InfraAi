import base64
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

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


def _git_check(tmpdir: str, *args: str) -> bool:
    """Run a git command purely for its exit status (0 -> True). Never raises."""
    return subprocess.run(["git", *args], cwd=tmpdir, capture_output=True, text=True).returncode == 0


def _drifted_files(repo_dir: str, files: dict[str, str], base_files: dict[str, str] | None) -> list[str]:
    """Files InfraAI is editing whose content on the freshly-checked-out base
    branch differs from the snapshot the change was planned against — InfraAI's
    version will overwrite them. Empty when the base snapshot is unknown."""
    if not base_files:
        return []
    drifted = [
        path
        for path in files
        if (Path(repo_dir) / path).is_file()
        and path in base_files
        and (Path(repo_dir) / path).read_text() != base_files[path]
    ]
    return sorted(drifted)


def _drift_note(paths: list[str]) -> str:
    listed = "\n".join(f"- `{p}`" for p in paths)
    return (
        "\n\n---\n**⚠️ Base branch changed during planning.** InfraAI edited these "
        "files, and they also moved on the base branch since InfraAI read them. "
        "InfraAI's version overwrites that and may revert a concurrent change — "
        f"review these closely:\n{listed}"
    )


def open_or_update_pr(
    repo: str,
    branch: str,
    files: dict[str, str],
    title: str,
    body: str,
    *,
    base: str = "main",
    base_files: dict[str, str] | None = None,
) -> str:
    """Open a PR for `branch` against `base`, or update the existing open one.

    The branch is always rebuilt from the current tip of `base` plus a single
    commit materializing `files`, then pushed (force-with-lease if it already
    exists). So the PR never carries stale commits and never conflicts with
    `base`; a branch left behind by a merged or closed PR is reset rather than
    pushed onto. The `infrai/*` namespace is InfraAI's alone — humans review the
    PR, they don't push to its branch.

    Shells out to `gh`, reusing the authenticated CLI. Raises RuntimeError on any
    step that genuinely fails (a silently empty pr_url would look like success).

    `base_files` (the repo snapshot the change was planned against) is optional;
    when given, files that moved on `base` since then are flagged in the PR body.
    """
    open_prs = json.loads(
        _run(["gh", "pr", "list", "--repo", repo, "--head", branch, "--state", "open", "--json", "url"]).stdout
        or "[]"
    )

    with tempfile.TemporaryDirectory(prefix="infrai-pr-") as tmpdir:
        _run(["gh", "repo", "clone", repo, tmpdir])

        remote_has_branch = _git_check(
            tmpdir, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}"
        )
        _run(["git", "checkout", "-B", branch, f"origin/{base}"], cwd=tmpdir)

        drift = _drifted_files(tmpdir, files, base_files)

        materialize(files, tmpdir)
        _run(["git", "add", "-A"], cwd=tmpdir)

        if _git_check(tmpdir, "diff", "--cached", "--quiet"):  # nothing staged
            if open_prs:
                return open_prs[0]["url"]
            raise RuntimeError(f"InfraAI's change is already on '{base}' — nothing to open a PR for")

        _run(
            ["git", "-c", "user.name=InfraAI", "-c", "user.email=infrai@users.noreply.github.com",
             "commit", "-m", title],
            cwd=tmpdir,
        )
        push_target = ["--force-with-lease", "origin", branch] if remote_has_branch else ["-u", "origin", branch]
        _run(["git", "push", *push_target], cwd=tmpdir)

    full_body = body + _drift_note(drift) if drift else body

    if open_prs:
        url = open_prs[0]["url"]
        _run(["gh", "pr", "edit", url, "--repo", repo, "--body", full_body])
        return url

    return _run(
        ["gh", "pr", "create", "--repo", repo, "--head", branch, "--base", base,
         "--title", title, "--body", full_body]
    ).stdout.strip()

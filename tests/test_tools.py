"""Unit tests for the external-CLI wrappers, with the subprocess call stubbed."""
import base64
import json
import subprocess

import pytest

from tools import security_tools
from tools.github_tools import branch_name_for, fetch_repo_files, open_or_update_pr


_INFRACOST_V2_JSON = json.dumps(
    {
        "currency": "USD",
        "summary": {
            "projects": 1,
            "resources": 2,
            "costed_resources": 2,
            "total_monthly_cost": "53.374",
        },
        "projects": [],
    }
)


def _stub_run(stdout: str):
    return lambda *a, **k: subprocess.CompletedProcess(a[0], 0, stdout=stdout, stderr="")


def test_run_infracost_parses_v2_summary_cost(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _stub_run(_INFRACOST_V2_JSON))
    result = security_tools.run_infracost({"main.tf": "# ignored, subprocess is stubbed"})
    assert result == {"delta_usd": 53.374}  # budget comparison is the agent's job, not the tool's


def test_run_infracost_handles_zero_cost(monkeypatch):
    zero = json.dumps({"currency": "USD", "summary": {"total_monthly_cost": "0"}, "projects": []})
    monkeypatch.setattr(subprocess, "run", _stub_run(zero))
    result = security_tools.run_infracost({"main.tf": ""})
    assert result["delta_usd"] == 0.0


def _gh_stub(responses: dict):
    """Maps a substring of the `gh api <path>` argument to a JSON stdout string."""

    def run(cmd, *a, **k):
        url = cmd[-1]
        for key, out in responses.items():
            if key in url:
                return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")
        raise AssertionError(f"unexpected gh call: {url}")

    return run


def _b64_file(text: str) -> str:
    return json.dumps({"content": base64.b64encode(text.encode()).decode(), "encoding": "base64"})


def test_fetch_repo_files_pulls_only_tf_and_config_over_the_api(monkeypatch):
    tree = json.dumps(
        {
            "tree": [
                {"path": "main.tf", "type": "blob"},
                {"path": "README.md", "type": "blob"},
                {"path": "infrai.config.yaml", "type": "blob"},
                {"path": "modules", "type": "tree"},
                {"path": "modules/vpc/main.tf", "type": "blob"},
            ]
        }
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        _gh_stub(
            {
                "git/trees/main?recursive=1": tree,
                "contents/main.tf?": _b64_file('resource "aws_s3_bucket" "a" {}'),
                "contents/infrai.config.yaml?": _b64_file("budget_ceiling_usd_per_month: 5"),
                "contents/modules/vpc/main.tf?": _b64_file('resource "aws_vpc" "v" {}'),
            }
        ),
    )

    files = fetch_repo_files("acme/infra")
    assert set(files) == {"main.tf", "infrai.config.yaml", "modules/vpc/main.tf"}
    assert files["main.tf"] == 'resource "aws_s3_bucket" "a" {}'
    assert "README.md" not in files


def test_fetch_repo_files_raises_when_gh_fails(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 1, stdout="", stderr="Not Found"),
    )
    try:
        fetch_repo_files("acme/nope")
    except RuntimeError as exc:
        assert "Not Found" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_branch_name_is_deterministic_per_request():
    assert branch_name_for("Add an S3 bucket") == branch_name_for("Add an S3 bucket")
    assert branch_name_for("Add an S3 bucket") != branch_name_for("Add a VPC")


def _git(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    )


@pytest.fixture
def fake_remote(tmp_path):
    """A bare `origin` seeded with one commit on `main` containing main.tf.
    Returns (remote_path, seed_checkout) so a test can add branches/commits."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)], check=True, capture_output=True)
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", str(remote), str(seed)], check=True, capture_output=True)
    (seed / "main.tf").write_text('resource "aws_s3_bucket" "existing" {}\n')
    _git(seed, "add", "-A")
    _git(seed, "commit", "-m", "init")
    _git(seed, "push", "origin", "main")
    return remote, seed


class _GhShim:
    """Passes real git through; fakes `gh repo clone` (from the bare remote) and
    the `gh pr` subcommands. Records every call."""

    def __init__(self, fake_remote, open_pr_url=None):
        self._remote = str(fake_remote)
        self._open_pr_url = open_pr_url
        self._real_run = subprocess.run
        self.calls: list[list[str]] = []

    def __call__(self, cmd, *args, **kwargs):
        self.calls.append(cmd)
        if cmd[:3] == ["gh", "repo", "clone"]:
            return self._real_run(["git", "clone", self._remote, cmd[4]], *args, **kwargs)
        if cmd[:3] == ["gh", "pr", "list"]:
            payload = f'[{{"url": "{self._open_pr_url}"}}]' if self._open_pr_url else "[]"
            return subprocess.CompletedProcess(cmd, 0, stdout=payload, stderr="")
        if cmd[:3] == ["gh", "pr", "create"]:
            self._create_body = _flag_value(cmd, "--body")
            return subprocess.CompletedProcess(cmd, 0, stdout="https://github.com/o/r/pull/7\n", stderr="")
        if cmd[:3] == ["gh", "pr", "edit"]:
            self._edit_body = _flag_value(cmd, "--body")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        return self._real_run(cmd, *args, **kwargs)  # real git

    def ran(self, prefix: str) -> bool:
        return any(" ".join(c).startswith(prefix) for c in self.calls)


def _flag_value(cmd, flag):
    return cmd[cmd.index(flag) + 1] if flag in cmd else None


def _remote_log(remote, branch="main"):
    out = subprocess.run(
        ["git", "--git-dir", str(remote), "log", "--format=%s", branch],
        check=True, capture_output=True, text=True,
    )
    return out.stdout.split()


def test_open_or_update_pr_creates_a_pr_when_none_is_open(fake_remote, monkeypatch):
    remote, _ = fake_remote
    shim = _GhShim(remote)
    monkeypatch.setattr(subprocess, "run", shim)

    url = open_or_update_pr(
        "o/r", "infrai/add-logs-abc123",
        {"main.tf": 'resource "aws_s3_bucket" "existing" {}\n', "logs.tf": 'resource "aws_s3_bucket" "logs" {}\n'},
        "title", "body",
    )

    assert url == "https://github.com/o/r/pull/7"
    assert shim.ran("gh pr create")
    # branch was pushed, based on main + exactly one commit
    assert _remote_log(remote, "infrai/add-logs-abc123") == ["title", "init"]


def test_open_or_update_pr_resets_a_leftover_branch_with_no_open_pr(fake_remote, monkeypatch):
    remote, seed = fake_remote
    # a stale branch left behind by an old merged/closed PR, diverged from main
    _git(seed, "checkout", "-b", "infrai/add-logs-abc123")
    (seed / "old.tf").write_text("# stale\n")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-m", "stale-work")
    _git(seed, "push", "origin", "infrai/add-logs-abc123")

    shim = _GhShim(remote)  # no open PR
    monkeypatch.setattr(subprocess, "run", shim)

    url = open_or_update_pr(
        "o/r", "infrai/add-logs-abc123",
        {"main.tf": 'resource "aws_s3_bucket" "existing" {}\n', "logs.tf": 'resource "aws_s3_bucket" "logs" {}\n'},
        "title", "body",
    )

    assert url == "https://github.com/o/r/pull/7"
    # the stale commit is gone — branch is main + one fresh commit
    assert _remote_log(remote, "infrai/add-logs-abc123") == ["title", "init"]


def test_open_or_update_pr_updates_the_open_pr_instead_of_duplicating(fake_remote, monkeypatch):
    remote, seed = fake_remote
    _git(seed, "checkout", "-b", "infrai/add-logs-abc123")
    _git(seed, "push", "origin", "infrai/add-logs-abc123")

    shim = _GhShim(remote, open_pr_url="https://github.com/o/r/pull/3")
    monkeypatch.setattr(subprocess, "run", shim)

    url = open_or_update_pr(
        "o/r", "infrai/add-logs-abc123",
        {"main.tf": 'resource "aws_s3_bucket" "existing" {}\n', "logs.tf": 'resource "aws_s3_bucket" "logs" {}\n'},
        "title", "body",
    )

    assert url == "https://github.com/o/r/pull/3"  # the open PR
    assert not shim.ran("gh pr create")            # no duplicate
    assert shim.ran("gh pr edit")                  # body refreshed


def test_open_or_update_pr_raises_when_the_change_is_already_on_base(fake_remote, monkeypatch):
    remote, _ = fake_remote
    shim = _GhShim(remote)
    monkeypatch.setattr(subprocess, "run", shim)

    with pytest.raises(RuntimeError, match="already on"):
        open_or_update_pr(
            "o/r", "infrai/noop-abc123",
            {"main.tf": 'resource "aws_s3_bucket" "existing" {}\n'},  # identical to main
            "title", "body",
        )
    assert not shim.ran("gh pr create")


def test_open_or_update_pr_flags_files_that_drifted_on_base(fake_remote, monkeypatch):
    remote, _ = fake_remote
    shim = _GhShim(remote)
    monkeypatch.setattr(subprocess, "run", shim)

    open_or_update_pr(
        "o/r", "infrai/edit-main-abc123",
        {"main.tf": 'resource "aws_s3_bucket" "existing" {}\n# edited by infrai\n'},
        "title", "body",
        base_files={"main.tf": "# what infrai read earlier, now stale\n"},
    )

    assert "Base branch changed during planning" in shim._create_body
    assert "`main.tf`" in shim._create_body

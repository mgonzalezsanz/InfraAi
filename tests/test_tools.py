"""Unit tests for the external-CLI wrappers, with the subprocess call stubbed."""
import base64
import json
import subprocess

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


class _FakeGh:
    """Records every gh/git call; returns the given `gh pr list` output and a
    fixed URL for `gh pr create`."""

    def __init__(self, pr_list_stdout: str):
        self.calls: list[list[str]] = []
        self._pr_list_stdout = pr_list_stdout

    def __call__(self, cmd, *args, **kwargs):
        self.calls.append(cmd)
        if cmd[:3] == ["gh", "pr", "list"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=self._pr_list_stdout, stderr="")
        if cmd[:3] == ["gh", "pr", "create"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="https://github.com/o/r/pull/7\n", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    def ran(self, prefix: str) -> bool:
        return any(" ".join(c).startswith(prefix) for c in self.calls)


def test_open_or_update_pr_creates_a_pr_when_none_is_open(monkeypatch):
    fake = _FakeGh(pr_list_stdout="[]")
    monkeypatch.setattr(subprocess, "run", fake)

    url = open_or_update_pr("o/r", "infrai/add-bucket-abc123", {"main.tf": "x"}, "title", "body")

    assert url == "https://github.com/o/r/pull/7"
    assert fake.ran("gh pr create")
    assert fake.ran("git checkout -b infrai/add-bucket-abc123")


def test_open_or_update_pr_updates_the_existing_pr_instead_of_duplicating(monkeypatch):
    fake = _FakeGh(pr_list_stdout='[{"url": "https://github.com/o/r/pull/3"}]')
    monkeypatch.setattr(subprocess, "run", fake)

    url = open_or_update_pr("o/r", "infrai/add-bucket-abc123", {"main.tf": "x"}, "title", "body")

    assert url == "https://github.com/o/r/pull/3"  # the open PR, not a new one
    assert not fake.ran("gh pr create")            # no duplicate
    assert fake.ran("git fetch origin infrai/add-bucket-abc123")
    assert fake.ran("git checkout infrai/add-bucket-abc123")

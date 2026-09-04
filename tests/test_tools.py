"""Unit tests for the external-CLI wrappers, with the subprocess call stubbed."""
import base64
import json
import subprocess

from tools import security_tools
from tools.github_tools import fetch_repo_files


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

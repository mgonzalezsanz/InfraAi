"""Unit tests for the external-CLI wrappers, with the subprocess call stubbed."""
import json
import subprocess

from tools import security_tools


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
    assert result == {"delta_usd": 53.374, "within_budget": True}


def test_run_infracost_handles_zero_cost(monkeypatch):
    zero = json.dumps({"currency": "USD", "summary": {"total_monthly_cost": "0"}, "projects": []})
    monkeypatch.setattr(subprocess, "run", _stub_run(zero))
    result = security_tools.run_infracost({"main.tf": ""})
    assert result["delta_usd"] == 0.0

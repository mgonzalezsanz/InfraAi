import json
import subprocess
import sys
import tempfile

from tools.hcl_tools import materialize


def run_checkov(files: dict[str, str]) -> list[dict]:
    """Writes `files` to a temp checkout and runs Checkov. No account/API key needed."""
    with tempfile.TemporaryDirectory(prefix="infrai-checkov-") as tmpdir:
        materialize(files, tmpdir)
        result = subprocess.run(
            [sys.executable, "-m", "checkov.main", "-d", tmpdir, "--compact", "-o", "json"],
            capture_output=True, text=True,
        )

    parsed = json.loads(result.stdout)
    failed = parsed.get("results", {}).get("failed_checks", [])
    return [
        {"check_id": c["check_id"], "check_name": c["check_name"], "resource": c["resource"]}
        for c in failed
    ]


def run_infracost(files: dict[str, str]) -> dict:
    """Writes `files` to a temp checkout and runs `infracost scan` (needs v2+)."""
    with tempfile.TemporaryDirectory(prefix="infrai-infracost-") as tmpdir:
        materialize(files, tmpdir)
        result = subprocess.run(
            ["infracost", "scan", tmpdir, "--json"],
            capture_output=True, text=True,
        )

    summary = json.loads(result.stdout).get("summary", {})
    return {"delta_usd": float(summary.get("total_monthly_cost") or 0), "within_budget": True}

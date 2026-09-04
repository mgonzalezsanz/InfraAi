import json
import os
import subprocess
import tempfile
from pathlib import Path

from tools.hcl_tools import materialize

# ponytail: shared cache so repeat validate calls don't redownload the provider each time
_PLUGIN_CACHE_DIR = Path(__file__).resolve().parent.parent / ".terraform-cache"


def run_validate(files: dict[str, str]) -> dict:
    """Writes `files` to a temp checkout and runs terraform init + validate.

    No AWS credentials needed — validate only checks syntax/schema against the
    provider plugin, it never calls AWS. See `run_plan` for the AWS-backed step.

    Skips backend.tf since even with -backend=false, a configured backend can
    interfere. Validation is about syntax, not backend setup.
    """
    _PLUGIN_CACHE_DIR.mkdir(exist_ok=True)
    env = {**os.environ, "TF_PLUGIN_CACHE_DIR": str(_PLUGIN_CACHE_DIR)}

    # exclude backend.tf from validation
    files_to_validate = {p: c for p, c in files.items() if not p.endswith("backend.tf")}

    with tempfile.TemporaryDirectory(prefix="infrai-validate-") as tmpdir:
        materialize(files_to_validate, tmpdir)

        subprocess.run(
            ["terraform", "init", "-backend=false", "-input=false"],
            cwd=tmpdir, env=env, capture_output=True, text=True,
        )
        result = subprocess.run(
            ["terraform", "validate", "-json"],
            cwd=tmpdir, env=env, capture_output=True, text=True,
        )

    parsed = json.loads(result.stdout)
    return {
        "valid": parsed.get("valid", False),
        "errors": [d["summary"] for d in parsed.get("diagnostics", []) if d.get("severity") == "error"],
    }


def run_plan(files: dict[str, str], aws_profile: str = "infrai-plan") -> dict:
    """Writes `files` to a temp checkout and runs terraform plan using infrai-plan-role
    credentials. Read-only against AWS — the role's policy denies every
    mutating action as a backstop, so this can never apply anything.

    Skips backend.tf so the plan doesn't depend on S3 backend setup (the apply
    workflow handles that).
    """
    _PLUGIN_CACHE_DIR.mkdir(exist_ok=True)
    env = {**os.environ, "TF_PLUGIN_CACHE_DIR": str(_PLUGIN_CACHE_DIR), "AWS_PROFILE": aws_profile}

    files_to_plan = {p: c for p, c in files.items() if not p.endswith("backend.tf")}

    with tempfile.TemporaryDirectory(prefix="infrai-plan-") as tmpdir:
        materialize(files_to_plan, tmpdir)

        subprocess.run(
            ["terraform", "init", "-backend=false", "-input=false"],
            cwd=tmpdir, env=env, capture_output=True, text=True,
        )
        result = subprocess.run(
            ["terraform", "plan", "-input=false", "-json"],
            cwd=tmpdir, env=env, capture_output=True, text=True,
        )

    summary = {"add": 0, "change": 0, "destroy": 0}
    errors = []
    for line in result.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "change_summary":
            changes = event["changes"]
            summary = {"add": changes["add"], "change": changes["change"], "destroy": changes["remove"]}
        elif event.get("type") == "diagnostic" and event.get("diagnostic", {}).get("severity") == "error":
            errors.append(event["diagnostic"].get("summary", ""))

    return {"valid": result.returncode == 0 and not errors, "summary": summary, "errors": errors}

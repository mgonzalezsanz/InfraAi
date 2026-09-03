"""Reads the target repo's ``infrai.config.yaml`` — the budget ceiling and the
allowed resource types the Security/cost agent checks against. This lives as a
file in the target repo, never in InfraAI's code or the UI."""

from pathlib import Path

import yaml

CONFIG_FILENAME = "infrai.config.yaml"

# A key left as None means "not configured" -> the security/cost agent skips
# that particular check rather than guessing a default.
_DEFAULTS: dict = {
    "budget_ceiling_usd_per_month": None,
    "allowed_resource_types": None,
}


def load_config(repo_path: str) -> dict:
    """Load ``infrai.config.yaml`` from the root of a target-repo checkout.

    A missing file (or missing keys) yields the permissive defaults above, so a
    target repo that hasn't added the file still runs — just without guardrails.
    """
    path = Path(repo_path) / CONFIG_FILENAME
    if not path.is_file():
        return dict(_DEFAULTS)
    loaded = yaml.safe_load(path.read_text()) or {}
    return {**_DEFAULTS, **loaded}

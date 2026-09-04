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


def parse_config(text: str | None) -> dict:
    """Parse ``infrai.config.yaml`` contents. Missing text or missing keys yield
    the permissive defaults, so a target repo without the file still runs — just
    without guardrails."""
    loaded = yaml.safe_load(text) if text else None
    return {**_DEFAULTS, **(loaded or {})}


def load_config(repo_path: str) -> dict:
    """`parse_config` for a local target-repo checkout."""
    path = Path(repo_path) / CONFIG_FILENAME
    return parse_config(path.read_text() if path.is_file() else None)
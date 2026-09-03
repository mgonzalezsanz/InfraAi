from tools.config import load_config

SAMPLE_REPO = "tests/fixtures/sample_repo"


def test_load_config_reads_the_target_repo_file():
    config = load_config(SAMPLE_REPO)
    assert config["budget_ceiling_usd_per_month"] == 100
    assert "aws_s3_bucket" in config["allowed_resource_types"]


def test_load_config_missing_file_returns_permissive_defaults(tmp_path):
    config = load_config(str(tmp_path))
    assert config == {"budget_ceiling_usd_per_month": None, "allowed_resource_types": None}


def test_load_config_fills_missing_keys(tmp_path):
    (tmp_path / "infrai.config.yaml").write_text("budget_ceiling_usd_per_month: 50\n")
    config = load_config(str(tmp_path))
    assert config["budget_ceiling_usd_per_month"] == 50
    assert config["allowed_resource_types"] is None

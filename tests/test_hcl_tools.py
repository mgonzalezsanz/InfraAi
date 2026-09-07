from tools.hcl_tools import parse_files, parse_repo

SAMPLE_REPO = "tests/fixtures/sample_repo"


def test_parse_repo_extracts_resources_and_variables():
    ctx = parse_repo(SAMPLE_REPO)
    assert "aws_s3_bucket.app_data" in ctx["resources"]
    assert set(ctx["variables"]) >= {"region", "environment", "resource_name_prefix"}


def test_parse_repo_picks_up_the_tagging_convention():
    # python-hcl2 wraps `tags = {...}` as [{...}]; parse_repo must unwrap it
    ctx = parse_repo(SAMPLE_REPO)
    assert ctx["conventions"]["tagging"] == ["Environment", "Project"]


def test_parse_files_matches_parse_repo_for_the_same_content():
    from pathlib import Path

    files = {
        str(p.relative_to(SAMPLE_REPO)): p.read_text()
        for p in Path(SAMPLE_REPO).rglob("*.tf")
    }
    assert parse_files(files)["conventions"]["tagging"] == ["Environment", "Project"]

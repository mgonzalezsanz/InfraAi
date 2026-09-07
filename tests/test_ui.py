import pytest
from fastapi.testclient import TestClient

import ui.app as ui_app

client = TestClient(ui_app.app)


@pytest.fixture(autouse=True)
def _reset():
    saved = dict(ui_app._settings)
    ui_app._settings.update({"anthropic_api_key": "", "target_repo": ""})
    ui_app._runs.clear()
    yield
    ui_app._settings.update(saved)
    ui_app._runs.clear()


class _StubGraph:
    def stream(self, *a, **k):
        return iter(())


def _seed_run(run_id, **over):
    ui_app._runs[run_id] = {
        "user_request": "add a bucket",
        "log": [],
        "done": True,
        "error": None,
        "result": {},
        **over,
    }


def test_index_page_loads_with_sidebar():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "InfraAI" in resp.text
    assert "New conversation" in resp.text


def test_create_run_redirects_to_the_run_page(monkeypatch):
    monkeypatch.setattr(ui_app, "_execute", lambda *a, **k: None)
    resp = client.post("/runs", data={"user_request": "test request"})
    assert resp.status_code == 200                 # 303 followed
    assert str(resp.url).rstrip("/").endswith("/runs/" + next(iter(ui_app._runs)))
    assert "hx-get" in resp.text                   # the run fragment self-polls
    assert "running" in resp.text


def test_settings_form_updates_and_remembers(monkeypatch):
    client.post("/settings", data={"target_repo": "acme/infra", "anthropic_api_key": "sk-ant-secret"})
    assert ui_app._settings == {"target_repo": "acme/infra", "anthropic_api_key": "sk-ant-secret"}

    # blank key keeps the current one; blank target repo clears it
    client.post("/settings", data={"target_repo": "", "anthropic_api_key": ""})
    assert ui_app._settings == {"target_repo": "", "anthropic_api_key": "sk-ant-secret"}


def test_sidebar_shows_target_repo_but_never_the_api_key():
    ui_app._settings.update({"target_repo": "acme/infra", "anthropic_api_key": "sk-ant-secret"})
    resp = client.get("/")
    assert "acme/infra" in resp.text
    assert "sk-ant-secret" not in resp.text
    assert "API key set" in resp.text


def test_sidebar_lists_past_conversations_newest_first():
    _seed_run("aaa", user_request="first request")
    _seed_run("bbb", user_request="second request")
    resp = client.get("/")
    assert "first request" in resp.text and "second request" in resp.text
    assert resp.text.index("second request") < resp.text.index("first request")


def test_execute_passes_settings_into_build_graph(monkeypatch):
    captured = {}
    monkeypatch.setattr(ui_app, "build_graph", lambda **kw: captured.update(kw) or _StubGraph())
    _seed_run("rid", done=False)
    ui_app._execute("rid", "add a bucket", "sk-ant-xyz", "acme/infra")
    assert captured == {"api_key": "sk-ant-xyz", "target_repo": "acme/infra"}


def test_run_fragment_shows_pr_url_and_stops_polling():
    _seed_run("fake-pr", log=[{"node": "pr", "status": "pr_open"}],
              result={"pr_url": "https://github.com/mock/mock/pull/1"})
    resp = client.get("/runs/fake-pr", headers={"HX-Request": "true"})
    assert "https://github.com/mock/mock/pull/1" in resp.text
    assert "hx-get" not in resp.text


def test_run_fragment_shows_agent_message():
    _seed_run("fake-q", log=[{"node": "planner", "status": "answered"}],
              result={"agent_message": "eu-west-3"})
    resp = client.get("/runs/fake-q", headers={"HX-Request": "true"})
    assert "eu-west-3" in resp.text


def test_agent_message_renders_markdown_and_escapes_html():
    _seed_run("fake-md", result={"agent_message": "I can:\n- **make changes**\n- <script>alert(1)</script>"})
    resp = client.get("/runs/fake-md", headers={"HX-Request": "true"})
    assert "<strong>make changes</strong>" in resp.text        # markdown rendered
    assert "<li>" in resp.text                                  # list rendered
    assert "<script>alert(1)</script>" not in resp.text         # raw HTML neutralised
    assert "&lt;script&gt;" in resp.text


def test_run_fragment_shows_error():
    _seed_run("fake-err", log=[], error="something broke", result={})
    resp = client.get("/runs/fake-err", headers={"HX-Request": "true"})
    assert "something broke" in resp.text


def test_run_fragment_shows_validator_retry_count():
    _seed_run("fake-retry", done=False, log=[
        {"node": "editor", "status": "validating", "retry_count": 0},
        {"node": "validator", "status": "editing", "retry_count": 2},
    ])
    resp = client.get("/runs/fake-retry", headers={"HX-Request": "true"})
    assert "retry 2/3" in resp.text


def test_run_page_renders_full_layout_when_not_an_hx_request():
    _seed_run("full", result={"agent_message": "hello"})
    resp = client.get("/runs/full")
    assert "New conversation" in resp.text  # sidebar present
    assert "hello" in resp.text

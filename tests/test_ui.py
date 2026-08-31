from fastapi.testclient import TestClient

import ui.app as ui_app

client = TestClient(ui_app.app)


def test_index_page_loads():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "InfraAI" in resp.text


def test_create_run_returns_pending_fragment_with_polling(monkeypatch):
    monkeypatch.setattr(ui_app, "_execute", lambda run_id, user_request: None)  # don't hit a real graph run
    resp = client.post("/runs", data={"user_request": "test request"})
    assert resp.status_code == 200
    assert "hx-get" in resp.text  # still running, so it should keep polling
    assert "running" in resp.text


def test_run_fragment_shows_pr_url_and_stops_polling():
    ui_app._runs["fake-pr"] = {
        "user_request": "add a bucket",
        "log": [{"node": "pr", "status": "pr_open"}],
        "done": True,
        "error": None,
        "result": {"pr_url": "https://github.com/mock/mock/pull/1"},
    }
    resp = client.get("/runs/fake-pr", headers={"HX-Request": "true"})
    assert "https://github.com/mock/mock/pull/1" in resp.text
    assert "hx-get" not in resp.text  # done, polling should stop


def test_run_fragment_shows_agent_message():
    ui_app._runs["fake-question"] = {
        "user_request": "what region?",
        "log": [{"node": "planner", "status": "answered"}],
        "done": True,
        "error": None,
        "result": {"agent_message": "us-east-1"},
    }
    resp = client.get("/runs/fake-question", headers={"HX-Request": "true"})
    assert "us-east-1" in resp.text


def test_run_fragment_shows_error():
    ui_app._runs["fake-error"] = {
        "user_request": "boom",
        "log": [],
        "done": True,
        "error": "something broke",
        "result": {},
    }
    resp = client.get("/runs/fake-error", headers={"HX-Request": "true"})
    assert "something broke" in resp.text

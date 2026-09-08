import pytest
from fastapi.testclient import TestClient

import ui.app as ui_app

client = TestClient(ui_app.app)


@pytest.fixture(autouse=True)
def _reset():
    saved = dict(ui_app._settings)
    ui_app._settings.update({"anthropic_api_key": "", "target_repo": ""})
    ui_app._conversations.clear()
    yield
    ui_app._settings.update(saved)
    ui_app._conversations.clear()


class _StubGraph:
    """A graph whose stream yields the given per-node updates."""

    def __init__(self, updates):
        self._updates = updates

    def stream(self, *a, **k):
        return iter(self._updates)


def _seed(conv_id, **over):
    ui_app._conversations[conv_id] = {
        "id": conv_id,
        "title": "add a bucket",
        "messages": [{"role": "user", "content": "add a bucket"}],
        "api_key": "",
        "target_repo": "",
        "log": [],
        "result": {},
        "error": None,
        "running": False,
        "done": True,
        **over,
    }
    return ui_app._conversations[conv_id]


# ---- index / settings / sidebar ----

def test_index_page_loads_with_sidebar():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "InfraAI" in resp.text and "New conversation" in resp.text


def test_settings_form_updates_and_remembers():
    client.post("/settings", data={"target_repo": "acme/infra", "anthropic_api_key": "sk-ant-secret"})
    assert ui_app._settings == {"target_repo": "acme/infra", "anthropic_api_key": "sk-ant-secret"}
    client.post("/settings", data={"target_repo": "", "anthropic_api_key": ""})
    assert ui_app._settings == {"target_repo": "", "anthropic_api_key": "sk-ant-secret"}


def test_sidebar_shows_target_repo_but_never_the_api_key():
    ui_app._settings.update({"target_repo": "acme/infra", "anthropic_api_key": "sk-ant-secret"})
    resp = client.get("/")
    assert "acme/infra" in resp.text
    assert "sk-ant-secret" not in resp.text and "API key set" in resp.text


def test_sidebar_lists_conversations_newest_first():
    _seed("aaa", title="first request")
    _seed("bbb", title="second request")
    resp = client.get("/")
    assert resp.text.index("second request") < resp.text.index("first request")


# ---- creating a conversation ----

def test_create_conversation_redirects_and_starts_a_turn(monkeypatch):
    monkeypatch.setattr(ui_app, "_start_turn", lambda cid: None)
    resp = client.post("/runs", data={"user_request": "add a logs bucket"})
    assert resp.status_code == 200  # 303 followed
    conv_id = next(iter(ui_app._conversations))
    assert str(resp.url).endswith(f"/conversations/{conv_id}")
    conv = ui_app._conversations[conv_id]
    assert conv["messages"] == [{"role": "user", "content": "add a logs bucket"}]
    assert conv["title"] == "add a logs bucket"


def test_legacy_run_url_redirects_to_conversation():
    _seed("xyz")
    resp = client.get("/runs/xyz", follow_redirects=False)
    assert resp.status_code == 308
    assert resp.headers["location"] == "/conversations/xyz"


# ---- a turn: _execute ----

def test_execute_streams_the_graph_and_appends_an_agent_message(monkeypatch):
    updates = [
        {"context": {"status": "planning"}},
        {"planner": {"status": "answered", "agent_message": "It's eu-west-3."}},
    ]
    monkeypatch.setattr(ui_app, "build_graph", lambda **kw: _StubGraph(updates))
    conv = _seed("c1", running=True, done=False)
    ui_app._execute("c1")
    assert conv["done"] and not conv["running"]
    assert conv["messages"][-1] == {"role": "agent", "content": "It's eu-west-3.", "status": "answered"}
    assert conv["log"][-1]["status"] == "answered"


def test_execute_passes_conversation_id_as_branch_key(monkeypatch):
    captured = {}
    monkeypatch.setattr(ui_app, "build_graph", lambda **kw: captured.update(kw) or _StubGraph([]))
    _seed("c2", api_key="sk-ant-xyz", target_repo="acme/infra", running=True, done=False)
    ui_app._execute("c2")
    assert captured == {"api_key": "sk-ant-xyz", "target_repo": "acme/infra", "branch_key": "c2"}


def test_execute_reports_a_graph_error_in_the_thread(monkeypatch):
    def boom(**kw):
        raise RuntimeError("gh not authenticated")

    monkeypatch.setattr(ui_app, "build_graph", boom)
    conv = _seed("c3", running=True, done=False)
    ui_app._execute("c3")
    assert conv["done"] and conv["error"] == "gh not authenticated"
    assert "gh not authenticated" in conv["messages"][-1]["content"]


# ---- follow-up messages ----

def test_follow_up_is_accepted_from_a_continuable_state(monkeypatch):
    started = []
    monkeypatch.setattr(ui_app, "_start_turn", started.append)
    _seed("c4", result={"status": "needs_clarification", "agent_message": "which bucket?"})
    client.post("/conversations/c4/messages", data={"message": "app_data"})
    assert ui_app._conversations["c4"]["messages"][-1] == {"role": "user", "content": "app_data"}
    assert started == ["c4"]


def test_follow_up_is_ignored_after_a_pr_is_open(monkeypatch):
    started = []
    monkeypatch.setattr(ui_app, "_start_turn", started.append)
    conv = _seed("c5", result={"status": "pr_open", "pr_url": "http://x/pull/1"})
    before = list(conv["messages"])
    client.post("/conversations/c5/messages", data={"message": "actually 30 days"})
    assert conv["messages"] == before and started == []


def test_follow_up_is_ignored_while_a_turn_is_running(monkeypatch):
    started = []
    monkeypatch.setattr(ui_app, "_start_turn", started.append)
    conv = _seed("c6", running=True, done=False)
    client.post("/conversations/c6/messages", data={"message": "more"})
    assert started == []


# ---- rendering ----

def test_conversation_page_renders_thread_and_reply_box_when_continuable():
    _seed("c7", messages=[
        {"role": "user", "content": "add a bucket"},
        {"role": "agent", "content": "Which name? **app_data** or **app_logs**?"},
    ], result={"status": "needs_clarification", "agent_message": "Which name?"})
    resp = client.get("/conversations/c7")
    assert "New conversation" in resp.text                        # sidebar
    assert "<strong>app_data</strong>" in resp.text               # agent message as markdown
    assert 'action="/conversations/c7/messages"' in resp.text     # reply box


def test_conversation_page_disables_reply_box_after_pr_open():
    _seed("c8", messages=[
        {"role": "user", "content": "add a bucket"},
        {"role": "agent", "content": "Opened a pull request: http://x/pull/1"},
    ], result={"status": "pr_open", "pr_url": "http://x/pull/1"})
    resp = client.get("/conversations/c8")
    assert "start a new conversation" in resp.text.lower()
    assert "disabled" in resp.text  # the reply box is shown but not usable


def test_running_poll_swaps_only_the_tail_and_updates_sidebar():
    _seed("c9", running=True, done=False, log=[{"node": "planner", "status": "editing", "retry_count": 1}])
    resp = client.get("/conversations/c9", headers={"HX-Request": "true"})
    assert 'id="turn-tail"' in resp.text and "hx-get" in resp.text and "retry 1/3" in resp.text
    assert 'id="turn"' not in resp.text  # thread is left alone while running
    assert 'id="conv-c9"' in resp.text and 'hx-swap-oob="true"' in resp.text


def test_finished_poll_replaces_the_whole_turn_and_stops_polling():
    _seed("c10", running=False, done=True, messages=[
        {"role": "user", "content": "what region?"},
        {"role": "agent", "content": "eu-west-3."},
    ], result={"status": "answered", "agent_message": "eu-west-3."})
    resp = client.get("/conversations/c10", headers={"HX-Request": "true"})
    assert resp.headers["hx-retarget"] == "#turn"
    assert 'id="turn"' in resp.text and "eu-west-3." in resp.text
    assert "every 1s" not in resp.text  # polling ends

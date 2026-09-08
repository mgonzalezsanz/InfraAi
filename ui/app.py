import os
import re
import threading
import uuid
from html import escape

import markdown as _markdown
from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from graph import build_graph
from state import create_conversation_state

load_dotenv()


def _render_markdown(text: str | None) -> str:
    # escape first so any stray HTML in an LLM message renders inert, then let
    # Markdown turn **bold** / lists / etc. into real elements
    safe = escape(text or "")
    # LLMs routinely omit the blank line Markdown wants before a list
    safe = re.sub(r"(?<=\S)\n(?=(?:[-*+]|\d+\.)\s)", "\n\n", safe)
    html = _markdown.markdown(safe, extensions=["sane_lists"])
    # Make links open in new tab
    html = re.sub(r'<a href="([^"]*)">', r'<a href="\1" target="_blank" rel="noopener">', html)
    return html


# Server-remembered settings. The settings form overrides and remembers; a blank
# API-key field keeps the current one (a blank target repo clears it). Seeded
# from the environment so `.env` still works untouched. Local single-user dev
# server — the key lives only in this process's memory, is never rendered back,
# and is never written to a conversation record.
_settings = {
    "anthropic_api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
    "target_repo": os.environ.get("INFRAI_TARGET_REPO", ""),
}

app = FastAPI(title="InfraAI")
templates = Jinja2Templates(directory="ui/templates")
templates.env.filters["markdown"] = _render_markdown
app.mount("/static", StaticFiles(directory="ui/static"), name="static")

# Conversations for this app run, keyed by id, in creation order. In-memory only.
_conversations: dict[str, dict] = {}
_lock = threading.Lock()

# States a follow-up message can continue from in this phase.
_CONTINUABLE = {"needs_clarification", "answered"}


def _conversation_status(conv: dict) -> str:
    if conv["running"]:
        return "running"
    if conv["error"]:
        return "error"
    return conv["result"].get("status", "done")


def _agent_turn_text(result: dict, error: str | None) -> str:
    if error:
        return f"⚠️ {error}"
    if result.get("pr_url"):
        url = result['pr_url']
        return f"Opened a pull request: [{url}]({url})"
    if result.get("agent_message"):
        return result["agent_message"]
    if result.get("status") == "needs_human":
        return (
            "I couldn't reach a valid Terraform plan after 3 attempts. "
            "Start a new conversation with a more specific request."
        )
    return "Done."


def _execute(conv_id: str) -> None:
    conv = _conversations[conv_id]
    messages = list(conv["messages"])
    api_key, target_repo = conv["api_key"], conv["target_repo"]
    log, result, error = [], {}, None
    try:
        graph = build_graph(target_repo=target_repo or None, api_key=api_key or None, branch_key=conv_id)
        for update in graph.stream(create_conversation_state(messages), stream_mode="updates"):
            for node_name, node_update in update.items():
                result.update(node_update)
                log.append(
                    {
                        "node": node_name,
                        "status": node_update.get("status"),
                        "retry_count": result.get("retry_count", 0),
                    }
                )
                with _lock:
                    conv["log"] = list(log)
                    conv["result"] = dict(result)
    except Exception as exc:  # surfaced in the UI, not swallowed
        error = str(exc)

    with _lock:
        conv["messages"] = messages + [{"role": "agent", "content": _agent_turn_text(result, error)}]
        conv["error"] = error
        conv["running"] = False
        conv["done"] = True


def _start_turn(conv_id: str) -> None:
    with _lock:
        _conversations[conv_id].update(log=[], result={}, error=None, running=True, done=False)
    threading.Thread(target=_execute, args=(conv_id,), daemon=True).start()


def _sidebar_context(active_id: str | None = None) -> dict:
    with _lock:
        conversations = [
            {"id": c["id"], "label": c["title"], "status": _conversation_status(c)}
            for c in _conversations.values()
        ]
    return {
        "conversations": list(reversed(conversations)),
        "active_id": active_id,
        "target_repo": _settings["target_repo"],
        "has_api_key": bool(_settings["anthropic_api_key"]),
    }


def _conversation_context(conv: dict) -> dict:
    status = _conversation_status(conv)
    return {
        "conv": conv,
        "conv_id": conv["id"],
        "status": status,
        "continuable": conv["done"] and status in _CONTINUABLE,
    }


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", _sidebar_context())


@app.post("/settings")
def update_settings(request: Request, anthropic_api_key: str = Form(""), target_repo: str = Form("")):
    if anthropic_api_key.strip():
        _settings["anthropic_api_key"] = anthropic_api_key.strip()
    _settings["target_repo"] = target_repo.strip()
    return RedirectResponse(request.headers.get("referer") or "/", status_code=303)


@app.post("/runs")
def create_conversation(request: Request, user_request: str = Form(...)):
    user_request = user_request.strip()
    conv_id = uuid.uuid4().hex[:8]
    with _lock:
        _conversations[conv_id] = {
            "id": conv_id,
            "title": user_request,
            "messages": [{"role": "user", "content": user_request}],
            "api_key": _settings["anthropic_api_key"],
            "target_repo": _settings["target_repo"],
            "log": [],
            "result": {},
            "error": None,
            "running": False,
            "done": False,
        }
    _start_turn(conv_id)
    return RedirectResponse(f"/conversations/{conv_id}", status_code=303)


@app.post("/conversations/{conv_id}/messages")
def add_message(request: Request, conv_id: str, message: str = Form(...)):
    conv = _conversations.get(conv_id)
    if conv is None:
        return RedirectResponse("/", status_code=303)
    message = message.strip()
    if message and not conv["running"] and _conversation_status(conv) in _CONTINUABLE:
        with _lock:
            conv["messages"] = conv["messages"] + [{"role": "user", "content": message}]
        _start_turn(conv_id)
    return RedirectResponse(f"/conversations/{conv_id}", status_code=303)


@app.get("/conversations/{conv_id}", response_class=HTMLResponse)
def get_conversation(request: Request, conv_id: str):
    conv = _conversations.get(conv_id)
    if conv is None:
        return RedirectResponse("/", status_code=303)
    ctx = _conversation_context(conv)
    if not request.headers.get("hx-request"):
        return templates.TemplateResponse(request, "conversation.html", {**ctx, **_sidebar_context(conv_id)})
    # htmx poll during a run: swap only the volatile tail (log + reply box), so
    # the message thread above is left untouched — no flash, no scroll jump.
    if conv["running"]:
        return templates.TemplateResponse(request, "turn_tail.html", {**ctx, "oob_sidebar": True})
    # run finished: replace the whole #turn once so the new agent message lands,
    # and polling stops (the fresh tail carries no hx-get).
    resp = templates.TemplateResponse(request, "turn_fragment.html", {**ctx, "oob_sidebar": True})
    resp.headers["HX-Retarget"] = "#turn"
    resp.headers["HX-Reswap"] = "outerHTML"
    return resp


@app.get("/runs/{conv_id}")
def _legacy_run_url(conv_id: str):
    return RedirectResponse(f"/conversations/{conv_id}", status_code=308)

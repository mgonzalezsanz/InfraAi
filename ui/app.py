import os
import re
import threading
import uuid
from html import escape

import markdown as _markdown
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from graph import build_graph
from state import create_initial_state


def _render_markdown(text: str | None) -> str:
    # escape first so any stray HTML in an LLM message renders inert, then let
    # Markdown turn **bold** / lists / etc. into real elements
    safe = escape(text or "")
    # LLMs routinely omit the blank line Markdown wants before a list
    safe = re.sub(r"(?<=\S)\n(?=(?:[-*+]|\d+\.)\s)", "\n\n", safe)
    return _markdown.markdown(safe, extensions=["sane_lists"])

# Server-remembered settings. The settings form overrides and remembers; a blank
# API-key field keeps the current one (a blank target repo clears it). Seeded
# from the environment so `.env` still works untouched. Local single-user dev
# server — the key lives only in this process's memory, is never rendered back,
# and is never written to a run record.
_settings = {
    "anthropic_api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
    "target_repo": os.environ.get("INFRAI_TARGET_REPO", ""),
}

app = FastAPI(title="InfraAI")
templates = Jinja2Templates(directory="ui/templates")
templates.env.filters["markdown"] = _render_markdown
app.mount("/static", StaticFiles(directory="ui/static"), name="static")

# Conversations for this app run, keyed by id, in creation order.
_runs: dict[str, dict] = {}
_lock = threading.Lock()

_TERMINAL_STATUSES = {"pr_open", "answered", "needs_clarification", "needs_human"}


def _execute(run_id: str, user_request: str, api_key: str, target_repo: str) -> None:
    log = []
    result = {}
    try:
        graph = build_graph(target_repo=target_repo or None, api_key=api_key or None)
        for update in graph.stream(create_initial_state(user_request), stream_mode="updates"):
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
                    _runs[run_id]["log"] = list(log)
                    _runs[run_id]["result"] = dict(result)
        with _lock:
            _runs[run_id]["done"] = True
    except Exception as exc:  # surfaced in the UI, not swallowed
        with _lock:
            _runs[run_id]["done"] = True
            _runs[run_id]["error"] = str(exc)


def _conversation_status(run: dict) -> str:
    if run["error"]:
        return "error"
    if not run["done"]:
        return "running"
    return run["result"].get("status", "done")


def _sidebar_context(active_id: str | None = None) -> dict:
    with _lock:
        conversations = [
            {"id": rid, "label": run["user_request"], "status": _conversation_status(run)}
            for rid, run in _runs.items()
        ]
    return {
        "conversations": list(reversed(conversations)),
        "active_id": active_id,
        "target_repo": _settings["target_repo"],
        "has_api_key": bool(_settings["anthropic_api_key"]),
    }


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", _sidebar_context())


@app.post("/settings")
def update_settings(
    request: Request,
    anthropic_api_key: str = Form(""),
    target_repo: str = Form(""),
):
    if anthropic_api_key.strip():
        _settings["anthropic_api_key"] = anthropic_api_key.strip()
    _settings["target_repo"] = target_repo.strip()
    return RedirectResponse(request.headers.get("referer") or "/", status_code=303)


@app.post("/runs")
def create_run(request: Request, user_request: str = Form(...)):
    run_id = uuid.uuid4().hex[:8]
    with _lock:
        _runs[run_id] = {"user_request": user_request, "log": [], "done": False, "error": None, "result": {}}
    threading.Thread(
        target=_execute,
        args=(run_id, user_request, _settings["anthropic_api_key"], _settings["target_repo"]),
        daemon=True,
    ).start()
    return RedirectResponse(f"/runs/{run_id}", status_code=303)


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def get_run(request: Request, run_id: str):
    with _lock:
        run = dict(_runs.get(run_id, {"user_request": "", "log": [], "done": True, "error": "Run not found", "result": {}}))
    # htmx polls the fragment; a direct visit / sidebar click renders the full page
    if request.headers.get("hx-request"):
        ctx = {"run_id": run_id, **run, "oob_sidebar": True, "sidebar_status": _conversation_status(run)}
        return templates.TemplateResponse(request, "run_fragment.html", ctx)
    return templates.TemplateResponse(request, "run_page.html", {"run_id": run_id, **run, **_sidebar_context(run_id)})

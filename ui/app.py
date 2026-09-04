import os
import threading
import uuid

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from graph import build_graph
from state import create_initial_state

# The repo InfraAI reads (context) and opens PRs against (pr agent). Unset ->
# context falls back to the bundled fixture.
TARGET_REPO = os.environ.get("INFRAI_TARGET_REPO")

app = FastAPI(title="InfraAI")
templates = Jinja2Templates(directory="ui/templates")
app.mount("/static", StaticFiles(directory="ui/static"), name="static")

_runs: dict[str, dict] = {}
_lock = threading.Lock()

_TERMINAL_STATUSES = {"pr_open", "answered", "needs_clarification", "needs_human"}


def _execute(run_id: str, user_request: str) -> None:
    log = []
    result = {}
    try:
        graph = build_graph(target_repo=TARGET_REPO)
        for update in graph.stream(create_initial_state(user_request), stream_mode="updates"):
            for node_name, node_update in update.items():
                log.append({"node": node_name, "status": node_update.get("status")})
                result.update(node_update)
                with _lock:
                    _runs[run_id]["log"] = list(log)
                    _runs[run_id]["result"] = dict(result)
        with _lock:
            _runs[run_id]["done"] = True
    except Exception as exc:  # surfaced in the UI, not swallowed
        with _lock:
            _runs[run_id]["done"] = True
            _runs[run_id]["error"] = str(exc)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@app.post("/runs", response_class=HTMLResponse)
def create_run(request: Request, user_request: str = Form(...)):
    run_id = uuid.uuid4().hex[:8]
    with _lock:
        _runs[run_id] = {"user_request": user_request, "log": [], "done": False, "error": None, "result": {}}
    threading.Thread(target=_execute, args=(run_id, user_request), daemon=True).start()
    return templates.TemplateResponse(request, "run_fragment.html", {"run_id": run_id, **_runs[run_id]})


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def get_run(request: Request, run_id: str):
    with _lock:
        run = dict(_runs.get(run_id, {"log": [], "done": True, "error": "Run not found", "result": {}}))
    ctx = {"run_id": run_id, **run}
    template = "run_fragment.html" if request.headers.get("hx-request") else "run_page.html"
    return templates.TemplateResponse(request, template, ctx)

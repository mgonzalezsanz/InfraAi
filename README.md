# InfraAi
Agentic system that turns a natural-language infra request into a validated, human-reviewed Terraform change — LangGraph multi-agent orchestration with a PR-gated safety model.

## Setup

**1. Python deps** (Python 3.12+):
```
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt
```
Checkov is pulled in automatically here — no separate install needed.

**2. External CLIs** — Terraform (validator agent) and Infracost (cost estimation):
```
winget install Hashicorp.Terraform
winget install Infracost.Infracost
```
Restart your terminal afterward (Windows PATH only refreshes for new sessions).

**3. `.env`** — copy `.env.example` to `.env` and fill in:
- `ANTHROPIC_API_KEY` — required, powers the Planner/Editor agents.
- `INFRACOST_API_KEY` — free tier: `infracost register`, then `infracost configure set api_key <key>` (or set it here instead).
- `LANGSMITH_*` — optional, only needed for trace observability.

**4. AWS** — `terraform validate` and Checkov/Infracost run with zero AWS access; `terraform plan` needs a **dedicated sandbox AWS account** (a separate AWS Organizations member account, not your main account) with a read-only `infrai-plan-role`:
- Create the sandbox account (console → AWS Organizations → Add an account).
- In it, create an IAM user (e.g. `infrai-plan`) with `policies/plan-role.json` as its permissions policy — read-only, with an explicit Deny on all mutating actions as a backstop.
- `aws configure --profile infrai-plan` with that user's access key. The Validator agent uses this exact profile name by default (override via `run_plan(files, aws_profile=...)`).

**5. GitHub CLI** — the PR agent shells out to `gh` (no separate PAT or GitHub App needed):
```
winget install GitHub.cli
gh auth login
```
Needs the `repo` scope (default when you log in interactively). Verify with `gh auth status`.

## Running it

Tests (fast, offline — every external tool call is faked):
```
.venv/Scripts/pytest -q
```

Interactively via LangGraph Studio (makes real Anthropic/Terraform/Checkov/Infracost calls):
```
.venv/Scripts/langgraph.exe dev --no-browser
```
Then open `https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024` and invoke the `infrai` graph with e.g. `{"user_request": "Add versioning to the app_data S3 bucket"}`.

Or via the web UI (run from the repo root so imports resolve):
```
.venv/Scripts/python.exe -m uvicorn ui.app:app --reload
```
Open `http://127.0.0.1:8000`, type a request, and watch the run log update live until it lands on a PR URL, an answer, or a clarifying question.

## Pointing this at a real target repo

`terraform apply` never runs here — it runs in the *target* repo's own CI, using
credentials this repo never holds. See
[`templates/target-repo-setup/SETUP.md`](templates/target-repo-setup/SETUP.md)
for the copy-in workflow, IAM policy, and config.

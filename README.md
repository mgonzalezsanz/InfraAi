# InfraAi
Agentic system that turns a natural-language infra request into a validated, human-reviewed Terraform change — LangGraph multi-agent orchestration with a PR-gated safety model.

> Resource/identifier names below use `infrai-` (one *a*) — short for InfraAi,
> dropped for brevity. It's the established convention across this repo's code,
> tests, and the live AWS/GitHub resources — not a typo, don't "fix" it to
> `infraai-` in one place only.

## Setup

Paths below use the venv layout for macOS/Linux (`.venv/bin/`). On Windows use
`.venv/Scripts/` and `.exe` suffixes.

**1. Python deps** (Python 3.12+):
```
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
```
Checkov is pulled in automatically here — no separate install needed.

**2. External CLIs** — Terraform (validator agent) and Infracost (cost estimation):
```
# macOS
brew install hashicorp/tap/terraform   # Terraform is no longer in brew core
brew install infracost

# Windows (restart the terminal afterward — PATH only refreshes for new sessions)
winget install Hashicorp.Terraform
winget install Infracost.Infracost
```
Infracost must be **v2.x or newer** (`run_infracost` calls `infracost scan --json`).
No API key needed.

**3. `.env`** — copy `.env.example` to `.env` and fill in:
- `ANTHROPIC_API_KEY` — required, powers the Planner/Editor agents.
- `INFRAI_TARGET_REPO` — `owner/repo` of the target repo the PR agent opens PRs
  against (e.g. `mgonzalezsanz/InfraAi-target-sandbox`). Required before running
  the PR agent.
- `LANGSMITH_*` — optional, only needed for trace observability.

**4. AWS** — `terraform validate` and Checkov/Infracost run with zero AWS access;
`terraform plan` needs a **dedicated sandbox AWS account** (a separate AWS
Organizations member account, not your main account) reached through a read-only
identity:
- Create the sandbox account (console → AWS Organizations → Add an account).
- In it, create an IAM user `infrai-plan` with `policies/plan-role.json` as an
  inline permissions policy — read-only, with an explicit Deny on all mutating
  actions as a backstop. (The policy is *named* `infrai-plan-role`; the principal
  is a user, not an assumable role.)
- `aws configure --profile infrai-plan` with that user's access key, region set
  to wherever the sandbox resources live. The Validator agent uses this exact
  profile name by default (override via `run_plan(files, aws_profile=...)`).
- Verify: `aws sts get-caller-identity --profile infrai-plan` resolves to the
  `infrai-plan` user, and `aws s3api create-bucket --bucket x --profile infrai-plan`
  fails with an explicit-deny `AccessDenied`.
- Multi-account tip: if you administer the sandbox from the Organizations
  management account, a `[profile infrai-sandbox]` with
  `role_arn = …:role/OrganizationAccountAccessRole` + `source_profile = <mgmt user>`
  gives you admin there without a second key. `infrai-plan` stays a direct
  read-only key — never point it at an admin role.

**5. GitHub CLI** — the PR agent shells out to `gh` (no separate PAT or GitHub App needed):
```
brew install gh          # macOS;  Windows: winget install GitHub.cli
gh auth login
```
Needs `repo` scope, plus `workflow` if any PR it opens touches `.github/workflows/`
(interactive login grants both). Verify with `gh auth status`.

## Running it

Tests (fast, offline — every external tool call is faked):
```
.venv/bin/pytest -q
```

Interactively via LangGraph Studio (makes real Anthropic/Terraform/Checkov/Infracost calls):
```
.venv/bin/langgraph dev --no-browser
```
Then open `https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024` and invoke the `infrai` graph with e.g. `{"user_request": "Add versioning to the app_data S3 bucket"}`.

Or via the web UI (run from the repo root so imports resolve):
```
.venv/bin/python -m uvicorn ui.app:app --reload
```
Open `http://127.0.0.1:8000`, type a request, and watch the run log update live until it lands on a PR URL, an answer, or a clarifying question.

## Pointing this at a real target repo

`terraform apply` never runs here — it runs in the *target* repo's own CI, using
credentials this repo never holds. See
[`templates/target-repo-setup/SETUP.md`](templates/target-repo-setup/SETUP.md)
for the copy-in workflow, IAM policy, and config.

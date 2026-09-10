import difflib

from state import InfraAIState, validation_errors
from tools.llm import get_editor_llm


def _build_prompt(
    change_plan: list[dict],
    repo_context: dict,
    prior_errors: list[str] | None = None,
    retry_count: int = 0,
) -> str:
    files_desc = "\n".join(
        f"--- {path} ---\n{content}" for path, content in repo_context.get("files", {}).items()
    )
    plan_desc = "\n".join(f"- {step['file']}: {step['action']} — {step['detail']}" for step in change_plan)
    prompt = (
        "You are the Editor agent in InfraAI. Given the plan below and the current "
        "content of the repo's Terraform files, produce the full new content for every "
        "file that needs to change. Keep changes minimal — don't rewrite unrelated files "
        "or unrelated parts of a file.\n\n"
        "Be reliable and trustworthy: preserve every existing resource, variable, and "
        "line not called for by the plan exactly as-is. Never remove or alter anything "
        "outside the plan's scope, and don't introduce resources the plan didn't ask for.\n\n"
        "Write each step's resources into the file its plan step names. If that file "
        "isn't in 'Current files' below, create it — return it as a new file_edit with "
        "its full content. Don't move existing resources between files or merge files.\n\n"
        f"Current files:\n{files_desc}\n\n"
        f"Plan:\n{plan_desc}"
    )
    if prior_errors:
        errors_desc = "\n".join(f"- {e}" for e in prior_errors)
        prompt += (
            f"\n\nYour previous attempt (retry {retry_count}/3) failed `terraform validate` / "
            "`terraform plan` with the errors below. The 'Current files' above already hold "
            "that attempt's output. Fix these specifically and leave the rest of your edit "
            "intact — still nothing outside the plan's scope.\n"
            f"{errors_desc}"
        )
    return prompt


def editor_agent(state: InfraAIState, *, llm=None, api_key=None) -> dict:
    """Produces a minimal diff via LLM. On a validator loop-back it's re-invoked with
    the previous attempt's terraform errors attached, so the retry is targeted rather
    than a blind repeat."""
    llm = llm or get_editor_llm(api_key)
    repo_context = state.get("repo_context", {})
    result = llm.invoke(
        _build_prompt(
            state.get("change_plan", []),
            repo_context,
            validation_errors(state.get("validation_result", {})),
            state.get("retry_count", 0),
        )
    )

    original_files = repo_context.get("files", {})
    updated_files = dict(original_files)
    diff_parts = []
    for edit in result.file_edits:
        original = original_files.get(edit.path, "")
        diff_lines = difflib.unified_diff(
            original.splitlines(keepends=True),
            edit.content.splitlines(keepends=True),
            fromfile=f"a/{edit.path}",
            tofile=f"b/{edit.path}",
        )
        diff_parts.append("".join(diff_lines))
        updated_files[edit.path] = edit.content

    return {
        "diff": "\n".join(diff_parts),
        "repo_context": {**repo_context, "files": updated_files},
        "status": "validating",
    }

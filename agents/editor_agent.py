import difflib

from state import InfraAIState
from tools.llm import get_editor_llm


def _build_prompt(change_plan: list[dict], repo_context: dict) -> str:
    files_desc = "\n".join(
        f"--- {path} ---\n{content}" for path, content in repo_context.get("files", {}).items()
    )
    plan_desc = "\n".join(f"- {step['file']}: {step['action']} — {step['detail']}" for step in change_plan)
    return (
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


def editor_agent(state: InfraAIState, *, llm=None) -> dict:
    """Produces a minimal diff via LLM, re-invoked with error context on validator failure."""
    llm = llm or get_editor_llm()
    repo_context = state.get("repo_context", {})
    result = llm.invoke(_build_prompt(state.get("change_plan", []), repo_context))

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

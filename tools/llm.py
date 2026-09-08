import os
from typing import Literal

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from pydantic import BaseModel

try:
    load_dotenv()
except UnicodeDecodeError:
    pass  # malformed .env (e.g. wrong encoding) shouldn't crash imports

DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")


class ChangeStep(BaseModel):
    file: str
    action: str
    detail: str


class PlannerOutput(BaseModel):
    intent: Literal["change", "question", "ambiguous"]
    change_plan: list[ChangeStep] = []
    agent_message: str | None = None
    title: str | None = None  # concise PR title, only for "change" intent


class FileEdit(BaseModel):
    path: str
    content: str


class EditorOutput(BaseModel):
    file_edits: list[FileEdit]


# No temperature/top_p/top_k here: claude-sonnet-5 rejects non-default sampling
# params with a 400 (adaptive thinking controls its own sampling). Reliability is
# steered via system-prompt instructions in each agent's prompt instead.


def _chat(api_key: str | None):
    # only pass api_key when we actually have one, so ChatAnthropic keeps its
    # own ANTHROPIC_API_KEY env fallback otherwise
    kwargs = {"model": DEFAULT_MODEL}
    if api_key:
        kwargs["api_key"] = api_key
    return ChatAnthropic(**kwargs)


def get_planner_llm(api_key: str | None = None):
    return _chat(api_key).with_structured_output(PlannerOutput)


def get_editor_llm(api_key: str | None = None):
    return _chat(api_key).with_structured_output(EditorOutput)

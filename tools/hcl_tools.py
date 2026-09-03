import re
import tempfile
from pathlib import Path

import hcl2

_SNAKE_CASE = re.compile(r"^[a-z][a-z0-9_]*$")


def _unquote(value):
    if isinstance(value, str) and len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


def parse_repo(path: str) -> dict:
    """Parse every *.tf file under `path` into a structured repo_context.

    Deterministic HCL parsing rather than an LLM summary — resource/variable
    extraction is a parsing task, not a language-understanding one, so this
    stays reliable and cheap to test.
    """
    root = Path(path)
    files: dict[str, str] = {}
    resources: list[str] = []
    variables: list[str] = []
    tag_keys: set[str] = set()
    names: list[str] = []

    for tf_file in sorted(root.rglob("*.tf")):
        relpath = str(tf_file.relative_to(root)).replace("\\", "/")
        files[relpath] = tf_file.read_text()

        with tf_file.open() as f:
            parsed = hcl2.load(f)

        for block in parsed.get("resource", []):
            for rtype, named in block.items():
                rtype = _unquote(rtype)
                for rname, attrs in named.items():
                    rname = _unquote(rname)
                    resources.append(f"{rtype}.{rname}")
                    names.append(rname)
                    tags = attrs.get("tags")
                    if isinstance(tags, dict):
                        tag_keys.update(tags.keys())

        for block in parsed.get("variable", []):
            for vname in block:
                vname = _unquote(vname)
                variables.append(vname)
                names.append(vname)

    naming = "snake_case" if names and all(_SNAKE_CASE.match(n) for n in names) else "mixed"

    return {
        "files": files,
        "resources": resources,
        "variables": variables,
        "conventions": {"naming": naming, "tagging": sorted(tag_keys)},
    }


def materialize(files: dict[str, str], directory: str) -> None:
    """Writes a repo_context["files"] dict back out to disk under `directory` (inverse of parse_repo)."""
    root = Path(directory)
    for relpath, content in files.items():
        path = root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def parse_files(files: dict[str, str]) -> dict:
    """`parse_repo` for an in-memory files dict — used by agents that hold an
    edited `repo_context["files"]` rather than a checkout on disk."""
    with tempfile.TemporaryDirectory(prefix="infrai-parse-") as tmpdir:
        materialize(files, tmpdir)
        return parse_repo(tmpdir)

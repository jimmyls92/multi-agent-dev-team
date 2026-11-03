"""
Validated tool handlers for the agents (DEC-036, DEC-042).

The LLM's tool arguments go through one Pydantic model per tool before the
tool runs: types are checked and every path is resolved inside the
workspace. Invalid arguments return an error string and the tool is not
called. The lab functions in file_io.py and code_executor.py stay
unconfined, so their tests keep calling them with any path.

Usage:
    from tools import TOOL_HANDLERS
    result = TOOL_HANDLERS["write_file"](path="hello.py", content="print(1)")
"""

import os
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .code_executor import exec_python
from .file_io import read_file, write_file

load_dotenv()

# DEC-045: resolved against the repo root, whatever directory the agent
# is started from.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_workspace_setting = os.getenv("WORKSPACE_DIR", "workspace")
if not _workspace_setting.strip():
    raise ValueError("WORKSPACE_DIR must not be empty")
WORKSPACE_DIR = (_REPO_ROOT / _workspace_setting).resolve()


def _resolve_in_workspace(path: str) -> str:
    # DEC-036, DEC-042: relative paths go under the workspace; anything that
    # ends up outside it (../, absolute path, symlink) is rejected.
    if not path.strip():
        raise ValueError("path must not be empty")
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = WORKSPACE_DIR / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(WORKSPACE_DIR):
        raise ValueError(
            f"path '{path}' is outside the workspace; "
            "use a path relative to the workspace"
        )
    return str(resolved)


class _PathArgs(BaseModel):
    # strict: "10" is not an int and 1 is not a path; extra arguments are errors.
    model_config = ConfigDict(extra="forbid", strict=True)

    path: str

    @field_validator("path")
    @classmethod
    def _confine(cls, path: str) -> str:
        return _resolve_in_workspace(path)


class ReadFileArgs(_PathArgs):
    pass


class WriteFileArgs(_PathArgs):
    content: str


class ExecPythonArgs(_PathArgs):
    # None lets exec_python use EXEC_TIMEOUT (DEC-037).
    timeout: int | None = Field(default=None, ge=1)


def _describe(error: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in err['loc']) or 'arguments'}: {err['msg']}"
        for err in error.errors()
    )


def _validated(model: type[BaseModel], tool: Callable[..., str]) -> Callable[..., str]:
    def handler(**kwargs) -> str:
        try:
            args = model.model_validate(kwargs)
        except ValidationError as e:
            return f"Error: invalid arguments for {tool.__name__}: {_describe(e)}"
        return tool(**args.model_dump())

    handler.__name__ = tool.__name__
    return handler


TOOL_HANDLERS = {
    "read_file": _validated(ReadFileArgs, read_file),
    "write_file": _validated(WriteFileArgs, write_file),
    "exec_python": _validated(ExecPythonArgs, exec_python),
}

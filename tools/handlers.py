"""Validated tool handlers for the agents (DEC-036, DEC-042).

The LLM's tool arguments go through one Pydantic model per tool before the
tool runs: types are checked and every path is resolved inside the
workspace. Invalid arguments return an error string and the tool is not
called. The lab functions in file_io.py and code_executor.py stay
unconfined, so their tests keep calling them with any path.

dispatch_tool is the single entry point for the agents: it never raises and
always returns a ToolOutcome, whose observation goes back to the LLM
(DEC-062) and whose execution carries the structured result of exec_python
(DEC-063).

Attributes:
    WORKSPACE_DIR: Absolute path of the agent's working directory, from the
        WORKSPACE_DIR environment variable resolved against the repo root
        (DEC-045).
    TOOL_HANDLERS: Tool name to validated handler.

Typical usage example:

    from tools import dispatch_tool
    outcome = dispatch_tool("write_file", {"path": "hello.py", "content": "print(1)"})
    print(outcome.observation)
"""

import os
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .code_executor import ExecutionResult, exec_python, run_python
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
    """Resolves a path inside the workspace.

    Args:
        path: Path sent by the LLM. Relative paths go under WORKSPACE_DIR.

    Returns:
        The resolved absolute path.

    Raises:
        ValueError: If the path is empty or ends up outside the workspace.
    """
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
    """Arguments shared by every tool: a path confined to the workspace.

    Validation is strict: no type coercion and no extra arguments (DEC-042).

    Attributes:
        path: Absolute path inside WORKSPACE_DIR, resolved by the validator.
    """
    # strict: "10" is not an int and 1 is not a path; extra arguments are errors.
    model_config = ConfigDict(extra="forbid", strict=True)

    path: str

    @field_validator("path")
    @classmethod
    def _confine(cls, path: str) -> str:
        """Resolves the path inside the workspace.

        Args:
            path: Path sent by the LLM.

        Returns:
            The resolved absolute path.

        Raises:
            ValueError: If the path is empty or outside the workspace.
        """
        return _resolve_in_workspace(path)


class ReadFileArgs(_PathArgs):
    """Arguments of read_file."""


class WriteFileArgs(_PathArgs):
    """Arguments of write_file.

    Attributes:
        content: Full text content to write.
    """
    content: str


class ExecPythonArgs(_PathArgs):
    """Arguments of exec_python.

    Attributes:
        timeout: Seconds to allow, at least 1. None lets exec_python use
            EXEC_TIMEOUT (DEC-037).
    """
    timeout: int | None = Field(default=None, ge=1)


def _describe(error: ValidationError) -> str:
    """Formats a validation error for the LLM.

    Args:
        error: The Pydantic validation error.

    Returns:
        One "field: message" item per problem, separated by "; ".
    """
    return "; ".join(
        f"{'.'.join(str(part) for part in err['loc']) or 'arguments'}: {err['msg']}"
        for err in error.errors()
    )


def _validate(
    model: type[BaseModel], tool_name: str, kwargs: dict
) -> BaseModel | str:
    """Validates the LLM's arguments for one tool.

    Args:
        model: Pydantic model that validates the tool's arguments.
        tool_name: Name of the tool, used in the error message.
        kwargs: Arguments sent by the LLM.

    Returns:
        The validated model, or an error string for the LLM if the
        arguments are invalid.
    """
    try:
        return model.model_validate(kwargs)
    except ValidationError as e:
        return f"Error: invalid arguments for {tool_name}: {_describe(e)}"


def _validated(model: type[BaseModel], tool: Callable[..., str]) -> Callable[..., str]:
    """Wraps a tool so its arguments are validated before it runs.

    Args:
        model: Pydantic model that validates the tool's arguments.
        tool: Lab tool function to call with the validated arguments.

    Returns:
        A handler that takes the LLM's arguments as keyword arguments.
    """
    def handler(**kwargs) -> str:
        """Validates the LLM's arguments and calls the tool.

        Args:
            **kwargs: Arguments sent by the LLM.

        Returns:
            The tool's result, or an error string without calling the tool
            if the arguments are invalid.
        """
        args = _validate(model, tool.__name__, kwargs)
        if isinstance(args, str):
            return args
        return tool(**args.model_dump())

    handler.__name__ = tool.__name__
    return handler


TOOL_HANDLERS = {
    "read_file": _validated(ReadFileArgs, read_file),
    "write_file": _validated(WriteFileArgs, write_file),
    "exec_python": _validated(ExecPythonArgs, exec_python),
}


class ToolOutcome(BaseModel):
    """Result of one tool call made through dispatch_tool (DEC-067).

    Attributes:
        observation: Text returned to the LLM; never empty (DEC-062).
        execution: Structured result when exec_python ran the script
            (DEC-063); None for any other tool or when the call was rejected
            before running.
    """
    model_config = ConfigDict(frozen=True)

    observation: str
    execution: ExecutionResult | None = None


def dispatch_tool(name: str, args: object) -> ToolOutcome:
    """Runs a tool requested by the LLM without ever raising (DEC-062).

    Args:
        name: Tool name chosen by the LLM.
        args: Arguments already parsed from the LLM's JSON. Anything that is
            not a dict is rejected; missing, extra or mistyped arguments are
            rejected by the Pydantic wrappers (DEC-042).

    Returns:
        A ToolOutcome. Unknown tools, non-object arguments, invalid arguments
        and unexpected errors give an "Error: ..." observation and no
        execution.
    """
    try:
        if name not in TOOL_HANDLERS:
            return ToolOutcome(
                observation=(
                    f"Error: unknown tool '{name}'. "
                    f"Available tools: {', '.join(TOOL_HANDLERS)}"
                )
            )
        if not isinstance(args, dict):
            return ToolOutcome(
                observation=(
                    f"Error: arguments for {name} must be a JSON object, "
                    f"got {type(args).__name__}"
                )
            )
        if name == "exec_python":
            # DEC-063: same validation as the wrapper, but keep the
            # structured result for the agent's loop.
            parsed = _validate(ExecPythonArgs, name, args)
            if isinstance(parsed, str):
                return ToolOutcome(observation=parsed)
            execution = run_python(**parsed.model_dump())
            return ToolOutcome(observation=execution.output, execution=execution)
        return ToolOutcome(observation=TOOL_HANDLERS[name](**args))
    except Exception as e:
        return ToolOutcome(observation=f"Error: tool '{name}' failed: {e}")

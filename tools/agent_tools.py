"""LangChain adapter for the agents' tools (DEC-076, DEC-072).

The only tool code that depends on LangChain. The implementations
(file_io.py, code_executor.py) and the validation layer (handlers.py) stay
framework-free; this module turns them into the tool objects that
``create_agent`` takes.

What the model sees is the unchanged lab schema of each tool
(tools/schemas.py) plus a required ``thought`` argument, so every action
carries its ReACT Thought (DEC-072). The tools are declared with that JSON
schema, so LangChain does not validate the arguments itself: the agent's
``wrap_tool_call`` middleware validates them first with ``check_tool_call``
(short errors, the tool never runs), and ``dispatch_tool`` validates them
again before running anything, so an invalid call never reaches a tool
(C4.6).

Not exported from ``tools/__init__.py``, so importing ``tools`` does not
import LangChain.

Attributes:
    CALL_MODELS: Tool name to the Pydantic model that validates a full tool
        call: the strict handler arguments plus ``thought``.
    AGENT_TOOLS: The LangChain tools, in the order of ALL_TOOL_SCHEMAS.

Typical usage example:

    from tools.agent_tools import AGENT_TOOLS, check_tool_call
    error = check_tool_call("read_file", {"thought": "...", "path": "a.py"})
"""

import copy

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from .code_executor import ExecutionResult
from .handlers import (
    ExecPythonArgs,
    ReadFileArgs,
    WriteFileArgs,
    _validate,
    dispatch_tool,
)
from .schemas import ALL_TOOL_SCHEMAS

_THOUGHT_DESCRIPTION = (
    "Your reasoning for this action: why you take it, given the last "
    "observation."
)


class _ThoughtArg(BaseModel):
    """The ReACT Thought every tool call carries (DEC-072).

    Attributes:
        thought: Why the model takes this action; must not be empty.
    """
    thought: str = Field(min_length=1)


class ReadFileCall(ReadFileArgs, _ThoughtArg):
    """Full read_file call: path confined to the workspace plus thought."""


class WriteFileCall(WriteFileArgs, _ThoughtArg):
    """Full write_file call: path, content and thought."""


class ExecPythonCall(ExecPythonArgs, _ThoughtArg):
    """Full exec_python call: path, optional timeout and thought."""


CALL_MODELS: dict[str, type[BaseModel]] = {
    "read_file": ReadFileCall,
    "write_file": WriteFileCall,
    "exec_python": ExecPythonCall,
}


def check_tool_call(name: str, args: object) -> str | None:
    """Validates a tool call before LangChain runs the tool (DEC-076).

    Args:
        name: Tool name chosen by the model.
        args: Arguments sent by the model, ``thought`` included.

    Returns:
        None if the call is valid; otherwise a short "Error: ..." message
        for the model, which never repeats the arguments.
    """
    if name not in CALL_MODELS:
        return (
            f"Error: unknown tool '{name}'. "
            f"Available tools: {', '.join(CALL_MODELS)}"
        )
    if not isinstance(args, dict):
        return (
            f"Error: arguments for {name} must be a JSON object, "
            f"got {type(args).__name__}"
        )
    parsed = _validate(CALL_MODELS[name], name, args)
    return parsed if isinstance(parsed, str) else None


def _parameters_with_thought(schema: dict) -> dict:
    """Returns a lab tool's parameters with a required ``thought`` first.

    ``thought`` goes first so the model writes its reasoning before the
    action's arguments. The lab schema itself is not modified.

    Args:
        schema: A lab tool schema from tools/schemas.py.

    Returns:
        A new JSON schema for the tool's parameters.
    """
    parameters = copy.deepcopy(schema["function"]["parameters"])
    parameters["properties"] = {
        "thought": {"type": "string", "description": _THOUGHT_DESCRIPTION},
        **parameters["properties"],
    }
    parameters["required"] = ["thought", *parameters.get("required", [])]
    return parameters


def _make_tool(schema: dict) -> StructuredTool:
    """Builds the LangChain tool for one lab tool schema.

    Args:
        schema: A lab tool schema from tools/schemas.py.

    Returns:
        A tool whose content is the observation for the model and whose
        artifact is the ``ExecutionResult`` of exec_python, or None
        (DEC-063, DEC-067).
    """
    name = schema["function"]["name"]

    def run(**kwargs: object) -> tuple[str, ExecutionResult | None]:
        """Drops the thought and runs the tool through dispatch_tool.

        Args:
            **kwargs: Arguments sent by the model, ``thought`` included.

        Returns:
            The observation and the structured execution result, if any.
            Never raises: dispatch_tool turns every failure into an
            "Error: ..." observation (DEC-062).
        """
        kwargs.pop("thought", None)  # DEC-072: recorded, never passed on
        outcome = dispatch_tool(name, kwargs)
        return outcome.observation, outcome.execution

    return StructuredTool.from_function(
        func=run,
        name=name,
        description=schema["function"]["description"],
        args_schema=_parameters_with_thought(schema),
        response_format="content_and_artifact",
    )


AGENT_TOOLS: list[StructuredTool] = [_make_tool(s) for s in ALL_TOOL_SCHEMAS]

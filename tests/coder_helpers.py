"""Shared data and scripted replies for the Coder node and graph tests.

The two-task state is a small project after the PM; the scripted tasks are
replies for ``tests.fakes.ScriptedChatModel`` whose scripts really run in
the ``isolated_run`` workspace.
"""

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from agents.coder_agent import MAX_ITERATIONS
from orchestration.state import ProjectState
from tests.fakes import tool_call_reply


def state_data() -> dict:
    """Returns a two-task state after the PM, with both tasks pending.

    Returns:
        A dict that ``ProjectState.model_validate`` accepts.
    """
    tasks = [
        {
            "task_id": "task_1",
            "title": "Create the greeting script",
            "description": "Create app.py that prints a greeting.",
            "acceptance_criteria": [
                {
                    "given": "the script exists",
                    "when": "it is run",
                    "then": "it prints a greeting",
                }
            ],
            "covers": ["REQ-1"],
            "files": ["app.py"],
            "priority": 1,
        },
        {
            "task_id": "task_2",
            "title": "Add a farewell",
            "description": "Extend app.py so it also prints a farewell.",
            "acceptance_criteria": [
                {
                    "given": "the greeting script",
                    "when": "it is run after the change",
                    "then": "it prints the greeting and then a farewell",
                }
            ],
            "covers": ["REQ-2"],
            "files": ["app.py"],
            "priority": 2,
        },
    ]
    return {
        "requirement": "Build a script that greets and says goodbye.",
        "spec": {
            "name": "Greeter",
            "description": "A Python script that greets the user and says goodbye.",
            "details": "## Overview\nA tiny script.",
            "acceptance_criteria": [
                {"id": "REQ-1", "text": "The script prints a greeting"},
                {"id": "REQ-2", "text": "The script prints a farewell"},
            ],
            "tasks": tasks,
        },
        "tasks": tasks,
    }


def two_task_state(**changes) -> ProjectState:
    """Returns the two-task state with some top-level fields changed.

    Args:
        **changes: Fields of ``ProjectState`` to replace.

    Returns:
        The validated state.
    """
    return ProjectState.model_validate({**state_data(), **changes})


def with_statuses(*statuses: str, **changes) -> ProjectState:
    """Returns the two-task state with the given task statuses.

    Args:
        *statuses: Status of task_1 and task_2, in order.
        **changes: Other fields of ``ProjectState`` to replace.

    Returns:
        The validated state.
    """
    data = state_data()
    data["tasks"] = [{**task, "status": status} for task, status in zip(data["tasks"], statuses)]
    return ProjectState.model_validate({**data, **changes})


def successful_task(content: str = 'print("hello")\n', path: str = "app.py") -> list:
    """Returns the replies of one task that writes a script, runs it and finishes.

    Args:
        content: Content of the script.
        path: Path of the script in the workspace.

    Returns:
        The replies for the plan call and the four loop calls.
    """
    return [
        tool_call_reply("Plan", {"steps": [f"Write {path}", f"Run {path}"]}, "call_plan"),
        tool_call_reply(
            "write_file", {"thought": "Write the script.", "path": path, "content": content}, "call_w"
        ),
        tool_call_reply("exec_python", {"thought": "Run it.", "path": path}, "call_e"),
        tool_call_reply(
            "Finish",
            {"thought": "It runs.", "main_file": path, "explanation": f"Wrote {path}."},
            "call_f",
        ),
    ]


def task_message(call: list[BaseMessage]) -> str:
    """Returns the task message of one model call (its first human message).

    Args:
        call: Messages received by one model call.

    Returns:
        The content of the first ``HumanMessage``.
    """
    return next(m.content for m in call if isinstance(m, HumanMessage))


def all_text(call: list[BaseMessage]) -> str:
    """Returns the content of every message of one model call, joined.

    Args:
        call: Messages received by one model call.

    Returns:
        The contents separated by newlines.
    """
    return "\n".join(str(m.content) for m in call)


def unsuccessful_task() -> list:
    """Returns the replies of one task that never finishes: a plan, then text only.

    Every text answer is nudged and counted, so the task ends at the
    iteration limit with status ``max_iterations``.

    Returns:
        The replies for the plan call and MAX_ITERATIONS loop calls.
    """
    return [tool_call_reply("Plan", {"steps": ["Think"]}, "call_plan")] + [
        AIMessage("Still thinking...") for _ in range(MAX_ITERATIONS)
    ]

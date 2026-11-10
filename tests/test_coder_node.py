"""Unit tests of the Coder node with a fake model (spec `lab_2_2_coder_node`).

Covers AC-2.2-2, AC-2.2-3, AC-2.2-4, AC-2.2-6, AC-2.2-8 and AC-2.2-9. Every
test runs in ``isolated_run``: the scripted scripts are really written and
executed in a temporary workspace, so ``result`` comes from a real run.
"""

from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.runtime import Runtime

from agents.coder_agent import CoderRunContext, make_coder_node
from orchestration.state import ProjectState
from tests.fakes import ScriptedChatModel, tool_call_reply


def _state_data() -> dict:
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


def _state(**changes) -> ProjectState:
    """Returns the two-task state with some top-level fields changed.

    Args:
        **changes: Fields of ``ProjectState`` to replace.

    Returns:
        The validated state.
    """
    return ProjectState.model_validate({**_state_data(), **changes})


def _with_statuses(*statuses: str, **changes) -> ProjectState:
    """Returns the two-task state with the given task statuses.

    Args:
        *statuses: Status of task_1 and task_2, in order.
        **changes: Other fields of ``ProjectState`` to replace.

    Returns:
        The validated state.
    """
    data = _state_data()
    data["tasks"] = [{**task, "status": status} for task, status in zip(data["tasks"], statuses)]
    return ProjectState.model_validate({**data, **changes})


def _successful_task(content: str = 'print("hello")\n', path: str = "app.py") -> list:
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


def _run_node(state: ProjectState, model: ScriptedChatModel) -> tuple[dict, ProjectState]:
    """Runs the Coder node once and applies its update to the state.

    Args:
        state: State before the node.
        model: Fake model of the Coder.

    Returns:
        The node's update and the state with the update applied (progress
        appended, as its reducer does).
    """
    update = make_coder_node(model)(state, Runtime(context=CoderRunContext()))
    merged = {**state.model_dump(), **update}
    merged["progress"] = state.progress + update.get("progress", [])
    return update, ProjectState.model_validate(merged)


def _task_message(call: list[BaseMessage]) -> str:
    """Returns the task message of one model call (its first human message).

    Args:
        call: Messages received by one model call.

    Returns:
        The content of the first ``HumanMessage``.
    """
    return next(m.content for m in call if isinstance(m, HumanMessage))


def _all_text(call: list[BaseMessage]) -> str:
    """Returns the content of every message of one model call, joined.

    Args:
        call: Messages received by one model call.

    Returns:
        The contents separated by newlines.
    """
    return "\n".join(str(m.content) for m in call)


def test_ac_2_2_2_runs_first_pending_task(isolated_run):
    model = ScriptedChatModel(_successful_task())

    _, state = _run_node(_state(), model)

    task_1, task_2 = state.tasks
    on_disk = (isolated_run / "app.py").read_text()
    assert task_1.status == "done"
    assert task_1.result.status == "success"
    assert task_1.result.plan
    assert "hello" in task_1.result.result
    assert task_1.result.code == on_disk
    assert state.code == {"app.py": on_disk}
    assert task_2.status == "pending"
    assert task_2.result is None
    assert state.error == ""


def test_ac_2_2_3_skips_finished_tasks(isolated_run):
    model = ScriptedChatModel(_successful_task())
    before = _with_statuses("done", "pending")

    _, state = _run_node(before, model)

    assert state.tasks[0] == before.tasks[0]
    assert state.tasks[1].status == "done"
    for call in model.calls:
        task_message = _task_message(call)
        assert "Extend app.py so it also prints a farewell." in task_message
        assert "Create app.py that prints a greeting." not in task_message


def test_ac_2_2_4_task_prompt_context(isolated_run):
    model = ScriptedChatModel(_successful_task())
    before = _with_statuses("done", "pending", code={"app.py": 'print("hello")\n'})

    _run_node(before, model)

    text = _all_text(model.calls[0])
    task_2 = before.tasks[1]
    assert "Greeter" in text
    assert "A Python script that greets the user and says goodbye." in text
    assert task_2.description in text
    for criterion in task_2.acceptance_criteria:
        assert criterion.given in text
        assert criterion.when in text
        assert criterion.then in text
    task_message = _task_message(model.calls[0])
    assert "Planned files: app.py" in task_message
    assert "Files already written in this run: app.py" in task_message


def test_ac_2_2_6_code_from_written_files(isolated_run):
    model = ScriptedChatModel([
        tool_call_reply("Plan", {"steps": ["Write the files", "Run app.py"]}, "call_plan"),
        tool_call_reply(
            "write_file",
            {"thought": "Escape.", "path": "../outside.py", "content": "x = 1\n"},
            "call_bad",
        ),
        tool_call_reply(
            "write_file",
            {"thought": "Helper.", "path": "helpers.py", "content": "GREETING = 'hi'\n"},
            "call_h",
        ),
        tool_call_reply(
            "write_file",
            {"thought": "App.", "path": "app.py", "content": "from helpers import GREETING\nprint(GREETING)\n"},
            "call_a",
        ),
        tool_call_reply("exec_python", {"thought": "Run it.", "path": "app.py"}, "call_e"),
        tool_call_reply(
            "Finish", {"thought": "It runs.", "main_file": "app.py", "explanation": "Done."}, "call_f"
        ),
    ])
    before = _state(code={"old.py": "OLD = True\n", "app.py": "stale\n"})

    _, state = _run_node(before, model)

    assert state.code == {
        "old.py": "OLD = True\n",
        "app.py": (isolated_run / "app.py").read_text(),
        "helpers.py": (isolated_run / "helpers.py").read_text(),
    }
    assert not (isolated_run.parent / "outside.py").exists()


def test_ac_2_2_8_progress_notes(isolated_run):
    model = ScriptedChatModel(_successful_task())

    update, _ = _run_node(_state(), model)

    first, second = update["progress"]
    assert "task_1" in first and "Create the greeting script" in first
    assert "task_1" in second and "done" in second


def test_ac_2_2_9_no_pending_task(isolated_run):
    model = ScriptedChatModel([])
    before = _with_statuses("done", "failed")

    _, state = _run_node(before, model)

    assert model.calls == []
    assert state.tasks == before.tasks
    assert "no pending task" in state.error

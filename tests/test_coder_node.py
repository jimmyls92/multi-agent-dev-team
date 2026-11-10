"""Unit tests of the Coder node with a fake model (spec `lab_2_2_coder_node`).

Covers AC-2.2-2 to AC-2.2-10. The node tests run in ``isolated_run``: the
scripted scripts are really written and executed in a temporary workspace,
so ``result`` comes from a real run.
"""

import logging

from langgraph.graph import END
from langgraph.runtime import Runtime

from agents.coder_agent import CoderRunContext, make_coder_node
from orchestration.graph import CODER_NODE, route_after_coder
from orchestration.state import ProjectState
from tests.coder_helpers import (
    all_text,
    successful_task,
    task_message,
    two_task_state,
    unsuccessful_task,
    with_statuses,
)
from tests.fakes import ScriptedChatModel, tool_call_reply


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


def test_ac_2_2_2_runs_first_pending_task(isolated_run):
    model = ScriptedChatModel(successful_task())

    _, state = _run_node(two_task_state(), model)

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
    model = ScriptedChatModel(successful_task())
    before = with_statuses("done", "pending")

    _, state = _run_node(before, model)

    assert state.tasks[0] == before.tasks[0]
    assert state.tasks[1].status == "done"
    for call in model.calls:
        message = task_message(call)
        assert "Extend app.py so it also prints a farewell." in message
        assert "Create app.py that prints a greeting." not in message


def test_ac_2_2_4_task_prompt_context(isolated_run):
    model = ScriptedChatModel(successful_task())
    before = with_statuses("done", "pending", code={"app.py": 'print("hello")\n'})

    _run_node(before, model)

    text = all_text(model.calls[0])
    task_2 = before.tasks[1]
    assert "Greeter" in text
    assert "A Python script that greets the user and says goodbye." in text
    assert task_2.description in text
    for criterion in task_2.acceptance_criteria:
        assert criterion.given in text
        assert criterion.when in text
        assert criterion.then in text
    message = task_message(model.calls[0])
    assert "Planned files: app.py" in message
    assert "Files already written in this run: app.py" in message


def test_ac_2_2_5_unsuccessful_task_failed(isolated_run):
    model = ScriptedChatModel(unsuccessful_task())

    _, state = _run_node(two_task_state(), model)

    task_1, task_2 = state.tasks
    assert task_1.status == "failed"
    assert task_1.result.status == "max_iterations"
    assert task_2.status == "pending"
    assert state.error == ""


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
    before = two_task_state(code={"old.py": "OLD = True\n", "app.py": "stale\n"})

    _, state = _run_node(before, model)

    assert state.code == {
        "old.py": "OLD = True\n",
        "app.py": (isolated_run / "app.py").read_text(),
        "helpers.py": (isolated_run / "helpers.py").read_text(),
    }
    assert not (isolated_run.parent / "outside.py").exists()


def test_ac_2_2_7_fatal_error_in_state(isolated_run, caplog):
    model = ScriptedChatModel([RuntimeError("API down")])

    with caplog.at_level(logging.ERROR):
        update, state = _run_node(two_task_state(), model)

    task_1, task_2 = state.tasks
    assert task_1.status == "failed"
    assert task_1.result is None
    assert task_2.status == "pending"
    assert "API down" in state.error
    assert any("API down" in note for note in update["progress"])
    assert any(
        record.levelno == logging.ERROR and "API down" in record.getMessage()
        for record in caplog.records
    )


def test_ac_2_2_8_progress_notes(isolated_run):
    model = ScriptedChatModel(successful_task())

    update, _ = _run_node(two_task_state(), model)

    first, second = update["progress"]
    assert "task_1" in first and "Create the greeting script" in first
    assert "task_1" in second and "done" in second


def test_ac_2_2_9_no_pending_task(isolated_run):
    model = ScriptedChatModel([])
    before = with_statuses("done", "failed")

    _, state = _run_node(before, model)

    assert model.calls == []
    assert state.tasks == before.tasks
    assert "no pending task" in state.error


def test_ac_2_2_10_router():
    assert route_after_coder(with_statuses("done", "pending")) == CODER_NODE
    assert route_after_coder(with_statuses("done", "failed")) == END
    assert route_after_coder(with_statuses("failed", "pending", error="RuntimeError: API down")) == END

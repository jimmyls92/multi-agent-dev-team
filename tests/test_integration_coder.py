"""Integration tests of the Coder graph's self-loop (spec `lab_2_2_coder_node`).

Covers AC-2.2-11 to AC-2.2-15. The graph runs from a prepared two-task state
(DEC-100) in ``isolated_run``: with a fake model, and for AC-2.2-15 with the
real Coder model on the graded demo (``--run-llm``).
"""

import subprocess
import sys

import pytest
from langchain_core.messages import SystemMessage

from agents.coder_agent import CoderRunContext
from orchestration.graph import CODER_NODE, build_coder_graph
from orchestration.state import ProjectState
from tests.coder_helpers import successful_task, two_task_state, unsuccessful_task
from tests.fakes import ScriptedChatModel


def _non_system(call) -> list:
    """Returns the messages of one model call that are not system messages.

    Args:
        call: Messages received by one model call.

    Returns:
        The window, task and turn messages of the call.
    """
    return [m for m in call if not isinstance(m, SystemMessage)]


def test_ac_2_2_11_window_per_run(isolated_run):
    first_task = successful_task('print("hello")\n')
    model = ScriptedChatModel(first_task + successful_task('print("hello")\nprint("bye")\n'))
    context = CoderRunContext()
    before = two_task_state()

    build_coder_graph(model).invoke(before, context=context)

    task_1_description = before.tasks[0].description
    task_2_calls = model.calls[len(first_task):]
    for call in task_2_calls:
        assert any(task_1_description in str(m.content) for m in _non_system(call))
    assert len(context.window) == 2

    second = ScriptedChatModel(successful_task() + successful_task())
    build_coder_graph(second).invoke(two_task_state(), context=CoderRunContext())

    only_message = _non_system(second.calls[0])
    assert len(only_message) == 1
    assert task_1_description in str(only_message[0].content)


def test_ac_2_2_12_self_loop_runs_all_tasks(isolated_run):
    model = ScriptedChatModel(
        successful_task('print("hello")\n') + successful_task('print("hello")\nprint("bye")\n')
    )
    before = two_task_state()

    chunks = list(build_coder_graph(model).stream(
        before, context=CoderRunContext(), stream_mode=["updates", "values"]
    ))

    coder_steps = [c for mode, c in chunks if mode == "updates" and CODER_NODE in c]
    final = ProjectState.model_validate([c for mode, c in chunks if mode == "values"][-1])
    assert len(coder_steps) == 2
    assert [t.status for t in final.tasks] == ["done", "done"]
    assert all(t.result is not None for t in final.tasks)
    assert len(final.progress) == 4
    assert final.code["app.py"] == 'print("hello")\nprint("bye")\n'
    assert final.code["app.py"] == (isolated_run / "app.py").read_text()
    assert final.requirement == before.requirement
    assert final.spec == before.spec
    assert final.error == ""


def test_ac_2_2_13_failed_task_then_next(isolated_run):
    model = ScriptedChatModel(unsuccessful_task() + successful_task())

    final = ProjectState.model_validate(
        build_coder_graph(model).invoke(two_task_state(), context=CoderRunContext())
    )

    assert [t.status for t in final.tasks] == ["failed", "done"]
    assert final.error == ""


def test_ac_2_2_14_fatal_error_ends_loop(isolated_run):
    model = ScriptedChatModel([RuntimeError("API down")])

    final = ProjectState.model_validate(
        build_coder_graph(model).invoke(two_task_state(), context=CoderRunContext())
    )

    assert "API down" in final.error
    assert [t.status for t in final.tasks] == ["failed", "pending"]
    assert len(model.calls) == 1


def _demo_state() -> ProjectState:
    """Returns the graded demo (/health and /echo) split into two pending tasks.

    Returns:
        The validated state, as the PM would leave it.
    """
    verify = (
        "Verify it by running app.py: its `if __name__ == '__main__':` block must "
        "use app.test_client() to call the endpoints and print the responses. "
        "Never call app.run()."
    )
    tasks = [
        {
            "task_id": "task_1",
            "title": "Create the Flask app with GET /health",
            "description": (
                "Create app.py with a Flask app named `app` and a GET /health route "
                'that returns the JSON {"status": "ok"} with HTTP 200. ' + verify
            ),
            "acceptance_criteria": [
                {
                    "given": "the app",
                    "when": "a client sends GET /health",
                    "then": 'it returns 200 with {"status": "ok"}',
                }
            ],
            "covers": ["REQ-1"],
            "files": ["app.py"],
            "priority": 1,
        },
        {
            "task_id": "task_2",
            "title": "Add POST /echo with input validation",
            "description": (
                "Edit app.py (read it first) to add a POST /echo route that returns "
                "the JSON body it receives with HTTP 200, and HTTP 400 with an error "
                "message when the body is not valid JSON. Keep GET /health unchanged. "
                + verify
            ),
            "acceptance_criteria": [
                {
                    "given": "the app",
                    "when": "a client sends POST /echo with a JSON body",
                    "then": "it returns 200 with the same body",
                },
                {
                    "given": "the app",
                    "when": "a client sends POST /echo with a non-JSON body",
                    "then": "it returns 400",
                },
            ],
            "covers": ["REQ-2", "REQ-3"],
            "files": ["app.py"],
            "priority": 2,
        },
    ]
    return ProjectState.model_validate({
        "requirement": (
            "Build a REST API with two endpoints: GET /health (returns {status: ok}) "
            "and POST /echo (returns the JSON body it receives). Include basic input "
            "validation."
        ),
        "spec": {
            "name": "Echo API",
            "description": "A Flask API with a health check and a validated echo endpoint.",
            "details": "## Overview\nA small Flask API.",
            "acceptance_criteria": [
                {"id": "REQ-1", "text": "GET /health returns {status: ok}"},
                {"id": "REQ-2", "text": "POST /echo returns the JSON body it receives"},
                {"id": "REQ-3", "text": "Invalid input to /echo is rejected with 400"},
            ],
            "tasks": tasks,
        },
        "tasks": tasks,
    })


# Runs in a subprocess with the workspace as working directory.
DEMO_BEHAVIOR_CHECK = """
from app import app
client = app.test_client()
health = client.get("/health")
assert health.status_code == 200 and health.get_json() == {"status": "ok"}, health.data
echo = client.post("/echo", json={"a": 1, "b": [2, 3]})
assert echo.status_code == 200 and echo.get_json() == {"a": 1, "b": [2, 3]}, echo.data
bad = client.post("/echo", data="not json", content_type="application/json")
assert bad.status_code == 400, bad.data
print("DEMO OK")
"""


@pytest.mark.llm
def test_ac_2_2_15_demo_tasks(isolated_run):
    final = ProjectState.model_validate(
        build_coder_graph().invoke(_demo_state(), context=CoderRunContext())
    )

    assert final.error == "", final.progress
    for task in final.tasks:
        assert task.status == "done", task.model_dump_json(indent=2)
        assert task.result.plan.strip()
        assert task.result.result.strip()
    apps = [path for path, content in final.code.items() if "/health" in content and "/echo" in content]
    assert len(apps) == 1, final.code.keys()
    assert final.code[apps[0]] == (isolated_run / apps[0]).read_text(encoding="utf-8")

    check = subprocess.run(
        [sys.executable, "-c", DEMO_BEHAVIOR_CHECK],
        cwd=(isolated_run / apps[0]).parent,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert check.returncode == 0, check.stderr
    assert "DEMO OK" in check.stdout

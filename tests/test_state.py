"""Tests for the shared project state.

Covers spec `lab_2_1_pm_agent` (AC-2.1-1, AC-2.1-2, AC-2.1-20, AC-2.1-22) and
spec `lab_2_2_coder_node` (AC-2.2-1).
"""

import pytest
from pydantic import ValidationError

from orchestration.state import Issue, ProjectState, QAReport, TaskState


def _state_data() -> dict:
    """Returns valid data for a state after the PM and part of the Coder's work.

    Returns:
        A dict that ``ProjectState.model_validate`` accepts, with a spec,
        two tasks, one code entry and progress notes.
    """
    tasks = [
        {
            "task_id": "task_1",
            "title": "Create the app",
            "description": "Create a Flask app with GET /health.",
            "acceptance_criteria": [
                {
                    "given": "the app is running",
                    "when": "a client sends GET /health",
                    "then": "it returns 200 with {'status': 'ok'}",
                }
            ],
            "covers": ["REQ-1"],
            "files": ["app.py"],
            "priority": 1,
        },
        {
            "task_id": "task_2",
            "title": "Add echo",
            "description": "Add POST /echo returning the JSON body.",
            "acceptance_criteria": [
                {
                    "given": "the app is running",
                    "when": "a client sends POST /echo with a JSON body",
                    "then": "it returns 200 with the same body",
                },
                {
                    "given": "the app is running",
                    "when": "a client sends POST /echo with a non-JSON body",
                    "then": "it returns 400",
                },
            ],
            "covers": ["REQ-2", "REQ-3"],
            "files": ["app.py"],
            "priority": 2,
        },
    ]
    return {
        "requirement": "Build a REST API with /health and /echo.",
        "spec": {
            "name": "Echo API",
            "description": "A Flask API with a health check and an echo endpoint.",
            "details": "## Overview\nA small API.",
            "acceptance_criteria": [
                {"id": "REQ-1", "text": "GET /health returns status ok"},
                {"id": "REQ-2", "text": "POST /echo returns the JSON body"},
                {"id": "REQ-3", "text": "Invalid input is rejected"},
            ],
            "tasks": tasks,
        },
        "tasks": [{**tasks[0], "status": "done"}, {**tasks[1], "status": "in_progress"}],
        "code": {"app.py": "from flask import Flask\n"},
        "progress": ["PM Agent: analysing requirement.", "PM Agent: 2 tasks created."],
        "error": "",
    }


def test_ac_2_1_1_state_rejects_invalid_values():
    data = ProjectState.model_validate(_state_data()).model_dump()
    data["tasks"][0]["status"] = "finished"

    with pytest.raises(ValidationError):
        ProjectState.model_validate(data)


def test_ac_2_1_2_state_json_round_trip():
    state = ProjectState.model_validate(_state_data())

    loaded = ProjectState.model_validate_json(state.model_dump_json())

    assert loaded == state


def test_ac_2_1_20_task_criteria_need_given_when_then():
    data = _state_data()
    del data["spec"]["tasks"][0]["acceptance_criteria"][0]["then"]

    with pytest.raises(ValidationError):
        ProjectState.model_validate(data)


@pytest.mark.parametrize("blank", ["", "   ", "\n\t"])
def test_ac_2_1_22_blank_text_rejected(blank):
    data = _state_data()
    data["requirement"] = blank

    with pytest.raises(ValidationError):
        ProjectState.model_validate(data)

    data = _state_data()
    data["spec"]["acceptance_criteria"][0]["text"] = blank

    with pytest.raises(ValidationError):
        ProjectState.model_validate(data)


def test_ac_2_2_1_task_result_round_trip():
    data = _state_data()
    data["tasks"][0]["result"] = {
        "status": "success",
        "plan": "1. Write app.py\n2. Run it",
        "code": "from flask import Flask\n",
        "explanation": "Created the Flask app.",
        "result": "exit code 0",
        "main_file": "app.py",
        "iterations": 3,
        "steps": [
            {
                "iteration": 1,
                "thought": "Write the app first.",
                "action": "write_file",
                "action_input": {"path": "app.py", "content": "from flask import Flask\n"},
                "observation": "Wrote app.py",
            }
        ],
    }
    state = ProjectState.model_validate(data)

    loaded = ProjectState.model_validate_json(state.model_dump_json())

    assert loaded == state
    assert loaded.tasks[0].result.status == "success"
    assert loaded.tasks[0].result.steps[0].action == "write_file"
    assert loaded.tasks[1].result is None


def _closed(data: dict, k: int, status: str, reason: str = "", reviews: int = 0,
            issue: str | None = None) -> TaskState:
    """Returns a copy of the first task of ``data`` closed in a given way.

    Args:
        data: State data with at least one task.
        k: Task number, for its ID and priority.
        status: The task's status.
        reason: Why it closed (DEC-198).
        reviews: Reviews it took.
        issue: Description of its one blocking issue; None for no report.

    Returns:
        The task.
    """
    report = None
    if issue is not None:
        blocking = Issue(severity="High", location=f"test_task_{k}.py::test_x", description=issue,
                         fix="Fix it.", source="test")
        report = QAReport(task_id=f"task_{k}", issues=[blocking], tests_failed=1)
    return TaskState(**{**data["tasks"][0], "task_id": f"task_{k}", "priority": k, "status": status,
                        "closed_reason": reason, "reviews": reviews, "qa_report": report})


def test_ac_3_3_38_outcome_and_report():
    data = _state_data()
    done = ProjectState(**{**data, "tasks": [_closed(data, 1, "done", reviews=1)]})

    assert done.outcome == "success"
    assert done.final_report() == ""

    tasks = [
        _closed(data, 1, "failed", "review limit reached", 5, "ISSUE-LIMIT"),
        _closed(data, 2, "failed", "the QA could not review it", 1, "ISSUE-QA"),
        _closed(data, 3, "failed", "A2A protocol error", 2, "ISSUE-PROTOCOL"),
        _closed(data, 4, "failed", "out of time", 0),
    ]
    open_run = ProjectState(**{**data, "tasks": tasks})
    report = open_run.final_report()

    assert open_run.outcome == "unresolved"
    for k, (reason, review, issue) in enumerate([
        ("review limit reached", 5, "ISSUE-LIMIT"),
        ("the QA could not review it", 1, "ISSUE-QA"),
        ("A2A protocol error", 2, "ISSUE-PROTOCOL"),
        ("out of time", 0, "not reviewed"),
    ], start=1):
        [block] = [b for b in report.split("\n- ") if b.lstrip("- ").startswith(f"task_{k} ")]
        assert reason in block and f"review {review}" in block and issue in block
    assert '"outcome":"unresolved"' in open_run.model_dump_json()

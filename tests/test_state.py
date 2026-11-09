"""Tests for the shared project state (spec `lab_2_1_pm_agent`, AC-2.1-1, AC-2.1-2, AC-2.1-20, AC-2.1-22)."""

import pytest
from pydantic import ValidationError

from orchestration.state import ProjectState


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

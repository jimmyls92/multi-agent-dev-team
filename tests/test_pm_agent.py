"""Tests for the PM Agent (spec `lab_2_1_pm_agent`, AC-2.1-5 .. AC-2.1-15)."""

import logging

import pytest
from langchain_core.messages import AIMessage

import agents.pm_agent as pm_agent
from agents.pm_agent import consolidate_tasks, make_pm_node
from orchestration.state import ProjectState, TaskSpec
from tests.fakes import ScriptedChatModel, tool_call_reply

REQUIREMENT = "Build a REST API with GET /health and POST /echo. Validate the input."


def _task(k: int) -> TaskSpec:
    """Returns a planned task whose fields all carry its number.

    Args:
        k: Task number; gives ``task_k``, ``REQ-k``, ``file_k.py`` and
            priority ``k``.

    Returns:
        The task.
    """
    return TaskSpec(
        task_id=f"task_{k}",
        title=f"Title {k}",
        description=f"Description {k}",
        acceptance_criteria=[{"given": f"given {k}", "when": f"when {k}", "then": f"then {k}"}],
        covers=[f"REQ-{k}"],
        files=[f"file_{k}.py"],
        priority=k,
    )


def test_ac_2_1_5_consolidates_to_eight():
    originals = [_task(k) for k in range(1, 12)]

    tasks = consolidate_tasks(originals)

    assert len(tasks) == 8
    assert [t.merged_from for t in tasks] == [
        ["task_1", "task_2"],
        ["task_3", "task_4"],
        ["task_5", "task_6"],
        ["task_7"],
        ["task_8"],
        ["task_9"],
        ["task_10"],
        ["task_11"],
    ]
    for task in tasks:
        absorbed = [o for o in originals if o.task_id in task.merged_from]
        assert task.acceptance_criteria == [c for o in absorbed for c in o.acceptance_criteria]
        assert task.covers == [r for o in absorbed for r in o.covers]
        assert task.files == [f for o in absorbed for f in o.files]
    assert [t.task_id for t in tasks] == [f"task_{k}" for k in range(1, 9)]
    assert [t.priority for t in tasks] == list(range(1, 9))


def test_ac_2_1_6_eight_or_fewer_unchanged():
    originals = [_task(k) for k in range(1, 9)]

    tasks = consolidate_tasks(originals)

    assert tasks == originals
    assert all(t.merged_from == [] for t in tasks)


# --- PM node (AC-2.1-7 .. AC-2.1-15) -----------------------------------------


def _spec_reply() -> AIMessage:
    """Returns a scripted valid spec draft with three criteria.

    Returns:
        The AI message calling the ``SpecDraft`` tool.
    """
    return tool_call_reply(
        "SpecDraft",
        {
            "name": "Echo API",
            "description": "A Flask API with a health check and an echo endpoint.",
            "details": "## Overview\nA small API.\n## Functional Requirements\n...",
            "acceptance_criteria": [
                "GET /health returns status ok",
                "POST /echo returns the JSON body",
                "Invalid input to /echo is rejected",
            ],
        },
        "spec_call",
    )


def _draft(k: int, covers: list[str]) -> dict:
    """Returns the arguments of one task draft.

    Args:
        k: Task number, used in its texts and file name.
        covers: Spec criterion IDs the task covers.

    Returns:
        The task draft as a dict.
    """
    return {
        "title": f"Task {k}",
        "description": f"Do part {k} of the API.",
        "acceptance_criteria": [{"given": "the app runs", "when": f"step {k}", "then": "it works"}],
        "covers": covers,
        "files": ["app.py"],
    }


def _tasks_reply(drafts: list[dict], call_id: str = "tasks_call") -> AIMessage:
    """Returns a scripted task list.

    Args:
        drafts: Task drafts, as built by ``_draft``.
        call_id: ID of the tool call.

    Returns:
        The AI message calling the ``TaskList`` tool.
    """
    return tool_call_reply("TaskList", {"tasks": drafts}, call_id)


def _valid_tasks(call_id: str = "tasks_call") -> AIMessage:
    """Returns a scripted task list of two tasks covering all three criteria.

    Args:
        call_id: ID of the tool call.

    Returns:
        The AI message calling the ``TaskList`` tool.
    """
    return _tasks_reply([_draft(1, ["REQ-1"]), _draft(2, ["REQ-2", "REQ-3"])], call_id)


def _run(model: ScriptedChatModel, state: ProjectState | None = None) -> ProjectState:
    """Runs the PM node and applies its update to the state.

    Args:
        model: Fake model for the PM.
        state: State before the node; a state with ``REQUIREMENT`` if None.

    Returns:
        The state after the update; ``progress`` holds the node's notes.
    """
    state = state or ProjectState(requirement=REQUIREMENT)
    update = make_pm_node(model)(state)
    return state.model_copy(update=update)


def _text(messages: list) -> str:
    """Returns the contents of a call's messages joined into one text.

    Args:
        messages: Messages received by one model call.

    Returns:
        All contents joined with spaces.
    """
    return " ".join(str(m.content) for m in messages)


def test_ac_2_1_7_writes_spec_and_tasks():
    model = ScriptedChatModel([_spec_reply(), _valid_tasks()])
    stale = ProjectState(requirement=REQUIREMENT, error="old failure")

    state = _run(model, stale)

    assert state.spec.name and state.spec.description and state.spec.details
    assert [c.id for c in state.spec.acceptance_criteria] == ["REQ-1", "REQ-2", "REQ-3"]
    assert [t.task_id for t in state.spec.tasks] == ["task_1", "task_2"]
    assert [t.task_id for t in state.tasks] == ["task_1", "task_2"]
    assert [t.priority for t in state.tasks] == [1, 2]
    assert all(t.status == "pending" for t in state.tasks)
    assert all(t.description and t.acceptance_criteria for t in state.tasks)
    assert state.error == ""


def test_ac_2_1_8_two_calls_in_order():
    model = ScriptedChatModel([_spec_reply(), _valid_tasks()])

    _run(model)

    assert len(model.calls) == 2
    assert REQUIREMENT in _text(model.calls[0])
    second = _text(model.calls[1])
    assert "Echo API" in second
    assert all(req in second for req in ["REQ-1", "REQ-2", "REQ-3"])


def test_ac_2_1_9_uncovered_criterion_retried():
    first = _tasks_reply([_draft(1, ["REQ-1"]), _draft(2, ["REQ-2"])], "tasks_1")
    model = ScriptedChatModel([_spec_reply(), first, _valid_tasks("tasks_2")])

    state = _run(model)

    assert len(model.calls) == 3
    assert "REQ-3 not covered" in _text(model.calls[2][-1:])
    assert [t.covers for t in state.tasks] == [["REQ-1"], ["REQ-2", "REQ-3"]]


def test_ac_2_1_10_unknown_criterion_rejected():
    bad = [_draft(1, ["REQ-1", "REQ-9"]), _draft(2, ["REQ-2", "REQ-3"])]
    model = ScriptedChatModel(
        [_spec_reply(), _tasks_reply(bad, "tasks_1"), _tasks_reply(bad, "tasks_2")]
    )

    state = _run(model)

    assert "REQ-9" in state.error
    assert state.spec is None
    assert state.tasks == []


def test_ac_2_1_11_single_task_retried():
    one = _tasks_reply([_draft(1, ["REQ-1", "REQ-2", "REQ-3"])], "tasks_1")
    model = ScriptedChatModel([_spec_reply(), one, _valid_tasks("tasks_2")])

    state = _run(model)

    assert len(state.tasks) == 2


def test_ac_2_3_18_task_needs_python_file():
    no_code = {**_draft(2, ["REQ-2", "REQ-3"]), "files": ["requirements.txt"]}
    first = _tasks_reply([_draft(1, ["REQ-1"]), no_code], "tasks_1")
    model = ScriptedChatModel([_spec_reply(), first, _valid_tasks("tasks_2")])

    state = _run(model)

    assert len(model.calls) == 3
    assert ".py" in _text(model.calls[2][-1:])
    assert state.error == ""
    assert all(any(f.endswith(".py") for f in t.files) for t in state.tasks)


def _eleven_tasks() -> AIMessage:
    """Returns a scripted list of 11 tasks where only the last one covers REQ-3.

    Dropping any task loses its requirement or its criteria, so only a real
    consolidation keeps everything.

    Returns:
        The AI message calling the ``TaskList`` tool.
    """
    drafts = [_draft(k, ["REQ-1"] if k <= 5 else ["REQ-2"]) for k in range(1, 11)]
    return _tasks_reply([*drafts, _draft(11, ["REQ-3"])])


def test_ac_2_1_12_node_consolidates():
    model = ScriptedChatModel([_spec_reply(), _eleven_tasks()])

    state = _run(model)

    assert len(model.calls) == 2
    assert len(state.spec.tasks) == 8
    assert len(state.tasks) == 8
    covered = {req for t in state.tasks for req in t.covers}
    assert covered == {"REQ-1", "REQ-2", "REQ-3"}
    merged = [task_id for t in state.tasks for task_id in t.merged_from]
    assert merged == [f"task_{k}" for k in range(1, 12)]
    whens = [c.when for t in state.tasks for c in t.acceptance_criteria]
    assert whens == [f"step {k}" for k in range(1, 12)]
    assert any("11" in note and "8" in note for note in state.progress)


def test_ac_2_1_13_progress_notes():
    model = ScriptedChatModel([_spec_reply(), _valid_tasks()])

    update = make_pm_node(model)(ProjectState(requirement=REQUIREMENT))

    assert isinstance(update["progress"], list)
    assert len(update["progress"]) == 3
    assert all(isinstance(note, str) for note in update["progress"])
    assert "2" in update["progress"][-1]


def test_ac_2_1_14_failure_in_state(caplog):
    model = ScriptedChatModel([RuntimeError("API down")])

    with caplog.at_level(logging.ERROR):
        state = _run(model)

    assert "API down" in state.error
    assert state.spec is None
    assert state.tasks == []
    assert any("API down" in note for note in state.progress)
    assert any(r.levelno == logging.ERROR and "API down" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize(
    ("env_value", "expected"), [("some/model", "some/model"), (None, "openai/gpt-4.1")]
)
def test_ac_2_1_15_uses_pm_model(monkeypatch, env_value, expected):
    requested = []

    def fake_get_chat_model(model_id):
        """Returns a fake model and records the requested model id.

        Args:
            model_id: OpenRouter model id the PM asked for.

        Returns:
            A fake model with valid outputs.
        """
        requested.append(model_id)
        return ScriptedChatModel([_spec_reply(), _valid_tasks()])

    if env_value is None:
        monkeypatch.delenv("PM_MODEL", raising=False)
    else:
        monkeypatch.setenv("PM_MODEL", env_value)
    monkeypatch.setattr(pm_agent, "get_chat_model", fake_get_chat_model)

    make_pm_node()(ProjectState(requirement=REQUIREMENT))

    assert requested == [expected]

"""Integration tests of the PM inside the graph (spec `lab_2_1_pm_agent`, AC-2.1-16, AC-2.1-17, AC-2.1-19).

The AC-2.1-19 test calls the real LLM and runs only with ``--run-llm``.
"""

import pytest

from main import DEMO_REQUIREMENT
from orchestration.graph import run
from orchestration.state import ProjectState
from tests.fakes import ScriptedChatModel
from tests.test_pm_agent import REQUIREMENT, _spec_reply, _valid_tasks


def test_ac_2_1_16_graph_writes_task_list():
    model = ScriptedChatModel([_spec_reply(), _valid_tasks()])

    state = run(REQUIREMENT, pm_model=model)

    assert isinstance(state, ProjectState)
    assert state.requirement == REQUIREMENT
    assert state.tasks
    for task in state.tasks:
        assert task.task_id and task.description and task.acceptance_criteria
        assert task.priority >= 1
        assert task.status == "pending"


def test_ac_2_1_17_graph_failure_reaches_end():
    model = ScriptedChatModel([RuntimeError("API down")])

    state = run(REQUIREMENT, pm_model=model)

    assert state.error
    assert state.tasks == []


@pytest.mark.llm
def test_ac_2_1_19_demo_requirement():
    state = run(DEMO_REQUIREMENT)

    assert state.error == ""
    assert 2 <= len(state.tasks) <= 8
    criterion_ids = {c.id for c in state.spec.acceptance_criteria}
    assert criterion_ids == {req for t in state.tasks for req in t.covers}
    spec_text = state.spec.model_dump_json().lower()
    assert "/health" in spec_text
    assert "/echo" in spec_text
    assert "valid" in spec_text

"""Integration tests of the PM inside the graph (spec `lab_2_1_pm_agent`, AC-2.1-16, AC-2.1-17, AC-2.1-19, AC-2.1-23).

Since Lab 2.3 the graph runs the Coder after the PM: these tests use a fake
Coder or stop right after the PM step, and run in ``isolated_run``. The
AC-2.1-19 test calls the real LLM and runs only with ``--run-llm``.
"""

from itertools import islice

import pytest

import agents.coder_agent as coder_agent
import agents.pm_agent as pm_agent
from agents.coder_agent import CoderRunContext
from main import DEMO_REQUIREMENT, main
from orchestration.graph import build_graph, run
from orchestration.state import ProjectState
from tests.coder_helpers import successful_task
from tests.fakes import ScriptedChatModel
from tests.test_pm_agent import REQUIREMENT, _eleven_tasks, _spec_reply, _valid_tasks


def test_ac_2_1_16_graph_writes_task_list(isolated_run):
    model = ScriptedChatModel([_spec_reply(), _valid_tasks()])
    coder = ScriptedChatModel([])
    values = build_graph(pm_model=model, coder_model=coder).stream(
        ProjectState(requirement=REQUIREMENT), context=CoderRunContext(), stream_mode="values"
    )

    _, after_pm = islice(values, 2)

    state = ProjectState.model_validate(after_pm)
    assert coder.calls == []
    assert state.requirement == REQUIREMENT
    assert state.tasks
    for task in state.tasks:
        assert task.task_id and task.description and task.acceptance_criteria
        assert task.priority >= 1
        assert task.status == "pending"


def test_ac_2_1_17_graph_failure_reaches_end(isolated_run):
    model = ScriptedChatModel([RuntimeError("API down")])

    state = run(REQUIREMENT, pm_model=model)

    assert state.error
    assert state.tasks == []


def test_ac_2_1_23_consolidation_visible_end_to_end(isolated_run, monkeypatch, capsys):
    model = ScriptedChatModel([_spec_reply(), _eleven_tasks()])
    coder = ScriptedChatModel([reply for _ in range(8) for reply in successful_task()])
    monkeypatch.setattr(pm_agent, "get_chat_model", lambda model_id: model)
    monkeypatch.setattr(coder_agent, "get_chat_model", lambda model_id: coder)

    code = main(["Build a large project"])

    out = capsys.readouterr().out
    assert code == 0
    assert "consolidated 11 tasks into 8" in out
    assert "merged from: task_1, task_2" in out
    assert "merged from: task_11" in out
    assert "covers: REQ-3" in out


@pytest.mark.llm
def test_ac_2_1_19_demo_requirement(isolated_run):
    state = run(DEMO_REQUIREMENT)

    assert state.error == ""
    assert 2 <= len(state.tasks) <= 8
    criterion_ids = {c.id for c in state.spec.acceptance_criteria}
    assert criterion_ids == {req for t in state.tasks for req in t.covers}
    spec_text = state.spec.model_dump_json().lower()
    assert "/health" in spec_text
    assert "/echo" in spec_text
    assert "valid" in spec_text

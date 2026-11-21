"""Unit tests of the team graph's routing and loop (specs `lab_2_3_pipeline`, `lab_3_3_a2a_loop`).

Covers AC-2.3-5, and AC-3.3-6, AC-3.3-27, AC-3.3-28 and AC-3.3-37
(DEC-178, DEC-180, DEC-184, DEC-197) with the fakes of
``test_integration_loop``.
"""

from langgraph.graph import END

import orchestration.graph as graph_module
from agents.coder_agent import CoderRunContext
from agents.pm_agent import MAX_TASKS
from orchestration.graph import CODER_NODE, QA_NODE, REFLECT_NODE, build_graph, route_after_pm, run
from orchestration.state import ProjectState
from tests.coder_helpers import state_data
from tests.fakes import ScriptedChatModel
from tests.test_integration_loop import FakeQA, _pm, _task_draft, approved, failing, loop  # noqa: F401
from tests.test_pm_agent import REQUIREMENT


def test_ac_2_3_5_route_after_pm():
    with_tasks = ProjectState.model_validate(state_data())
    failed = with_tasks.model_copy(update={"error": "RuntimeError: API down"})
    no_tasks = with_tasks.model_copy(update={"tasks": []})

    assert route_after_pm(with_tasks) == CODER_NODE
    assert route_after_pm(failed) == END
    assert route_after_pm(no_tasks) == END


def test_ac_3_3_6_settings_per_run(loop, monkeypatch):
    reviews = []
    for limit in ("2", "3"):
        monkeypatch.setenv("QA_MAX_ITERATIONS", limit)
        qa = FakeQA({"task_1": [failing]})

        final = run(REQUIREMENT, pm_model=_pm(_task_draft(1)), coder_model=ScriptedChatModel([]), qa_review=qa)

        reviews.append(final.tasks[0].reviews)
    assert reviews == [2, 3]


def test_ac_3_3_27_history_records(loop):
    qa = FakeQA({"task_1": [failing, approved]})

    final = run(REQUIREMENT, pm_model=_pm(_task_draft(1)), coder_model=ScriptedChatModel([]), qa_review=qa)

    first, second = final.tasks[0].history
    assert [first.review, second.review] == [1, 2]
    assert [first.explanation, second.explanation] == ["pass 1", "pass 2"]
    assert (first.high, first.medium, first.low, first.version) == (0, 0, 0, 0)
    assert (first.tests_passed, first.tests_failed) == (1, 1)
    assert [(t.name, t.criterion) for t in first.failed_tests] == [("test_order", "C0")]
    assert (second.tests_passed, second.tests_failed, second.failed_tests) == (2, 0, [])


def test_ac_3_3_28_graph_order(loop):
    qa = FakeQA({"task_1": [approved]})
    graph = build_graph(pm_model=_pm(_task_draft(1)), coder_model=ScriptedChatModel([]), qa_review=qa)

    steps = list(graph.stream(ProjectState(requirement=REQUIREMENT), context=CoderRunContext(),
                              stream_mode="updates"))

    assert [next(iter(step)) for step in steps] == [
        "pm", "coder", "reflect", "qa", "coder", "reflect", "qa"]
    coder, reflect, qa_step = (steps[k][node] for k, node in ((1, "coder"), (2, "reflect"), (3, "qa")))
    assert coder["tasks"][0].status == "in_progress"
    assert reflect["tasks"][0].status == "in_progress"
    assert qa_step["tasks"][0].status == "done"


def test_ac_3_3_37_step_limit(loop, monkeypatch):
    monkeypatch.setenv("QA_MAX_ITERATIONS", "2")
    monkeypatch.setattr(graph_module, "route_after_pass", lambda state: REFLECT_NODE)
    monkeypatch.setattr(graph_module, "route_after_reflect", lambda state: QA_NODE)
    monkeypatch.setattr(graph_module, "route_after_qa", lambda state: CODER_NODE)
    qa = FakeQA({"task_1": [failing], "task_2": [failing]})

    final = run(REQUIREMENT, pm_model=_pm(_task_draft(1)), coder_model=ScriptedChatModel([]), qa_review=qa)

    limit = 1 + MAX_TASKS * 2 * 3 + 3
    assert final.error == f"Run stopped: step limit of {limit} reached."
    assert [t.status for t in final.tasks] == ["failed", "failed"]
    assert final.outcome == "unresolved"

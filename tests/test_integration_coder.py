"""Integration tests of the Coder graph's self-loop (spec `lab_2_2_coder_node`).

Covers AC-2.2-11 to AC-2.2-14. The graph runs from a prepared two-task state
(DEC-100) with a fake model, in ``isolated_run``.
"""

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

    assert len(_non_system(second.calls[0])) == 1


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

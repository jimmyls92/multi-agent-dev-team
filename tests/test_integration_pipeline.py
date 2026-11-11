"""Integration tests of the PM + Coder graph through ``run()`` (spec `lab_2_3_pipeline`).

Covers AC-2.3-6 to AC-2.3-11 with fake PM and Coder models in
``isolated_run``.
"""

import orchestration.graph as graph_module
import orchestration.workspace as workspace_module
from agents.pm_agent import MAX_TASKS
from orchestration.graph import CODER_NODE, run
from tests.coder_helpers import all_text, successful_task
from tests.fakes import ScriptedChatModel
from tests.test_pm_agent import _draft, _spec_reply, _tasks_reply, _valid_tasks

REQUIREMENT = "Build an echo API"


def _position(progress: list[str], text: str) -> int:
    """Returns the index of the first progress note that contains a text.

    Args:
        progress: The run's progress notes.
        text: Text to look for.

    Returns:
        The index of the first matching note.

    Raises:
        AssertionError: If no note contains the text.
    """
    matches = [i for i, note in enumerate(progress) if text in note]
    assert matches, f"{text!r} not in {progress}"
    return matches[0]


def _two_task_models() -> tuple[ScriptedChatModel, ScriptedChatModel]:
    """Returns a fake PM that plans two tasks and a fake Coder that completes both.

    Returns:
        The PM model and the Coder model; the Coder writes ``app.py`` and
        then ``utils.py``.
    """
    pm = ScriptedChatModel([_spec_reply(), _valid_tasks()])
    coder = ScriptedChatModel(
        successful_task('print("app")\n', "app.py") + successful_task("X = 2\n", "utils.py")
    )
    return pm, coder


def test_ac_2_3_6_pm_to_coder_handoff(isolated_run):
    pm, coder = _two_task_models()

    final = run(REQUIREMENT, pm_model=pm, coder_model=coder)

    assert final.error == ""
    assert [t.task_id for t in final.tasks] == ["task_1", "task_2"]
    assert [t.status for t in final.tasks] == ["done", "done"]
    assert all(t.result is not None for t in final.tasks)
    tasks_per_call = len(successful_task())
    for task, first_call in zip(final.tasks, (coder.calls[0], coder.calls[tasks_per_call])):
        message = all_text(first_call)
        assert task.description in message
        for criterion in task.acceptance_criteria:
            assert criterion.when in message and criterion.then in message
    assert final.code == {
        "app.py": (isolated_run / "app.py").read_text(),
        "utils.py": (isolated_run / "utils.py").read_text(),
    }
    order = [
        _position(final.progress, "tasks created"),
        _position(final.progress, "starting task_1"),
        _position(final.progress, "task_1 done"),
        _position(final.progress, "starting task_2"),
        _position(final.progress, "task_2 done"),
    ]
    assert order == sorted(order)


def test_ac_2_3_7_pm_failure_skips_coder(isolated_run):
    pm = ScriptedChatModel([RuntimeError("API down")])
    coder = ScriptedChatModel([])

    final = run(REQUIREMENT, pm_model=pm, coder_model=coder)

    assert "API down" in final.error
    assert final.tasks == []
    assert coder.calls == []


def test_ac_2_3_8_run_archives_workspace(isolated_run):
    (isolated_run / "old.py").write_text("OLD = True\n")
    pm, coder = _two_task_models()

    final = run(REQUIREMENT, pm_model=pm, coder_model=coder)

    assert final.error == ""
    assert sorted(p.name for p in isolated_run.iterdir()) == ["app.py", "utils.py"]
    archived = list((isolated_run.parent / "workspace_history").glob("*/old.py"))
    assert len(archived) == 1
    assert str(archived[0].parent) in final.progress[0]
    assert "old.py" not in final.code


def test_ac_2_3_9_refused_archive_is_error(isolated_run, monkeypatch):
    (isolated_run / "keep.py").write_text("KEEP = True\n")
    monkeypatch.setattr(workspace_module, "REPO_ROOT", isolated_run)
    pm, coder = ScriptedChatModel([]), ScriptedChatModel([])

    final = run(REQUIREMENT, pm_model=pm, coder_model=coder)

    assert "archive" in final.error.lower()
    assert pm.calls == [] and coder.calls == []
    assert (isolated_run / "keep.py").read_text() == "KEEP = True\n"


def test_ac_2_3_10_step_limit_keeps_state(isolated_run, monkeypatch):
    monkeypatch.setattr(graph_module, "route_after_coder", lambda state: CODER_NODE)
    pm, coder = _two_task_models()

    final = run(REQUIREMENT, pm_model=pm, coder_model=coder)

    assert "step limit" in final.error
    assert _position(final.progress, "tasks created") >= 0
    assert _position(final.progress, "task_1 done") < _position(final.progress, "task_2 done")
    coder_steps = 2 + sum("no pending task" in note for note in final.progress)
    assert coder_steps <= MAX_TASKS + 2


def test_ac_2_3_11_eight_tasks_within_limit(isolated_run):
    drafts = [_draft(k, ["REQ-1", "REQ-2", "REQ-3"] if k == 1 else ["REQ-1"]) for k in range(1, 9)]
    pm = ScriptedChatModel([_spec_reply(), _tasks_reply(drafts)])
    coder_replies = []
    for k in range(1, 9):
        coder_replies += successful_task(f"print({k})\n", f"step_{k}.py")
    coder = ScriptedChatModel(coder_replies)

    final = run(REQUIREMENT, pm_model=pm, coder_model=coder)

    assert final.error == ""
    assert [t.task_id for t in final.tasks] == [f"task_{k}" for k in range(1, 9)]
    assert all(t.status == "done" for t in final.tasks)
    starts = [_position(final.progress, f"starting task_{k} ") for k in range(1, 9)]
    assert starts == sorted(starts)


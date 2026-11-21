"""Tests for the command-line entry point (specs `lab_2_1_pm_agent`, AC-2.1-18,
AC-2.1-21, and `lab_2_3_pipeline`, AC-2.3-12..AC-2.3-14).

Since Lab 2.3 ``main`` runs the Coder after the PM, so a run that reaches
the Coder uses a fake Coder in ``isolated_run``; since Lab 3.3 it also
evaluates clean and has a QA that approves, unless a test says otherwise
(DEC-197).
"""

import pytest

import agents.coder_agent as coder_agent
import agents.pm_agent as pm_agent
import agents.qa_agent as qa_agent
import main as main_module
from main import main
from orchestration.state import Issue, ProjectState, QAReport
from tests.coder_helpers import approving_review_steps, successful_task, unsuccessful_task
from tests.fakes import ScriptedChatModel
from tests.test_pm_agent import _draft, _spec_reply, _tasks_reply, _valid_tasks


def _use_model(monkeypatch, model: ScriptedChatModel) -> None:
    """Makes the PM use a fake model instead of the real one.

    Args:
        monkeypatch: Pytest's monkeypatch fixture.
        model: The fake model to return for any model id.
    """
    monkeypatch.setattr(pm_agent, "get_chat_model", lambda model_id: model)


def test_ac_2_1_18_main_output_and_exit_code(isolated_run, monkeypatch, capsys):
    drafts = [_draft(1, ["REQ-1"]), _draft(2, ["REQ-2", "REQ-3"])]
    drafts[0]["files"], drafts[1]["files"] = ["app.py"], ["validation.py"]
    _use_model(monkeypatch, ScriptedChatModel([_spec_reply(), _tasks_reply(drafts)]))
    coder = ScriptedChatModel(successful_task() + successful_task("X = 1\n", "validation.py"))
    monkeypatch.setattr(coder_agent, "get_chat_model", lambda model_id: coder)
    approving_review_steps(monkeypatch)

    code = main(["Build an echo API"])

    out = capsys.readouterr().out
    assert code == 0
    assert "Echo API" in out
    assert "task_1 · priority 1" in out
    assert "task_2 · priority 2" in out
    assert "files: app.py" in out
    assert "files: validation.py" in out
    for note in [
        "PM Agent: analysing requirement.",
        "PM Agent: spec complete — decomposing into tasks.",
        "PM Agent: 2 tasks created — handoff ready.",
    ]:
        assert note in out

    _use_model(monkeypatch, ScriptedChatModel([RuntimeError("API down")]))

    code = main(["Build an echo API"])

    out = capsys.readouterr().out
    assert code == 1
    assert "API down" in out


@pytest.mark.parametrize("requirement", ["", "   "])
def test_ac_2_1_21_main_rejects_empty_requirement(monkeypatch, capsys, requirement):
    model = ScriptedChatModel([])
    _use_model(monkeypatch, model)

    with pytest.raises(SystemExit) as exc_info:
        main([requirement])

    assert exc_info.value.code == 2
    assert "must not be empty" in capsys.readouterr().err
    assert model.calls == []


def _two_task_run(monkeypatch, coder_replies: list) -> None:
    """Makes ``main`` use a fake PM with two tasks, a fake Coder and a QA that approves.

    Args:
        monkeypatch: Pytest's monkeypatch fixture.
        coder_replies: The Coder's scripted replies for both tasks.
    """
    _use_model(monkeypatch, ScriptedChatModel([_spec_reply(), _valid_tasks()]))
    coder = ScriptedChatModel(coder_replies)
    monkeypatch.setattr(coder_agent, "get_chat_model", lambda model_id: coder)
    approving_review_steps(monkeypatch)


def _task_block(out: str, task_id: str) -> str:
    """Returns the printed lines of one task, from its header to the next task.

    Args:
        out: The printed output.
        task_id: ID of the task.

    Returns:
        The task's header line and its indented lines.
    """
    lines = out.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"  {task_id} · "))
    block = [lines[start]]
    for line in lines[start + 1:]:
        if not line.startswith("    "):
            break
        block.append(line)
    return "\n".join(block)


def test_ac_2_3_12_main_success(isolated_run, monkeypatch, capsys):
    _two_task_run(
        monkeypatch,
        successful_task('print("hello")\n') + successful_task('print("utils ready")\n', "utils.py"),
    )

    code = main(["Build an echo API"])

    out = capsys.readouterr().out
    assert code == 0
    first, second = _task_block(out, "task_1"), _task_block(out, "task_2")
    assert "· done ·" in first and "app.py" in first and "3 iterations" in first
    assert "hello" in first
    assert "· done ·" in second and "utils.py" in second and "utils ready" in second
    assert str(isolated_run) in out
    assert out.strip().splitlines()[-1] == "RESULT: success"


async def _fail_task_2(task) -> QAReport:
    """Stands for a QA that approves task_1 and fails task_2.

    Args:
        task: The task reviewed.

    Returns:
        An approved report for task_1; one failing test for any other.
    """
    if task.task_id == "task_1":
        return QAReport(task_id=task.task_id, tests_passed=1)
    issue = Issue(severity="High", location="test_task_2.py::test_x", description="assert False",
                  fix="Make it pass.", source="test")
    return QAReport(task_id=task.task_id, issues=[issue], tests_failed=1)


def test_ac_2_3_13_main_incomplete(isolated_run, monkeypatch, capsys):
    _two_task_run(monkeypatch, successful_task() + unsuccessful_task())
    monkeypatch.setattr(qa_agent, "run_qa", _fail_task_2)
    monkeypatch.setenv("QA_MAX_ITERATIONS", "1")

    code = main(["Build an echo API"])

    out = capsys.readouterr().out
    assert code == 1
    assert "· done ·" in _task_block(out, "task_1")
    assert "· failed ·" in _task_block(out, "task_2")
    assert out.strip().splitlines()[-1] == "RESULT: unresolved — task_2 not approved"
    assert "[FINAL REPORT]" in out and "review limit reached" in out
    assert "RESULT: success" not in out


def test_ac_2_3_14_main_error(isolated_run, monkeypatch, capsys):
    _use_model(monkeypatch, ScriptedChatModel([RuntimeError("API down")]))

    code = main(["Build an echo API"])

    out = capsys.readouterr().out
    assert code == 1
    last = out.strip().splitlines()[-1]
    assert last.startswith("RESULT: error")
    assert "API down" in last


def _final(status: str, error: str = "") -> ProjectState:
    """Returns a final state with two tasks, the second with the given status.

    Args:
        status: Status of task_2.
        error: The run's error.

    Returns:
        The state; a failed task_2 closed at the review limit.
    """
    from tests.test_state import _closed, _state_data

    data = _state_data()
    second = (_closed(data, 2, "failed", "review limit reached", 5, "ISSUE-X") if status == "failed"
              else _closed(data, 2, status, reviews=1))
    return ProjectState(**{**data, "error": error, "tasks": [_closed(data, 1, "done", reviews=1), second]})


@pytest.mark.parametrize(
    ("state", "verdict", "code"),
    [
        (_final("done"), "RESULT: success", 0),
        (_final("failed"), "RESULT: unresolved — task_2 not approved", 1),
        (_final("done", "RuntimeError: API down"), "RESULT: error — RuntimeError: API down", 1),
    ],
    ids=["success", "unresolved", "error"],
)
def test_ac_3_3_39_verdict(monkeypatch, capsys, state, verdict, code):
    monkeypatch.setattr(main_module, "run", lambda requirement: state)

    exit_code = main(["Build an echo API"])

    out = capsys.readouterr().out
    assert exit_code == code
    assert out.strip().splitlines()[-1] == verdict
    if code == 0 or "error" in verdict:
        assert "[FINAL REPORT]" not in out
    else:
        assert "[FINAL REPORT]" in out and "ISSUE-X" in out and "review 5" in out

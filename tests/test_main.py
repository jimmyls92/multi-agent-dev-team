"""Tests for the command-line entry point (spec `lab_2_1_pm_agent`, AC-2.1-18, AC-2.1-21).

Since Lab 2.3 ``main`` runs the Coder after the PM, so a run that reaches
the Coder uses a fake Coder in ``isolated_run``.
"""

import pytest

import agents.coder_agent as coder_agent
import agents.pm_agent as pm_agent
from main import main
from tests.coder_helpers import successful_task
from tests.fakes import ScriptedChatModel
from tests.test_pm_agent import _draft, _spec_reply, _tasks_reply


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

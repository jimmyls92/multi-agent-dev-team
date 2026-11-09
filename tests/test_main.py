"""Tests for the command-line entry point (spec `lab_2_1_pm_agent`, AC-2.1-18, AC-2.1-21)."""

import pytest

import agents.pm_agent as pm_agent
from main import main
from tests.fakes import ScriptedChatModel
from tests.test_pm_agent import _spec_reply, _valid_tasks


def _use_model(monkeypatch, model: ScriptedChatModel) -> None:
    """Makes the PM use a fake model instead of the real one.

    Args:
        monkeypatch: Pytest's monkeypatch fixture.
        model: The fake model to return for any model id.
    """
    monkeypatch.setattr(pm_agent, "get_chat_model", lambda model_id: model)


def test_ac_2_1_18_main_output_and_exit_code(monkeypatch, capsys):
    _use_model(monkeypatch, ScriptedChatModel([_spec_reply(), _valid_tasks()]))

    code = main(["Build an echo API"])

    out = capsys.readouterr().out
    assert code == 0
    assert "Echo API" in out
    for task_id, priority in [("task_1", 1), ("task_2", 2)]:
        assert task_id in out
        assert f"priority {priority}" in out
    assert "app.py" in out
    assert "PM Agent: analysing requirement." in out

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

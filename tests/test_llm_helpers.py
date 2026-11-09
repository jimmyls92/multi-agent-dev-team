"""Tests for the structured-call helper (spec `lab_2_1_pm_agent`, AC-2.1-3, AC-2.1-4)."""

import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel, Field

from agents.llm_helpers import StructuredOutputError, structured_call
from tests.fakes import ScriptedChatModel, tool_call_reply


class _Answer(BaseModel):
    """Toy schema for the helper tests.

    Attributes:
        value: A positive integer.
    """
    value: int = Field(ge=1)


def _answer(value: int, call_id: str) -> AIMessage:
    """Returns a scripted reply that calls the ``_Answer`` tool.

    Args:
        value: The ``value`` argument of the call.
        call_id: ID of the tool call.

    Returns:
        The scripted AI message.
    """
    return tool_call_reply("_Answer", {"value": value}, call_id)


def test_ac_2_1_3_corrective_retry():
    model = ScriptedChatModel([_answer(0, "c1"), _answer(5, "c2")])

    result = structured_call(model, _Answer, "Give a number.", "Pick one.")

    assert result == _Answer(value=5)
    assert len(model.calls) == 2
    second_call_text = " ".join(str(m.content) for m in model.calls[1])
    assert "greater than or equal to 1" in second_call_text


def test_ac_2_1_4_second_invalid_raises():
    model = ScriptedChatModel([_answer(0, "c1"), _answer(-1, "c2"), _answer(5, "c3")])

    with pytest.raises(StructuredOutputError, match="greater than or equal to 1") as exc_info:
        structured_call(model, _Answer, "Give a number.", "Pick one.")

    assert "-1" in str(exc_info.value)
    assert len(model.calls) == 2

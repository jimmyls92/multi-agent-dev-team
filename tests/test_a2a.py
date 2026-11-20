"""Tests of the A2A messages and the state mailbox (Lab 3.3, T1).

Covers spec `lab_3_3_a2a_loop` AC-3.3-1 .. AC-3.3-4 (DEC-175, DEC-176,
DEC-189).
"""

import logging
import uuid

import pytest
from pydantic import ValidationError

from orchestration.a2a import A2AMessage, A2AProtocolError, inbox, payload_model, send
from orchestration.state import Issue, ProjectState, QAReport


def _approved_report() -> dict:
    """Returns an approved QA report for ``task_1`` as a dict.

    Returns:
        A report with two passed tests and no issues.
    """
    return QAReport(task_id="task_1", tests_passed=2).model_dump(mode="json")


def _failed_report() -> dict:
    """Returns an unapproved QA report for ``task_1`` as a dict.

    Returns:
        A report with one passed test, one failed test and its issue.
    """
    issue = Issue(
        severity="High",
        location="test_task_1.py::test_insert_order",
        description="assert [1, 2, 3] == [3, 2, 1]",
        fix="Insert at the head of the list.",
        source="test",
    )
    return QAReport(task_id="task_1", issues=[issue], tests_passed=1, tests_failed=1).model_dump(
        mode="json"
    )


def _request(correlation_id: str = "c-1", review: int = 1) -> A2AMessage:
    """Returns a valid ``review_request`` from the Coder to the QA.

    Args:
        correlation_id: Correlation id of the request.
        review: Review number n.

    Returns:
        The message.
    """
    return A2AMessage(
        sender="coder",
        receiver="qa",
        intent="review_request",
        payload={"task_id": "task_1", "review": review, "limit": 5},
        correlation_id=correlation_id,
    )


def _reply(correlation_id: str, intent: str = "fix_instruction") -> A2AMessage:
    """Returns a valid reply from the QA to the Coder.

    Args:
        correlation_id: Correlation id the reply carries.
        intent: ``fix_instruction``, ``approved`` or ``unresolved``.

    Returns:
        The message.
    """
    payload = {"task_id": "task_1", "review": 1}
    payload["report"] = _approved_report() if intent == "approved" else _failed_report()
    if intent == "unresolved":
        payload["reason"] = "review limit reached"
    return A2AMessage(
        sender="qa", receiver="coder", intent=intent, payload=payload, correlation_id=correlation_id
    )


def _with(state: ProjectState, update: dict) -> ProjectState:
    """Returns the state after applying a ``send`` update, as the graph's reducer does.

    Args:
        state: State before the update.
        update: Update returned by ``send``.

    Returns:
        A new state with the update's messages appended.
    """
    return state.model_copy(update={"messages": state.messages + update["messages"]})


_VALID_REQUEST = {
    "sender": "coder",
    "receiver": "qa",
    "intent": "review_request",
    "payload": {"task_id": "task_1", "review": 1, "limit": 5},
}


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"sender": "pm"}, "sender"),
        ({"receiver": "pm"}, "receiver"),
        ({"intent": "bad_intent"}, "intent"),
        ({"receiver": "coder"}, "sender"),
        (
            {
                "intent": "approved",
                "payload": {"task_id": "task_1", "review": 1, "report": _approved_report()},
            },
            "intent",
        ),
        ({"sender": "qa", "receiver": "coder"}, "intent"),
        ({"payload": {"review": 1, "limit": 5}}, "payload"),
    ],
    ids=[
        "unknown-sender",
        "unknown-receiver",
        "unknown-intent",
        "sender-is-receiver",
        "approved-to-qa",
        "review-request-to-coder",
        "payload-without-task-id",
    ],
)
def test_ac_3_3_1_message_validation(changes, field):
    with pytest.raises(ValidationError, match=field):
        A2AMessage(**{**_VALID_REQUEST, **changes})


def test_ac_3_3_1_valid_messages_accepted():
    request = A2AMessage(**_VALID_REQUEST)
    assert uuid.UUID(request.correlation_id).version == 4
    for intent in ("fix_instruction", "approved", "unresolved"):
        reply = _reply("c-1", intent)
        assert reply.intent == intent
        assert payload_model(reply).task_id == "task_1"


@pytest.mark.parametrize(
    ("intent", "report"),
    [("approved", _failed_report), ("fix_instruction", _approved_report)],
    ids=["approved-with-failing-report", "fix-with-approved-report"],
)
def test_ac_3_3_1_report_matches_intent(intent, report):
    payload = {"task_id": "task_1", "review": 1, "report": report()}
    with pytest.raises(ValidationError, match="payload"):
        A2AMessage(sender="qa", receiver="coder", intent=intent, payload=payload)


def test_ac_3_3_2_reply_correlation():
    state = _with(ProjectState(requirement="r"), send(ProjectState(requirement="r"), _request("c-1")))

    with pytest.raises(A2AProtocolError, match="c-2"):
        send(state, _reply("c-2"))
    assert len(state.messages) == 1

    state = _with(state, send(state, _reply("c-1")))
    assert [m.correlation_id for m in state.messages] == ["c-1", "c-1"]


def test_ac_3_3_2_reply_needs_an_open_request():
    state = ProjectState(requirement="r")
    with pytest.raises(A2AProtocolError):
        send(state, _reply("c-1"))

    state = _with(state, send(state, _request("c-1")))
    state = _with(state, send(state, _reply("c-1")))
    with pytest.raises(A2AProtocolError, match="c-1"):
        send(state, _reply("c-1", "approved"))


def test_ac_3_3_3_send_and_inbox(caplog):
    caplog.set_level(logging.INFO, logger="orchestration.a2a")
    state = ProjectState(requirement="r")
    first, second = _request("c-1"), _reply("c-1")
    third = _request("c-2", review=2)

    for message in (first, second, third):
        update = send(state, message)
        assert update == {"messages": [message]}
        state = _with(state, update)

    assert inbox(state, "qa") == [first, third]
    assert inbox(state, "coder") == [second]
    records = [r.getMessage() for r in caplog.records if r.name == "orchestration.a2a"]
    assert len(records) == 3
    for record, message in zip(records, (first, second, third)):
        for part in ("coder", "qa", message.intent, "task_1", message.correlation_id):
            assert part in record
        assert f"review={message.payload['review']}" in record


def test_ac_3_3_4_messages_serializable():
    state = ProjectState(requirement="r")
    for message in (_request("c-1"), _reply("c-1"), _request("c-2", 2), _reply("c-2", "approved")):
        state = _with(state, send(state, message))
    state = state.model_copy(
        update={"messages": state.messages + [_request("c-3", 3), _reply("c-3", "unresolved")]}
    )

    restored = ProjectState.model_validate_json(state.model_dump_json())

    assert restored == state
    assert {m.intent for m in restored.messages} == {
        "review_request",
        "fix_instruction",
        "approved",
        "unresolved",
    }

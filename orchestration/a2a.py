"""A2A messages between the Coder and the QA, kept in the shared state (C3.5, DEC-175).

Every message carries ``sender``, ``receiver``, ``intent``, ``payload`` and
``correlation_id`` and validates itself: known agents and intent, an
intent its receiver accepts, and a payload its intent's model accepts
(DEC-189). Messages travel in ``ProjectState.messages``; nodes add them
with ``send``, which also checks that a reply answers the open request,
and read them with ``inbox``.

Typical usage example:

    request = A2AMessage(
        sender="coder",
        receiver="qa",
        intent="review_request",
        payload={"task_id": "task_1", "review": 1, "limit": 5},
    )
    update = send(state, request)  # returned by a graph node
"""

import logging
import uuid
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from orchestration.qa_report import NonEmptyStr, QAReport

if TYPE_CHECKING:  # the state imports this module (DEC-188)
    from orchestration.state import ProjectState

logger = logging.getLogger(__name__)

Agent = Literal["coder", "qa"]
Intent = Literal["review_request", "fix_instruction", "approved", "unresolved"]

# DEC-176: the Coder asks for reviews; the QA answers with one of three intents.
ACCEPTED_INTENTS: dict[str, frozenset[str]] = {
    "qa": frozenset({"review_request"}),
    "coder": frozenset({"fix_instruction", "approved", "unresolved"}),
}


class A2AProtocolError(ValueError):
    """Raised when a message breaks the conversation, e.g. a reply to no open request (DEC-170)."""


class ReviewRequest(BaseModel):
    """Payload of ``review_request``: the Coder asks the QA to review a task.

    Attributes:
        task_id: The task to review.
        review: Review number n, starting at 1 (DEC-163).
        limit: Reviews allowed for the task (``QA_MAX_ITERATIONS``).
    """
    model_config = ConfigDict(extra="forbid")

    task_id: NonEmptyStr
    review: int = Field(ge=1)
    limit: int = Field(ge=1)


class _Reply(BaseModel):
    """Fields shared by the QA's replies.

    Attributes:
        task_id: The task reviewed.
        review: Review number n the reply answers.
        report: The QA's report of that review.
    """
    model_config = ConfigDict(extra="forbid")

    task_id: NonEmptyStr
    review: int = Field(ge=1)
    report: QAReport


class Approved(_Reply):
    """Payload of ``approved``: the task's tests ran and all passed."""

    @model_validator(mode="after")
    def _report_approved(self) -> "Approved":
        """Checks that the report is approved.

        Returns:
            The payload unchanged.

        Raises:
            ValueError: If the report is not approved.
        """
        if not self.report.approved:
            raise ValueError("an approved reply needs an approved report")
        return self


class FixInstruction(_Reply):
    """Payload of ``fix_instruction``: tests failed and reviews are left."""

    @model_validator(mode="after")
    def _report_not_approved(self) -> "FixInstruction":
        """Checks that the report is not approved.

        Returns:
            The payload unchanged.

        Raises:
            ValueError: If the report is approved.
        """
        if self.report.approved:
            raise ValueError("a fix_instruction needs a report that is not approved")
        return self


class Unresolved(_Reply):
    """Payload of ``unresolved``: the task closes unapproved; the report is final.

    Attributes:
        reason: Why the task closes, e.g. "review limit reached".
    """
    reason: NonEmptyStr

    @model_validator(mode="after")
    def _report_not_approved(self) -> "Unresolved":
        """Checks that the report is not approved.

        Returns:
            The payload unchanged.

        Raises:
            ValueError: If the report is approved.
        """
        if self.report.approved:
            raise ValueError("an unresolved reply needs a report that is not approved")
        return self


PAYLOAD_MODELS: dict[str, type[BaseModel]] = {
    "review_request": ReviewRequest,
    "fix_instruction": FixInstruction,
    "approved": Approved,
    "unresolved": Unresolved,
}


class A2AMessage(BaseModel):
    """One A2A message between two agents (C3.5, DEC-175, DEC-189).

    Attributes:
        sender: Agent that sends the message.
        receiver: Agent the message is for; never the sender.
        intent: What the message asks or answers; the receiver must accept it.
        payload: The intent's payload, stored as its model's JSON dump.
        correlation_id: Id shared by a request and its reply; UUID4 by
            default.
    """
    model_config = ConfigDict(frozen=True)

    sender: Agent
    receiver: Agent
    intent: Intent
    payload: dict
    correlation_id: NonEmptyStr = Field(default_factory=lambda: str(uuid.uuid4()))

    @field_validator("payload")
    @classmethod
    def _payload_fits_intent(cls, payload: dict, info: ValidationInfo) -> dict:
        """Validates the payload with its intent's model and normalizes it.

        Args:
            payload: The raw payload.
            info: Fields validated so far; ``intent`` is missing if it was
                invalid, and then the payload is left to that error.

        Returns:
            The payload as its model's JSON dump.

        Raises:
            ValueError: If the payload does not fit the intent's model.
        """
        intent = info.data.get("intent")
        if intent is None:
            return payload
        model = PAYLOAD_MODELS[intent].model_validate(payload)
        return model.model_dump(mode="json")

    @model_validator(mode="after")
    def _agents_and_intent(self) -> "A2AMessage":
        """Checks that sender and receiver differ and the receiver accepts the intent.

        Returns:
            The message unchanged.

        Raises:
            ValueError: If the sender is the receiver or the receiver does
                not accept the intent.
        """
        if self.sender == self.receiver:
            raise ValueError(f"sender and receiver are both {self.sender!r}")
        if self.intent not in ACCEPTED_INTENTS[self.receiver]:
            raise ValueError(f"intent {self.intent!r} is not accepted by {self.receiver!r}")
        return self


def payload_model(message: A2AMessage) -> BaseModel:
    """Returns the message's payload as its intent's typed model.

    Args:
        message: A validated message.

    Returns:
        A ``ReviewRequest``, ``FixInstruction``, ``Approved`` or
        ``Unresolved``.
    """
    return PAYLOAD_MODELS[message.intent].model_validate(message.payload)


def _check_reply(messages: list[A2AMessage], reply: A2AMessage) -> None:
    """Checks that a reply answers the last request its receiver sent, still unanswered.

    Args:
        messages: Messages already in the state.
        reply: A reply about to be sent.

    Raises:
        A2AProtocolError: If there is no open request from the reply's
            receiver to its sender, or the reply carries another
            correlation id.
    """
    requests = [
        m
        for m in messages
        if m.intent == "review_request" and m.sender == reply.receiver and m.receiver == reply.sender
    ]
    if not requests:
        raise A2AProtocolError(
            f"{reply.intent} {reply.correlation_id!r} answers no review_request"
        )
    request = requests[-1]
    answered = any(
        m.correlation_id == request.correlation_id and m.intent != "review_request"
        for m in messages
    )
    if answered or reply.correlation_id != request.correlation_id:
        raise A2AProtocolError(
            f"{reply.intent} {reply.correlation_id!r} does not answer the open request "
            f"({request.correlation_id!r}, already answered: {answered})"
        )


def send(state: "ProjectState", message: A2AMessage) -> dict[str, list[A2AMessage]]:
    """Returns the state update that sends a message, after checking and logging it.

    Args:
        state: Current state; its messages are only read.
        message: A validated message.

    Returns:
        ``{"messages": [message]}``, for the state's append reducer.

    Raises:
        A2AProtocolError: If the message is a reply that does not answer
            the open request (DEC-189); it is never added to the state.
    """
    if message.intent != "review_request":
        _check_reply(state.messages, message)
    logger.info(
        "A2A %s -> %s intent=%s task=%s review=%s correlation_id=%s",
        message.sender,
        message.receiver,
        message.intent,
        message.payload["task_id"],
        message.payload["review"],
        message.correlation_id,
    )
    return {"messages": [message]}


def inbox(state: "ProjectState", agent: str) -> list[A2AMessage]:
    """Returns the messages sent to an agent, in send order.

    Args:
        state: Current state.
        agent: ``"coder"`` or ``"qa"``.

    Returns:
        The agent's messages, oldest first.
    """
    return [m for m in state.messages if m.receiver == agent]

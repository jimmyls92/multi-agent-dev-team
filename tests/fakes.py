"""Fake chat models shared by the agent tests."""

from typing import Any

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult


def tool_call_reply(name: str, args: dict, call_id: str = "call_1") -> AIMessage:
    """Returns an AI message that calls one tool.

    Args:
        name: Tool name; for structured output, the schema's class name.
        args: Arguments of the call.
        call_id: ID of the tool call.

    Returns:
        An ``AIMessage`` with empty content and one tool call.
    """
    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": call_id}])


class ScriptedChatModel(GenericFakeChatModel):
    """Chat model that returns scripted replies and records every call.

    A scripted reply that is an exception is raised instead of returned.

    Attributes:
        replies: Replies still to give, in call order.
        calls: Messages received by each call, in order.
    """
    replies: list[AIMessage | Exception] = []
    calls: list[list[BaseMessage]] = []

    def __init__(self, replies: list[AIMessage | Exception], **kwargs: Any):
        """Initialises the model with its replies.

        Args:
            replies: Replies in call order; an exception is raised when its
                turn comes.
            **kwargs: Extra arguments for ``GenericFakeChatModel``.
        """
        super().__init__(messages=iter([]), **kwargs)
        self.replies = list(replies)
        self.calls = []

    def bind_tools(self, *args: Any, **kwargs: Any) -> "ScriptedChatModel":
        """Returns the model itself; the scripted replies already hold the tool calls.

        Args:
            *args: Ignored.
            **kwargs: Ignored.

        Returns:
            This model.
        """
        return self

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> ChatResult:
        """Records the call and returns, or raises, the next scripted reply.

        Args:
            messages: Messages sent to the model.
            *args: Ignored.
            **kwargs: Ignored.

        Returns:
            The chat result with the next reply.

        Raises:
            Exception: The next scripted reply, when it is an exception.
            IndexError: If the model is called more times than scripted.
        """
        self.calls.append(list(messages))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return ChatResult(generations=[ChatGeneration(message=reply)])

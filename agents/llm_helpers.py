"""Helpers for calling the LLM, shared by the agents (DEC-094).

``structured_call`` asks the model for one output with a Pydantic schema
and gives it one chance to fix an invalid output (DEC-088, DEC-091).
``PYTHON_ENVIRONMENT`` tells every agent which packages the generated code
may use (DEC-121).

Typical usage example:

    spec = structured_call(model, SpecDraft, SPEC_PROMPT, requirement)

Attributes:
    PYTHON_ENVIRONMENT: Prompt rule naming the packages installed for the
        generated code.
"""

from typing import TypeVar

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, ToolMessage
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

# DEC-121: generated code runs with this project's interpreter; only Flask is
# installed for it (DEC-108), so naming it keeps agents off FastAPI and others.
PYTHON_ENVIRONMENT = (
    "The project is written in Python 3.11. Besides the standard library, the only "
    "third-party package installed is Flask: use Flask for any web server or API, and "
    "do not use FastAPI, requests or any other package, because they are not installed."
)


class StructuredOutputError(Exception):
    """Raised when the model gives no valid output within the allowed calls."""


def _last_validation_error(messages: list[BaseMessage]) -> str:
    """Returns the last validation error that ToolStrategy sent to the model.

    Called only when the run ended without a structured response, so the
    last ToolMessage is the error of the last attempt. ToolStrategy marks
    these messages with ``status="success"``, hence no status filter.

    Args:
        messages: Final messages of the agent run.

    Returns:
        The content of the last ToolMessage, or a fallback text when there
        is none (e.g. the model answered with plain text).
    """
    for message in reversed(messages):
        if isinstance(message, ToolMessage):
            return str(message.content)
    return "the model did not return the structured output"


def structured_call(
    model: BaseChatModel,
    schema: type[T],
    system_prompt: str,
    user_message: str,
    max_attempts: int = 2,
) -> T:
    """Returns the model's output for one request, validated against a schema.

    Runs a ``create_agent`` with no tools and ``ToolStrategy(schema)``. When
    an output fails validation, ToolStrategy sends the error back to the
    model, which tries again; ``max_attempts`` caps the number of model
    calls (DEC-088, DEC-091).

    Args:
        model: Chat model to call.
        schema: Pydantic model the output must validate against.
        system_prompt: Instructions for the model.
        user_message: The request.
        max_attempts: Maximum model calls, 2 = one corrective retry.

    Returns:
        The validated output as an instance of ``schema``.

    Raises:
        ValueError: If ``max_attempts`` is lower than 1.
        StructuredOutputError: If no output is valid within ``max_attempts``
            calls; the message holds the last validation error.
        Exception: Errors of the model call itself (API, network) propagate
            unchanged.
    """
    if max_attempts < 1:
        raise ValueError(f"max_attempts must be at least 1, got {max_attempts}")
    agent = create_agent(
        model,
        tools=[],
        system_prompt=system_prompt,
        response_format=ToolStrategy(schema),
        middleware=[ModelCallLimitMiddleware(run_limit=max_attempts, exit_behavior="end")],
    )
    state = agent.invoke({"messages": [("user", user_message)]})
    response = state.get("structured_response")
    if response is None:
        raise StructuredOutputError(
            f"No valid {schema.__name__} after {max_attempts} model calls: "
            f"{_last_validation_error(state['messages'])}"
        )
    return response

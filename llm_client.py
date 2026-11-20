"""Shared LLM client (DEC-002, DEC-034, DEC-075).

Every agent gets its chat model from here, so the provider is configured
in one place. Calls go to OpenRouter through LangChain's ``ChatOpenAI``:
"OpenAI" is the API protocol OpenRouter exposes for every model, so the
model can be any OpenRouter model that supports tool calling.

Typical usage example:

    from llm_client import get_chat_model
    model = get_chat_model("openai/gpt-4.1-mini")
    reply = model.invoke("Hello")
"""

import os
from functools import lru_cache

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from orchestration.settings import load_llm_timeout

load_dotenv()

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


def _require_api_key() -> str:
    """Returns the OpenRouter API key from the environment.

    Returns:
        The value of OPENROUTER_API_KEY.

    Raises:
        EnvironmentError: If OPENROUTER_API_KEY is not set in the environment.
    """
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "OPENROUTER_API_KEY is not set.\n"
            "Copy .env.example to .env and add your OpenRouter key."
        )
    return api_key


def get_chat_model(model: str) -> ChatOpenAI:
    """Returns the shared LangChain chat model for an OpenRouter model id.

    Reads OPENROUTER_API_KEY (required), OPENROUTER_BASE_URL (optional) and
    LLM_TIMEOUT (seconds per request, default 60) from the environment. The
    timeout is read on every call, so a new value applies to the next run
    (DEC-166, DEC-190). The model is a parameter so each agent can use a
    different one (C4.5). Retries stay at ``ChatOpenAI``'s defaults until
    Module 4 (C4.2).

    Args:
        model: OpenRouter model id, for example ``"openai/gpt-4.1-mini"``.

    Returns:
        The shared ``ChatOpenAI`` instance for that model and timeout.

    Raises:
        EnvironmentError: If OPENROUTER_API_KEY is not set in the environment.
        ValueError: If LLM_TIMEOUT is not an integer of at least 1.
    """
    return _cached_model(model, load_llm_timeout(os.environ))


@lru_cache(maxsize=None)  # DEC-190: one model object per model id and timeout
def _cached_model(model: str, timeout: int) -> ChatOpenAI:
    """Returns the chat model for a model id and a timeout, built once.

    Args:
        model: OpenRouter model id.
        timeout: Seconds each request may take.

    Returns:
        The ``ChatOpenAI`` instance.

    Raises:
        EnvironmentError: If OPENROUTER_API_KEY is not set in the environment.
    """
    return ChatOpenAI(
        model=model,
        base_url=os.getenv("OPENROUTER_BASE_URL", DEFAULT_BASE_URL),
        api_key=_require_api_key(),
        timeout=timeout,
    )

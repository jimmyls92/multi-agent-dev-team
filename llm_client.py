"""
Shared LLM client (DEC-002, DEC-034).

Every agent and tool gets its client from here, so the provider is
configured in one place. Calls go to OpenRouter through the official
OpenAI SDK.

Usage:
    from llm_client import get_client
    client = get_client()
    # Use exactly like the standard OpenAI client.
"""

import os
from functools import lru_cache

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


@lru_cache(maxsize=1)  # one client per process, shared by every caller
def get_client() -> OpenAI:
    """
    Return the shared OpenAI-compatible client pointed at OpenRouter.

    Reads OPENROUTER_API_KEY (required) and OPENROUTER_BASE_URL (optional)
    from the environment.

    Raises
    ------
    EnvironmentError
        If OPENROUTER_API_KEY is not set in the environment.
    """
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "OPENROUTER_API_KEY is not set.\n"
            "Copy .env.example to .env and add your OpenRouter key."
        )

    return OpenAI(
        base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        api_key=api_key,
    )

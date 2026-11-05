"""Coder Agent with two-tier memory (Lab 1.1, C1.2).

chat() runs one conversation turn; main() is the interactive loop.

Attributes:
    MODEL: OpenRouter model id, from the LLM_MODEL environment variable.
"""

import logging
import os
from llm_client import get_client
from memory import SlidingWindowBuffer, store_memory, build_context

MODEL = os.getenv("LLM_MODEL", "openai/gpt-4.1-mini")

logger = logging.getLogger(__name__)


class EmptyReplyError(RuntimeError):
    """The LLM answered with no content; the turn counts as failed (DEC-029)."""


def chat(user_input: str, window: SlidingWindowBuffer) -> str:
    """Runs one agent turn and returns the reply.

    Steps, in order:
      1. Stores the user input in long-term memory (DEC-019).
      2. Assembles the full message list with build_context().
      3. Calls the LLM with the assembled messages.
      4. Adds the user turn and the reply to the window (DEC-031).

    Args:
        user_input: The user's message.
        window: Short-term window of the conversation.

    Returns:
        The LLM's reply.

    Raises:
        EmptyReplyError: If the LLM returns an empty reply (DEC-029).
        Exception: Any other failure propagates (DEC-027). On any failure the
            window is left untouched (DEC-028).
    """
    store_memory(user_input)
    messages = build_context(user_input, window)

    response = get_client().chat.completions.create(model=MODEL, messages=messages)
    reply = response.choices[0].message.content
    if not reply or not reply.strip():
        raise EmptyReplyError(f"{MODEL} returned an empty reply")

    window.add("user", user_input)
    window.add("assistant", reply)
    return reply


def main():
    """Runs the interactive chat loop until the user types quit or exit.

    A failed turn is reported and the conversation goes on (DEC-030).
    """
    # DEC-023: the entry point configures logging; an invalid LOG_LEVEL fails here.
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())

    from memory import SLIDING_WINDOW_SIZE
    print("=== Coder Agent — Lab 1.1 ===")
    print(f"Short-term window: {SLIDING_WINDOW_SIZE} turns | Long-term: Chroma semantic store")
    print("Type 'quit' to exit.\n")

    window = SlidingWindowBuffer()
    turn = 0

    while True:
        user_input = input(f"[Turn {turn + 1}] You: ").strip()
        if user_input.lower() in ("quit", "exit"):
            break
        if not user_input:
            continue
        try:
            reply = chat(user_input, window)
        except Exception as exc:
            # DEC-030: a failed turn is reported and the conversation goes on.
            logger.error("Turn failed: %s: %s", type(exc).__name__, exc)
            logger.debug("Turn failure traceback", exc_info=True)
            print("Agent: [error] this turn failed, please try again.\n")
            continue
        turn += 1
        print(f"Agent: {reply}\n")


if __name__ == "__main__":
    main()
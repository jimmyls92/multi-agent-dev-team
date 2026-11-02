# agent.py
# Lab 1.1 — Coder Agent with two-tier memory
#
# chat() runs one conversation turn; main() is the interactive loop.

import logging
import os
from tools.memory import SlidingWindowBuffer, store_memory, build_context, llm_client

# Reuse the same OpenRouter client from memory.py (DEC-002)
client = llm_client
MODEL = os.getenv("LLM_MODEL", "openai/gpt-4.1-mini")

logger = logging.getLogger(__name__)


class EmptyReplyError(RuntimeError):
    """The LLM answered with no content; the turn counts as failed (DEC-029)."""


def chat(user_input: str, window: SlidingWindowBuffer) -> str:
    """
    Single agent turn. Steps in order:
      1. Call store_memory() to save the user input to long-term memory (DEC-019).
      2. Call build_context() to assemble the full message list.
      3. Call the LLM with the assembled messages.
      4. Add the user turn and the assistant reply to the sliding window (DEC-031).
      5. Return the reply string.

    Any failure propagates (DEC-027) and leaves the window untouched (DEC-028).
    """
    store_memory(user_input)
    messages = build_context(user_input, window)

    response = client.chat.completions.create(model=MODEL, messages=messages)
    reply = response.choices[0].message.content
    if not reply or not reply.strip():
        raise EmptyReplyError(f"{MODEL} returned an empty reply")

    window.add("user", user_input)
    window.add("assistant", reply)
    return reply


def main():
    # DEC-023: the entry point configures logging; an invalid LOG_LEVEL fails here.
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())

    from tools.memory import SLIDING_WINDOW_SIZE
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
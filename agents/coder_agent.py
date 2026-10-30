# agent.py
# Lab 1.1 — Coder Agent with two-tier memory
#
# The main loop is already written.
# TODO: implement the body of the chat() function.

import os
from tools.memory import SlidingWindowBuffer, store_memory, build_context, llm_client

# Reuse the same OpenRouter client from memory.py
client = llm_client
MODEL = os.getenv("LLM_MODEL", "openai/gpt-4.1-mini")


def chat(user_input: str, window: SlidingWindowBuffer) -> str:
    """
    Single agent turn. Steps in order:
      1. Call store_memory() to save the user input to long-term memory.
      2. Call window.add() to add the user turn to the sliding window.
      3. Call build_context() to assemble the full message list.
      4. Call the OpenAI API with the assembled messages.
      5. Call window.add() to add the assistant reply to the sliding window.
      6. Return the reply string.
    """
    # TODO: implement
    raise NotImplementedError


def main():
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
        reply = chat(user_input, window)
        turn += 1
        print(f"Agent: {reply}\n")


if __name__ == "__main__":
    main()
# test_memory.py
# Automated verification for Lab 1.1.
# Run from the repo root: python -m tests.test_memory

import importlib
import sys


def run():
    import tools.memory as mem
    importlib.reload(mem)
    import agents.coder_agent as ag
    importlib.reload(ag)

    window = mem.SlidingWindowBuffer()
    WINDOW_SIZE = mem.SLIDING_WINDOW_SIZE

    # Plant a fact at turn 1
    planted_fact = "My name is Priya and I am building a CLI tool in Python."
    ag.chat(planted_fact, window)

    # Advance past the window boundary with filler turns
    fillers = [
        "What is a decorator in Python?",
        "Show me an example using functools.wraps.",
        "What is the difference between args and kwargs?",
        "How do I write a context manager?",
        "Explain generator functions.",
        "What does __slots__ do?",
        "How does the GIL affect threading?",
    ]
    for msg in fillers[:WINDOW_SIZE + 1]:
        ag.chat(msg, window)

    # Turn 1 is now outside the window — answer must come from Chroma
    reply = ag.chat("What is my name and what am I building?", window)
    reply_lower = reply.lower()

    passed = "priya" in reply_lower and ("cli" in reply_lower or "command" in reply_lower)

    if passed:
        print("PASS — agent recalled the planted fact from long-term memory.")
    else:
        print("FAIL — agent did not recall the planted fact.")
        print(f"  Expected: response containing 'Priya' and 'CLI'")
        print(f"  Got: {reply}")
        sys.exit(1)


if __name__ == "__main__":
    run()
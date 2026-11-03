"""
Lab 1.2 — Agent Integration Demo
==================================

Run this AFTER all tests pass, from the repo root:
    pytest tests/test_file_io.py tests/test_code_executor.py -v
    python -m agents.tools_demo

This script wires your three tool handlers into an LLM function-calling
loop and issues a single coding task. A successful run demonstrates the
Lab 1.2 success criterion:

    The agent writes a Python file, executes it, reads the output,
    and reports the result — all in one agentic loop.

Project adaptations (DEC-034): moved from the lab's root `agent.py`; the
client comes from the shared `llm_client` (OpenRouter, DEC-002) and the model
from LLM_MODEL.
"""

import json
import os

from dotenv import load_dotenv

from llm_client import get_client
from tools import TOOL_HANDLERS
from tools.schemas import ALL_TOOL_SCHEMAS

load_dotenv()

MODEL = os.getenv("LLM_MODEL", "openai/gpt-4.1-mini")

TASK = (
    "Write a Python script called word_freq.py that reads a hardcoded "
    "sample string (use: 'to be or not to be that is the question'), "
    "counts the frequency of each word, and prints the top 5 most common "
    "words with their counts. Then execute it and report the output."
)

SYSTEM_PROMPT = """You are a Coder Agent. Use the available tools to complete coding tasks.

Available tools: read_file, write_file, exec_python

Rules:
- Always write code to a file before executing it.
- After execution, read back the file or report what you observed in stdout.
- If execution fails, read the error, fix the code, and try again (max 2 retries).
- When the task is complete, output DONE and give a one-paragraph summary
  of what you produced.
"""

MAX_ITERATIONS = 10


def dispatch_tool(name: str, arguments: str) -> str:
    """Parse the LLM's tool call and invoke the matching handler."""
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return (
            f"Error: unknown tool '{name}'. "
            f"Available tools: {list(TOOL_HANDLERS.keys())}"
        )
    try:
        args = json.loads(arguments)
    except json.JSONDecodeError as e:
        return f"Error: could not parse tool arguments as JSON: {e}"
    return handler(**args)


def run_agent(task: str) -> None:
    client = get_client()

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]

    print(f"\n{'=' * 60}")
    print(f"TASK: {task}")
    print(f"{'=' * 60}\n")

    for iteration in range(MAX_ITERATIONS):
        print(f"--- Iteration {iteration + 1} ---")

        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=ALL_TOOL_SCHEMAS,
            tool_choice="auto",
        )

        message = response.choices[0].message

        # No tool call → agent has produced its final answer
        if not message.tool_calls:
            print(f"\nAGENT: {message.content}")
            if message.content and "DONE" in message.content.upper():
                print("\n✓ Task complete.")
            break

        # Append the assistant turn (with its tool calls) to history
        messages.append(message)

        # Dispatch each tool call and collect results
        tool_results = []
        for tool_call in message.tool_calls:
            name = tool_call.function.name
            args_raw = tool_call.function.arguments
            preview = args_raw[:120] + ("..." if len(args_raw) > 120 else "")
            print(f"  → {name}({preview})")

            result = dispatch_tool(name, args_raw)
            result_preview = result[:200] + ("..." if len(result) > 200 else "")
            print(f"  ← {result_preview}")

            tool_results.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            })

        messages.extend(tool_results)

    else:
        print(f"\n⚠ Reached max iterations ({MAX_ITERATIONS}) without a DONE signal.")


if __name__ == "__main__":
    run_agent(TASK)
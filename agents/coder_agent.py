"""Coder Agent with two-tier memory and a ReACT loop (Labs 1.1-1.3).

The LLM answers in the lab's text format (Thought / Action / Action Input or
FINAL ANSWER); every response is parsed into a Pydantic step before anything
acts on it (DEC-060). run_agent() runs one task and returns a CoderResult;
chat() wraps it for one session message; main() is the command line
(interactive session or a single task).

Attributes:
    MODEL: OpenRouter model id, from the LLM_MODEL environment variable.
    MAX_ITERATIONS: LLM calls allowed per task (C1.4).
    TOOL_NAMES: Names of the tools the agent may call.
    REACT_SYSTEM_PROMPT: System prompt of the ReACT loop, with the tool list
        generated from the schemas (DEC-061).
    MAX_ITERATIONS_MESSAGE: Reply of chat() when a task hits the limit.
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from llm_client import get_client
from memory import SlidingWindowBuffer, build_context, store_memory, store_outcome
from tools import ExecutionResult, dispatch_tool
from tools.handlers import resolve_in_workspace
from tools.schemas import ALL_TOOL_SCHEMAS

MODEL = os.getenv("LLM_MODEL", "openai/gpt-4.1-mini")
MAX_ITERATIONS = 10  # C1.4

logger = logging.getLogger(__name__)

# --- ReACT prompt (DEC-061) --------------------------------------------------

TOOL_NAMES = tuple(schema["function"]["name"] for schema in ALL_TOOL_SCHEMAS)


def _describe_tools(schemas: list[dict]) -> str:
    """Renders the tool schemas as a plain-text list for the prompt (DEC-061).

    Args:
        schemas: Tool schemas in the OpenAI function format.

    Returns:
        One block per tool: its name and description, then one line per
        argument with its type, whether it is required and its description.
    """
    blocks = []
    for schema in schemas:
        function = schema["function"]
        parameters = function["parameters"]
        required = set(parameters.get("required", []))
        lines = [f"- {function['name']}: {function['description']}"]
        for name, spec in parameters["properties"].items():
            need = "required" if name in required else "optional"
            lines.append(f"    - {name} ({spec['type']}, {need}): {spec['description']}")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


REACT_SYSTEM_PROMPT = f"""You are an expert Python developer working as an autonomous coding agent.
You solve the user's task step by step with tools, reasoning before every action.

Tools (file paths are relative to your workspace directory; scripts run with
their own directory as the working directory):
{_describe_tools(ALL_TOOL_SCHEMAS)}

Answer in exactly one of these two formats, and nothing else.

To use a tool:
Thought: <your reasoning>
Action: <one tool name>
Action Input: <a JSON object with the tool arguments>

To finish:
Thought: <your reasoning>
FINAL ANSWER: {{"main_file": "<path of the main file you wrote>", "explanation": "<what you built and how it behaves>"}}

Rules:
- Your first Thought states a short numbered plan for the whole task. Later
  steps follow what the observations show, not the plan.
- One action per response. After it, stop and wait: the system replies with
  "OBSERVATION: <tool result>". Never write an OBSERVATION yourself.
- For a coding task, write the code to a file and run it with exec_python
  before finishing; fix it and run it again if the run fails. Only finish
  once the last run shows the code works.
- If a tool returns an error, fix the cause instead of repeating the same call.
- You have at most {MAX_ITERATIONS} responses for the whole task; finish before you run out.
- If the request needs no code (for example a question), finish directly with
  "main_file": null and the answer in "explanation".
- Paths in FINAL ANSWER use the same form you used with the tools."""

# --- Steps and output models (DEC-060, DEC-065) ------------------------------


class ToolStep(BaseModel):
    """A validated tool call from the LLM (DEC-060).

    Attributes:
        thought: Reasoning before the action.
        action: Name of a known tool.
        action_input: Tool arguments; validated again by the tool wrappers
            (DEC-042).
    """
    model_config = ConfigDict(strict=True)

    thought: str = Field(min_length=1)
    action: Literal[TOOL_NAMES]  # type: ignore[valid-type]
    action_input: dict


class FinalStep(BaseModel):
    """A validated final answer from the LLM (DEC-052, DEC-056, DEC-060).

    Attributes:
        thought: Reasoning before finishing.
        main_file: Main file of the deliverable, or None when no code was
            needed (DEC-056).
        explanation: What was built or the answer itself; never empty.
    """
    model_config = ConfigDict(strict=True)

    thought: str = Field(min_length=1)
    main_file: str | None
    explanation: str = Field(min_length=1)

    @field_validator("main_file")
    @classmethod
    def _blank_is_none(cls, main_file: str | None) -> str | None:
        """Returns None for a blank main file, so "" means no code.

        Args:
            main_file: Main file sent by the LLM.

        Returns:
            The stripped path, or None if it is empty.
        """
        if main_file is None or not main_file.strip():
            return None
        return main_file.strip()


class ParseFailure(BaseModel):
    """An LLM response that could not be turned into a step (DEC-060).

    Attributes:
        error: Explanation for the LLM, sent back as the observation.
        thought: The Thought, when one could be read, for the step record.
    """
    error: str
    thought: str | None = None


Step = ToolStep | FinalStep


class StepRecord(BaseModel):
    """Record of one loop iteration (C1.4, DEC-065).

    Attributes:
        iteration: Iteration number, starting at 1.
        thought: The LLM's Thought, if any could be read.
        action: Tool called, or None for a final answer or a parse error.
        action_input: Arguments of the tool call, if any.
        observation: Text sent back to the LLM; None for the final answer.
    """
    iteration: int
    thought: str | None = None
    action: str | None = None
    action_input: dict | None = None
    observation: str | None = None


class CoderResult(BaseModel):
    """Output of one whole task (C1.5, DEC-065).

    Attributes:
        status: How the task ended (DEC-055, DEC-056).
        plan: The first Thought (DEC-053); empty if none was read.
        code: Content of main_file read from disk (DEC-052); empty without one.
        explanation: Explanation from the final answer; empty without one.
        result: Output of the last valid execution (DEC-055, DEC-063);
            empty without one.
        main_file: Main file declared in the final answer, if any.
        iterations: LLM calls made.
        steps: Record of every iteration.
    """
    status: Literal["success", "failed_execution", "unverified", "max_iterations", "answered"]
    plan: str = ""
    code: str = ""
    explanation: str = ""
    result: str = ""
    main_file: str | None = None
    iterations: int = 0
    steps: list[StepRecord] = Field(default_factory=list)


# --- Parsing (DEC-060) -------------------------------------------------------

_MARKER_FLAGS = re.IGNORECASE | re.MULTILINE
_OBSERVATION_RE = re.compile(r"^\s*OBSERVATION:", _MARKER_FLAGS)
_THOUGHT_RE = re.compile(r"^\s*Thought:", _MARKER_FLAGS)
_ACTION_RE = re.compile(r"^\s*Action:[ \t]*(.*)$", _MARKER_FLAGS)
_ACTION_INPUT_RE = re.compile(r"^\s*Action Input:", _MARKER_FLAGS)
_FINAL_RE = re.compile(r"^\s*FINAL ANSWER:", _MARKER_FLAGS)
_NEXT_FIELD_RE = re.compile(r"^\s*(?:Action|Action Input|FINAL ANSWER):", _MARKER_FLAGS)


def _cut_self_observation(text: str) -> str:
    """Returns text up to any OBSERVATION the LLM wrote itself (DEC-060).

    Args:
        text: Raw LLM response.

    Returns:
        The text before the first line starting with "OBSERVATION:", or the
        whole text if there is none.
    """
    cut = _OBSERVATION_RE.search(text)
    return text[:cut.start()] if cut else text


def _read_thought(text: str) -> str | None:
    """Returns the Thought of a response, or None if it has none.

    Args:
        text: LLM response, already cut at any self-written OBSERVATION.

    Returns:
        The stripped text between "Thought:" and the next field, or None if
        there is no Thought or it is empty.
    """
    match = _THOUGHT_RE.search(text)
    if not match:
        return None
    rest = text[match.end():]
    end = _NEXT_FIELD_RE.search(rest)
    thought = (rest[:end.start()] if end else rest).strip()
    return thought or None


def _read_json_object(text: str) -> dict:
    """Decodes the JSON object at the start of text.

    Code fences around the object and any text after it are ignored.

    Args:
        text: Text that starts with a JSON object, possibly inside ``` fences.

    Returns:
        The decoded object.

    Raises:
        ValueError: If text does not start with a valid JSON object.
    """
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].lstrip() if "\n" in text else ""
    if not text.startswith("{"):
        raise ValueError("expected a JSON object starting with '{'")
    value, _ = json.JSONDecoder().raw_decode(text)
    return value


def _describe_validation(error: ValidationError) -> str:
    """Formats a step validation error for the LLM.

    Args:
        error: The Pydantic validation error.

    Returns:
        One "field: message" item per problem, separated by "; ".
    """
    return "; ".join(
        f"{'.'.join(str(part) for part in err['loc']) or 'response'}: {err['msg']}"
        for err in error.errors()
    )


def parse_llm_response(text: str | None) -> Step | ParseFailure:
    """Parses one LLM response of the ReACT loop into a validated step (DEC-060).

    Rules, in order:
      1. Any text from a self-written "OBSERVATION:" line onwards is cut off.
      2. An empty response is an error.
      3. A missing or empty Thought is an error (C1.4 evidence).
      4. A response with both Action and FINAL ANSWER is an error.
      5. FINAL ANSWER must be a JSON object {"main_file", "explanation"}.
      6. Action must name one known tool, appear once, and be followed by an
         Action Input that is a JSON object.
      7. A response with neither Action nor FINAL ANSWER is an error.
    Markers are matched at line start, ignoring case.

    Args:
        text: Raw content of the LLM response; None counts as empty.

    Returns:
        A ToolStep or FinalStep, or a ParseFailure whose error tells the LLM
        how to fix its response. Never raises.
    """
    text = _cut_self_observation(text or "")
    if not text.strip():
        return ParseFailure(error="empty response. Answer with Thought and then Action or FINAL ANSWER.")

    thought = _read_thought(text)
    if thought is None:
        return ParseFailure(error="missing 'Thought:'. Start every response with your reasoning.")

    final = _FINAL_RE.search(text)
    actions = list(_ACTION_RE.finditer(text))
    if final and actions:
        return ParseFailure(
            thought=thought,
            error="response has both Action and FINAL ANSWER. Either call one tool "
                  "and wait for its OBSERVATION, or finish.",
        )

    try:
        if final:
            answer = _read_json_object(text[final.end():])
            return FinalStep(
                thought=thought,
                main_file=answer.get("main_file"),
                explanation=answer.get("explanation", ""),
            )
        if not actions:
            return ParseFailure(
                thought=thought,
                error="response has neither Action nor FINAL ANSWER.",
            )
        if len(actions) > 1:
            return ParseFailure(
                thought=thought,
                error="more than one Action. Call one tool per response.",
            )
        action = actions[0]
        action_input = _ACTION_INPUT_RE.search(text, action.end())
        if not action_input:
            return ParseFailure(thought=thought, error="Action without 'Action Input:'.")
        return ToolStep(
            thought=thought,
            action=action.group(1).strip().strip("`"),
            action_input=_read_json_object(text[action_input.end():]),
        )
    except ValidationError as e:
        return ParseFailure(thought=thought, error=f"invalid step: {_describe_validation(e)}")
    except ValueError as e:  # includes json.JSONDecodeError
        return ParseFailure(thought=thought, error=f"invalid JSON: {e}")



# --- ReACT loop (C1.4) --------------------------------------------------------


def _read_main_file(main_file: str) -> str | None:
    """Reads the declared main file from the workspace (DEC-052).

    The path is resolved with the same workspace confinement as the tools
    (DEC-036, DEC-042), and read whole: code must match the file.

    Args:
        main_file: Path declared in the final answer.

    Returns:
        The file content, or None if the path is outside the workspace, does
        not exist or cannot be read.
    """
    try:
        return Path(resolve_in_workspace(main_file)).read_text(encoding="utf-8")
    except (ValueError, OSError):
        return None


def _final_status(main_code: str | None, execution: ExecutionResult | None) -> str:
    """Returns the status of a task that ended with a file declared (DEC-055).

    Args:
        main_code: Content of the main file, or None if it could not be read.
        execution: Last valid execution, or None if there is none.

    Returns:
        "success" if the file exists and the last valid execution ended
        without error, "failed_execution" if that execution failed, and
        "unverified" if the file is missing or there is no valid execution.
    """
    if main_code is None or execution is None:
        return "unverified"
    return "success" if execution.ok else "failed_execution"


def run_agent(task: str, window: SlidingWindowBuffer) -> CoderResult:
    """Runs one task through the ReACT loop and returns its structured output.

    Steps:
      1. Stores the task in long-term memory (DEC-019).
      2. Up to MAX_ITERATIONS times: builds the context with retrieval by the
         task (DEC-050, DEC-058), calls the LLM, parses the response
         (DEC-060) and either runs the tool and sends back its OBSERVATION or
         stops on a final answer. Parse errors go back as observations and
         count as iterations.
      3. Sets the status (DEC-055, DEC-056), reads code from the main file
         (DEC-052) and takes the first Thought as the plan (DEC-053).
      4. Stores the outcome when there is a final answer (DEC-049, DEC-059)
         and adds the whole task to the window as one turn (DEC-057).

    Args:
        task: The user's request.
        window: Short-term window of the session.

    Returns:
        A CoderResult. Reaching the iteration limit or a failed execution
        never raises; they are statuses.

    Raises:
        Exception: API and memory errors propagate (DEC-027); the window is
            then left untouched (DEC-028).
    """
    store_memory(task)  # DEC-019
    turn: list[dict] = []  # messages after the task (DEC-057)
    steps: list[StepRecord] = []
    plan = ""
    final: FinalStep | None = None
    last_execution: ExecutionResult | None = None  # DEC-055, DEC-063

    for iteration in range(1, MAX_ITERATIONS + 1):
        messages = build_context(
            task, window, system_prompt=REACT_SYSTEM_PROMPT, turn_messages=turn
        )
        response = get_client().chat.completions.create(model=MODEL, messages=messages)
        content = response.choices[0].message.content or ""
        step = parse_llm_response(content)

        reply = _cut_self_observation(content).strip()
        if reply:
            turn.append({"role": "assistant", "content": reply})
        if not plan and step.thought:
            plan = step.thought  # DEC-053

        if isinstance(step, FinalStep):
            logger.info("Iteration %d/%d: FINAL ANSWER", iteration, MAX_ITERATIONS)
            steps.append(StepRecord(iteration=iteration, thought=step.thought))
            final = step
            break

        if isinstance(step, ParseFailure):
            observation = f"Error: {step.error}"
            record = StepRecord(iteration=iteration, thought=step.thought, observation=observation)
            logger.info("Iteration %d/%d: parse error: %s", iteration, MAX_ITERATIONS, step.error)
        else:
            outcome = dispatch_tool(step.action, step.action_input)  # DEC-062
            if step.action == "write_file":
                last_execution = None  # DEC-063: any write invalidates the last run
            if outcome.execution is not None:
                last_execution = outcome.execution
            observation = outcome.observation
            record = StepRecord(
                iteration=iteration,
                thought=step.thought,
                action=step.action,
                action_input=step.action_input,
                observation=observation,
            )
            logger.info("Iteration %d/%d: %s", iteration, MAX_ITERATIONS, step.action)
        steps.append(record)
        # DEC-057: observations are "user" messages, read as external.
        turn.append({"role": "user", "content": f"OBSERVATION: {observation}"})

    if final is None:
        result = CoderResult(
            status="max_iterations", plan=plan, iterations=len(steps), steps=steps
        )
    elif final.main_file is None:
        # DEC-056: text answer; code and result stay empty.
        result = CoderResult(
            status="answered",
            plan=plan,
            explanation=final.explanation,
            iterations=len(steps),
            steps=steps,
        )
    else:
        main_code = _read_main_file(final.main_file)
        result = CoderResult(
            status=_final_status(main_code, last_execution),
            plan=plan,
            code=main_code or "",
            explanation=final.explanation,
            result=last_execution.output if last_execution else "",
            main_file=final.main_file,
            iterations=len(steps),
            steps=steps,
        )

    if final is not None:
        store_outcome(task, result.status, result.main_file, result.explanation)  # DEC-049
    window.add_turn([{"role": "user", "content": task}, *turn])  # DEC-057
    logger.info("Task finished: %s after %d iterations", result.status, result.iterations)
    return result


MAX_ITERATIONS_MESSAGE = (
    f"I stopped after {MAX_ITERATIONS} iterations without finishing the task."
)


def chat(user_input: str, window: SlidingWindowBuffer) -> str:
    """Runs one session message through the ReACT loop and returns the reply.

    Entry point of one message of the session (DEC-051, DEC-064); the whole
    task with its iterations is one turn of the window (DEC-048, DEC-057).

    Args:
        user_input: The user's message.
        window: Short-term window of the session.

    Returns:
        The explanation of the final answer, or MAX_ITERATIONS_MESSAGE when
        the task hit the iteration limit.

    Raises:
        Exception: API and memory errors propagate (DEC-027); the window is
            then left untouched (DEC-028).
    """
    result = run_agent(user_input, window)
    if result.status == "max_iterations":
        return MAX_ITERATIONS_MESSAGE
    return result.explanation


def _print_result(result: CoderResult) -> None:
    """Prints the parts of a task result shown in the interactive session.

    Args:
        result: Output of run_agent().
    """
    print(f"Agent [{result.status}, {result.iterations} iterations]:")
    print(result.explanation or MAX_ITERATIONS_MESSAGE)
    if result.main_file:
        print(f"Main file: {result.main_file}")
    if result.result:
        print(f"Result of the last run:\n{result.result}")
    print()


def _interactive() -> None:
    """Runs the interactive session until the user types quit or exit.

    A failed task is reported and the session goes on (DEC-030).
    """
    from memory import SLIDING_WINDOW_SIZE
    print("=== Coder Agent ===")
    print(f"Short-term window: {SLIDING_WINDOW_SIZE} tasks | Long-term: Chroma semantic store")
    print(f"ReACT loop: up to {MAX_ITERATIONS} iterations per task. Type 'quit' to exit.\n")

    window = SlidingWindowBuffer()
    while True:
        user_input = input(f"[Task {len(window) + 1}] You: ").strip()
        if user_input.lower() in ("quit", "exit"):
            break
        if not user_input:
            continue
        try:
            result = run_agent(user_input, window)
        except Exception as exc:
            # DEC-030: a failed task is reported and the session goes on.
            logger.error("Task failed: %s: %s", type(exc).__name__, exc)
            logger.debug("Task failure traceback", exc_info=True)
            print("Agent: [error] this task failed, please try again.\n")
            continue
        _print_result(result)


def main(argv: list[str] | None = None) -> int:
    """Runs the Coder from the command line (DEC-064).

    Without arguments it starts the interactive session; with one task it
    runs that task and prints the whole CoderResult as JSON.

    Args:
        argv: Command-line arguments without the program name. Defaults to
            sys.argv[1:].

    Returns:
        The exit code: 0, or 1 if the single task failed with an error.
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m agents.coder_agent", description="Coder Agent (ReACT)."
    )
    parser.add_argument("task", nargs="?", help="run this task once and print the result as JSON")
    args = parser.parse_args(argv)

    # DEC-023: the entry point configures logging; an invalid LOG_LEVEL fails here.
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())

    if args.task is None:
        _interactive()
        return 0
    try:
        result = run_agent(args.task, SlidingWindowBuffer())
    except Exception as exc:
        logger.error("Task failed: %s: %s", type(exc).__name__, exc)
        logger.debug("Task failure traceback", exc_info=True)
        return 1
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

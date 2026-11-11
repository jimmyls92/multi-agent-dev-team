"""Coder Agent with two-tier memory and a ReACT loop (Module 1).

The loop is a LangChain ``create_agent`` graph (LangGraph) with native tool
calling (DEC-068, DEC-069): every tool call carries its Thought (DEC-072),
its arguments are validated before the tool runs (DEC-076), and the task
ends only through the validated ``Finish`` tool (DEC-073). A planning step
runs before the loop (DEC-071). run_agent() runs one task and returns a
CoderResult; chat() wraps it for one session message; main() is the command
line (interactive session or a single task). make_coder_node() wraps it as a
LangGraph node that runs the next pending task of the shared state (Lab 2.2).

Attributes:
    MODEL: OpenRouter model id, from the LLM_MODEL environment variable.
    MAX_ITERATIONS: Model calls allowed in the tool loop per task (C1.4,
        DEC-070); the plan call is not counted.
    RECURSION_LIMIT: LangGraph step limit; a safety net only, well above
        what MAX_ITERATIONS needs (DEC-079).
    CODER_SYSTEM_PROMPT: System prompt of the tool loop.
    PLAN_SYSTEM_PROMPT: System prompt of the planning step.
    NUDGE_MESSAGE: Error sent back when the model answers without a tool.
    MAX_ITERATIONS_MESSAGE: Reply of chat() when a task hits the limit.
"""

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    after_model,
    wrap_model_call,
    wrap_tool_call,
)
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    convert_to_messages,
    convert_to_openai_messages,
)
from langgraph.runtime import Runtime
from pydantic import BaseModel, ConfigDict, Field, field_validator

import tools.handlers
from llm_client import get_chat_model
from memory import SlidingWindowBuffer, build_context, store_memory, store_outcome
from orchestration.state import CoderResult, ProjectSpec, ProjectState, StepRecord, TaskState
from tools import ExecutionResult
from tools.agent_tools import AGENT_TOOLS, check_tool_call
from tools.handlers import resolve_in_workspace

MODEL = os.getenv("LLM_MODEL", "openai/gpt-4.1-mini")
MAX_ITERATIONS = 10  # C1.4, DEC-070
RECURSION_LIMIT = 10 * MAX_ITERATIONS  # DEC-079: safety net only

logger = logging.getLogger(__name__)

# --- Prompts, plan and finish (DEC-069..DEC-074) -----------------------------

# DEC-112: the Coder's prompts, not the PM's, keep it from running servers.
CODER_SYSTEM_PROMPT = f"""You are an expert Python developer working as an autonomous coding agent.
You solve the user's task step by step with your tools.

How you work:
- Every response calls exactly one tool. Its "thought" argument says why you
  take this action, given the last observation.
- File paths are relative to your workspace directory; scripts run with their
  own directory as the working directory.
- For a coding task, write the code to a file and run it with exec_python
  before finishing; fix it and run it again if the run fails. Only finish
  once the last run shows the code works.
- Web servers and APIs are the exception: never run their file, because a
  server never ends (exec_python refuses such a file). The API file must end
  with an `if __name__ == "__main__":` block that starts the server (for
  Flask, `app.run()`), so that running it serves the API; keep that block
  when you edit the file and never remove it to make the file runnable.
  To verify the API, write a separate check script that imports it and
  calls it in-process (for Flask, `app.test_client()`), and run the check
  script. "main_file" is still the API file, not the check script.
- If a tool returns an error, fix the cause instead of repeating the same call.
- You end the task only by calling the Finish tool: "main_file" is the main
  file you wrote in this task (the same path form you used with the tools),
  or null when you wrote no code in this task, for example to answer a
  question, even one about files from earlier tasks; the answer then goes in
  "explanation".
- You have at most {MAX_ITERATIONS} responses for the whole task; finish before you run out.
- Follow your plan below, but let the observations decide each next step."""

PLAN_SYSTEM_PROMPT = """You are an expert Python developer about to work on the user's task as an
autonomous coding agent. Later you will be able to write files, run Python
scripts and read files; now you only plan.

Write a short, concrete plan for the task: a few steps, each one sentence.
- For a coding task, include writing the code, running it and checking the
  output.
- For a web server or API, never plan to run its file: a server never ends
  and the run tool refuses it. Keep its `if __name__ == "__main__":` block
  that starts the server, and plan a separate check script that imports it
  and calls it in-process (for Flask, `app.test_client()`); run that script.
- For a question that needs no code, one step is enough."""

PLAN_HEADING = "Your plan for this task:"


class Plan(BaseModel):
    """Plan for the task, made before the tool loop (DEC-071).

    Attributes:
        steps: Ordered steps, each one short sentence.
    """
    steps: list[Annotated[str, Field(min_length=1)]] = Field(
        min_length=1, description="Ordered steps of the plan, each one short sentence."
    )

    def render(self) -> str:
        """Returns the plan as a numbered list, one step per line."""
        return "\n".join(f"{n}. {step}" for n, step in enumerate(self.steps, start=1))


class Finish(BaseModel):
    """Ends the task. Call it only when the task is done, or to answer a question.

    Attributes:
        thought: Why the task is finished, given the last observation.
        main_file: Main file you wrote in this task, or null when you wrote
            no code in this task.
        explanation: What you built and how it behaves, or the answer itself.
    """
    model_config = ConfigDict(extra="forbid")

    thought: str = Field(
        min_length=1, description="Why the task is finished, given the last observation."
    )
    main_file: str | None = Field(
        description=(
            "Path of the main file you wrote in this task, or null when you "
            "wrote no code in this task (for example to answer a question)."
        )
    )
    explanation: str = Field(
        min_length=1,
        description="What you built and how it behaves, or the answer to the question.",
    )

    @field_validator("main_file")
    @classmethod
    def _blank_is_none(cls, main_file: str | None) -> str | None:
        """Returns None for a blank main file, so "" means no code.

        Args:
            main_file: Main file sent by the model.

        Returns:
            The stripped path, or None if it is empty.
        """
        if main_file is None or not main_file.strip():
            return None
        return main_file.strip()


# DEC-073: sent back when the model answers with text and no tool call.
NUDGE_MESSAGE = (
    "Error: you answered with text and no tool call. Every response must call "
    "exactly one tool; call Finish to end the task."
)


@dataclass(frozen=True)
class CoderContext:
    """Per-task data the middleware reads at run time (DEC-077).

    Passed as ``context=`` when the agent is invoked; the agent's own state
    only holds the task message and the messages of the turn.

    Attributes:
        task: The user's request, also the memory query.
        window: Short-term window of the session.
        plan: The rendered plan of the task (DEC-071).
    """
    task: str
    window: SlidingWindowBuffer
    plan: str


# --- Middleware (DEC-073, DEC-074, DEC-076, DEC-077) -------------------------


@wrap_model_call
def inject_context(request, handler):
    """Builds the whole model input from memory before every model call (DEC-077).

    The agent is invoked with the task as its only input message, so the
    request's messages are the task followed by the turn so far. They are
    rebuilt with ``build_context()``: system message (Coder prompt, plan and
    retrieved memories), window, task, turn. Parallel tool calls are turned
    off (DEC-074).

    Args:
        request: The model request built by the agent.
        handler: Calls the model with a request.

    Returns:
        The model response for the rebuilt request.
    """
    context: CoderContext = request.runtime.context
    system_prompt = f"{CODER_SYSTEM_PROMPT}\n\n{PLAN_HEADING}\n{context.plan}"
    turn = convert_to_openai_messages(request.messages[1:])
    system, *messages = build_context(
        context.task, context.window, system_prompt=system_prompt, turn_messages=turn
    )
    return handler(request.override(
        system_message=SystemMessage(system["content"]),
        messages=convert_to_messages(messages),
        model_settings={**(request.model_settings or {}), "parallel_tool_calls": False},
    ))


@wrap_tool_call
def validate_tool_call(request, handler):
    """Rejects invalid tool calls before LangChain runs the tool (DEC-076).

    Args:
        request: The tool call request; ``request.tool_call`` has the name,
            arguments and id sent by the model.
        handler: Runs the tool.

    Returns:
        The tool's message, or an error ToolMessage with a short
        "Error: ..." content when the call is invalid; the tool then never
        runs (C4.6).
    """
    call = request.tool_call
    error = check_tool_call(call["name"], call["args"])
    if error is not None:
        logger.info("Rejected tool call: %s", error)
        return ToolMessage(
            content=error, tool_call_id=call["id"], name=call["name"], status="error"
        )
    return handler(request)


@after_model(can_jump_to=["model"])
def require_tool_call(state, runtime) -> dict[str, Any] | None:
    """Logs each iteration and sends text-only answers back as errors (DEC-073).

    Runs after every model call that is under the limit (DEC-079), so it
    also logs one line per iteration.

    Args:
        state: Agent state. Its last AI message is the model's response;
            after a valid Finish, ToolStrategy has already added a
            ToolMessage after it.
        runtime: LangGraph runtime (unused).

    Returns:
        None when the response called a tool or this was the last
        iteration; otherwise the nudge message and a jump back to the model,
        which counts as an iteration.
    """
    messages = state["messages"]
    iteration = sum(isinstance(message, AIMessage) for message in messages)
    last = next(m for m in reversed(messages) if isinstance(m, AIMessage))
    if last.tool_calls:
        actions = ", ".join(call["name"] for call in last.tool_calls)
        logger.info("Iteration %d/%d: %s", iteration, MAX_ITERATIONS, actions)
        return None
    if iteration >= MAX_ITERATIONS:
        # No nudge the model would never read: the limit ends the run here.
        logger.info("Iteration %d/%d: no tool call", iteration, MAX_ITERATIONS)
        return None
    logger.info("Iteration %d/%d: no tool call, sent back", iteration, MAX_ITERATIONS)
    return {"messages": [HumanMessage(NUDGE_MESSAGE)], "jump_to": "model"}


def build_agent(model: BaseChatModel | None = None):
    """Builds the Coder's tool loop with ``create_agent`` (DEC-069).

    Args:
        model: Chat model to use. Defaults to ``get_chat_model(MODEL)``;
            tests pass a fake model.

    Returns:
        The compiled LangGraph agent. Invoke it with the task as the only
        message and a CoderContext as ``context``; it ends with a
        ``structured_response`` (a Finish) or, at the limit, without one.
    """
    return create_agent(
        model or get_chat_model(MODEL),
        AGENT_TOOLS,
        # DEC-079: after_model hooks run in reverse order, so the call limit
        # goes last: it counts every model call, nudges included, before
        # require_tool_call can jump back to the model.
        middleware=[
            inject_context,
            validate_tool_call,
            require_tool_call,
            ModelCallLimitMiddleware(run_limit=MAX_ITERATIONS, exit_behavior="end"),
        ],
        response_format=ToolStrategy(Finish),
        context_schema=CoderContext,
    )


@lru_cache(maxsize=1)  # the graph is compiled once per process
def _default_agent():
    """Returns the Coder agent built with the default model."""
    return build_agent()


# --- Result from the final messages (DEC-078) --------------------------------


def _read_main_file(main_file: str) -> str | None:
    """Reads the declared main file from the workspace (DEC-052).

    The path is resolved with the same workspace confinement as the tools
    (DEC-036, DEC-042), and read whole: code must match the file.

    Args:
        main_file: Path declared in Finish.

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


def _drop_limit_message(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Returns the messages without the one LangChain adds at the call limit.

    ``ModelCallLimitMiddleware`` ends the run by adding an AIMessage the
    model never wrote ("Model call limits exceeded ..."); it is the AI
    message after the last allowed model call (DEC-077).

    Args:
        messages: Final messages of the agent run.

    Returns:
        The same messages, without that last AI message if present.
    """
    model_calls = sum(isinstance(message, AIMessage) for message in messages)
    if model_calls > MAX_ITERATIONS and isinstance(messages[-1], AIMessage):
        return messages[:-1]
    return messages


def _last_ai(messages: list[BaseMessage]) -> AIMessage | None:
    """Returns the last AIMessage of a message list, or None if there is none.

    Args:
        messages: Messages of the run.

    Returns:
        The last AIMessage, or None.
    """
    return next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)


def _resolved(path: object) -> str | None:
    """Returns a path resolved in the workspace, or None if it is invalid.

    Args:
        path: Path sent by the model.

    Returns:
        The absolute path inside the workspace, or None if path is not a
        string or ends up outside the workspace.
    """
    if not isinstance(path, str):
        return None
    try:
        return resolve_in_workspace(path)
    except ValueError:
        return None


def _touched_paths(messages: list[BaseMessage]) -> set[str]:
    """Returns the files this task wrote or ran (DEC-080).

    Args:
        messages: Messages of the run.

    Returns:
        The resolved paths of every write_file and exec_python call that
        was not rejected by validation.
    """
    rejected = {
        m.tool_call_id for m in messages
        if isinstance(m, ToolMessage) and m.status == "error"
    }
    return {
        path
        for m in messages if isinstance(m, AIMessage)
        for call in m.tool_calls
        if call["name"] in ("write_file", "exec_python") and call["id"] not in rejected
        if (path := _resolved(call["args"].get("path"))) is not None
    }


def result_from_messages(
    messages: list[BaseMessage], finish: Finish | None, plan: str
) -> CoderResult:
    """Computes the CoderResult of a task from the agent's messages (DEC-078).

    Args:
        messages: Messages of the run: the task first, then the turn,
            without the limit message.
        finish: The validated Finish (``structured_response``), or None when
            the run hit the limit.
        plan: The rendered plan of the task (DEC-071).

    Returns:
        The task's CoderResult: one StepRecord per tool call, or per text
        answer; the last valid execution is the artifact of the last
        exec_python with no write_file call after it (DEC-055, DEC-063); a
        declared main file that exists but that this task neither wrote nor
        ran counts as none (DEC-080); the status follows DEC-055/DEC-056, or
        ``max_iterations`` without Finish.
    """
    tool_results = {m.tool_call_id: m for m in messages if isinstance(m, ToolMessage)}
    accepted_finish = _last_ai(messages) if finish is not None else None
    steps: list[StepRecord] = []
    last_execution: ExecutionResult | None = None
    iteration = 0

    for index, message in enumerate(messages):
        if not isinstance(message, AIMessage):
            continue
        iteration += 1
        if not message.tool_calls:
            following = messages[index + 1] if index + 1 < len(messages) else None
            nudged = isinstance(following, HumanMessage) and following.content == NUDGE_MESSAGE
            steps.append(StepRecord(
                iteration=iteration, observation=NUDGE_MESSAGE if nudged else None
            ))
            continue
        for call in message.tool_calls:
            args = dict(call["args"])
            thought = args.pop("thought", None)
            reply = tool_results.get(call["id"])
            observation = str(reply.text) if reply is not None else None
            if call["name"] == "write_file":
                last_execution = None  # DEC-063: any write invalidates the last run
            elif call["name"] == "exec_python" and isinstance(
                getattr(reply, "artifact", None), ExecutionResult
            ):
                last_execution = reply.artifact
            elif message is accepted_finish:
                observation = None  # the accepted Finish ends the loop
            steps.append(StepRecord(
                iteration=iteration,
                thought=thought if isinstance(thought, str) else None,
                action=call["name"],
                action_input=args,
                observation=observation,
                rejected=getattr(reply, "status", None) == "error",
            ))

    if finish is None:
        return CoderResult(status="max_iterations", plan=plan, iterations=iteration, steps=steps)
    main_file = finish.main_file
    main_code = _read_main_file(main_file) if main_file is not None else None
    if main_code is not None and _resolved(main_file) not in _touched_paths(messages):
        # DEC-080: an existing file this task neither wrote nor ran is not its
        # deliverable. A missing file stays declared and ends as unverified.
        logger.info("Declared main file %r was not written or run in this task; "
                    "treated as an answer", main_file)
        main_file = None
    if main_file is None:
        # DEC-056: text answer; code and result stay empty.
        return CoderResult(
            status="answered",
            plan=plan,
            explanation=finish.explanation,
            iterations=iteration,
            steps=steps,
        )
    return CoderResult(
        status=_final_status(main_code, last_execution),
        plan=plan,
        code=main_code or "",
        explanation=finish.explanation,
        result=last_execution.output if last_execution else "",
        main_file=main_file,
        iterations=iteration,
        steps=steps,
    )


# --- Task entry points --------------------------------------------------------


def make_plan(task: str, window: SlidingWindowBuffer, model: BaseChatModel | None = None) -> Plan:
    """Makes the validated plan of a task with one LLM call (DEC-071).

    The call gets the same memory context as the loop (C1.2, DEC-077) and
    is not counted as an iteration (DEC-070).

    Args:
        task: The user's request.
        window: Short-term window of the session.
        model: Chat model to use. Defaults to ``get_chat_model(MODEL)``.

    Returns:
        The plan, validated with Pydantic (C4.6).

    Raises:
        Exception: API errors and an invalid plan propagate (DEC-027).
    """
    messages = build_context(task, window, system_prompt=PLAN_SYSTEM_PROMPT)
    planner = (model or get_chat_model(MODEL)).with_structured_output(
        Plan, method="function_calling"
    )
    plan = planner.invoke(convert_to_messages(messages))
    logger.info("Plan:\n%s", plan.render())
    return plan


def run_agent(
    task: str, window: SlidingWindowBuffer, model: BaseChatModel | None = None
) -> CoderResult:
    """Runs one task through the planning step and the tool loop.

    Steps:
      1. Stores the task in long-term memory (DEC-019).
      2. Makes the plan (DEC-071).
      3. Runs the agent: at most MAX_ITERATIONS model calls, each with the
         memory context rebuilt (DEC-077); it ends with Finish or at the
         limit (DEC-073, DEC-079).
      4. Computes the CoderResult from the messages (DEC-078), stores the
         outcome when the task ended with Finish (DEC-049, DEC-059) and adds
         the whole task to the window as one turn (DEC-057, DEC-077).

    Args:
        task: The user's request.
        window: Short-term window of the session.
        model: Chat model for the plan and the loop. Defaults to the
            configured one (``get_chat_model(MODEL)``); tests pass a fake
            model (DEC-105).

    Returns:
        A CoderResult. Reaching the iteration limit or a failed execution
        never raises; they are statuses.

    Raises:
        Exception: API and memory errors propagate (DEC-027); the window is
            then left untouched (DEC-028).
    """
    store_memory(task)  # DEC-019
    plan = make_plan(task, window, model).render()
    agent = _default_agent() if model is None else build_agent(model)
    output = agent.invoke(
        {"messages": [HumanMessage(task)]},
        {"recursion_limit": RECURSION_LIMIT},
        context=CoderContext(task=task, window=window, plan=plan),
    )
    messages = _drop_limit_message(output["messages"])
    finish: Finish | None = output.get("structured_response")
    result = result_from_messages(messages, finish, plan)

    if finish is not None:
        store_outcome(task, result.status, result.main_file, result.explanation)  # DEC-049
    window.add_turn(convert_to_openai_messages(messages))  # DEC-057, DEC-077
    logger.info("Task finished: %s after %d iterations", result.status, result.iterations)
    return result


# --- Graph node (Lab 2.2, DEC-097..DEC-107) ----------------------------------


@dataclass
class CoderRunContext:
    """Data that lives for one graph run, passed as ``context=`` (DEC-104).

    Attributes:
        window: Short-term window shared by every task of the run, one turn
            per task (DEC-099).
    """
    window: SlidingWindowBuffer = field(default_factory=SlidingWindowBuffer)


def _next_pending(tasks: list[TaskState]) -> TaskState | None:
    """Returns the first pending task, or None when none is left.

    The PM lists tasks in priority order (DEC-085), so the first pending one
    is the next to run (DEC-103).

    Args:
        tasks: The state's task list.

    Returns:
        The task to run next, or None.
    """
    return next((task for task in tasks if task.status == "pending"), None)


def _task_prompt(task: TaskState, spec: ProjectSpec | None, existing_files: list[str]) -> str:
    """Returns the task text the Coder receives for one task (DEC-098, DEC-105).

    Args:
        task: The task to run.
        spec: The PM's spec; its name and description give the project
            context. None leaves the context out.
        existing_files: Files already written in this run (keys of
            ``state.code``).

    Returns:
        The task, its Given/When/Then criteria, its planned files and the
        files that already exist, as plain text.
    """
    lines = []
    if spec is not None:
        lines += [f"Project: {spec.name} — {spec.description}", ""]
    lines += [f"Task {task.task_id}: {task.title}", task.description, "", "Acceptance criteria:"]
    lines += [f"- Given {c.given}, when {c.when}, then {c.then}" for c in task.acceptance_criteria]
    lines += [
        "",
        f"Planned files: {', '.join(task.files)}",
        f"Files already written in this run: {', '.join(existing_files) or 'none'}",
    ]
    return "\n".join(lines)


def _written_files(result: CoderResult) -> dict[str, str]:
    """Returns the files the task wrote, read from disk (DEC-106).

    Only ``write_file`` steps not rejected by validation, whose path
    resolves inside the workspace and exists on disk, count. A file that
    cannot be read as text is skipped with a warning, so the node never
    raises here (DEC-102).

    Args:
        result: The task's result; its steps hold the tool calls.

    Returns:
        File path relative to the workspace mapped to its content on disk.
    """
    files = {}
    for step in result.steps:
        if step.action != "write_file" or step.rejected or not step.action_input:
            continue
        path = _resolved(step.action_input.get("path"))
        if path is None or not Path(path).is_file():
            continue
        relative = Path(path).relative_to(tools.handlers.WORKSPACE_DIR).as_posix()
        try:
            files[relative] = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("Skipping %s in the accumulated code: %s", relative, exc)
    return files


def _with_task(tasks: list[TaskState], task_id: str, **update: Any) -> list[TaskState]:
    """Returns the task list with one task's fields replaced.

    Args:
        tasks: The state's task list.
        task_id: ID of the task to update.
        **update: Fields of ``TaskState`` to replace.

    Returns:
        A new list; the other tasks are the same objects.
    """
    return [t.model_copy(update=update) if t.task_id == task_id else t for t in tasks]


def make_coder_node(
    model: BaseChatModel | None = None,
) -> Callable[[ProjectState, Runtime[CoderRunContext]], dict]:
    """Returns the Coder node function for the graph.

    Args:
        model: Chat model for the Coder. None uses the configured one.

    Returns:
        The node: it takes the state and the run's runtime and returns a
        partial update.
    """

    def coder_node(state: ProjectState, runtime: Runtime[CoderRunContext]) -> dict:
        """Runs the next pending task and records its status, result and code.

        Args:
            state: Current state; reads ``tasks``, ``spec`` and ``code``.
            runtime: The run's runtime; its context holds the window.

        Never raises: a fatal error marks the task failed and is returned in
        ``error``, which ends the run (DEC-102).

        Returns:
            Update with ``tasks``, ``code``, ``progress`` and ``error``;
            ``code`` is left out after a fatal error, and only ``progress``
            and ``error`` are returned when no task is pending or the run
            has no context.
        """
        task = _next_pending(state.tasks)
        if task is None:
            error = "Coder Agent: no pending task to run."
            return {"progress": [error], "error": error}
        if runtime.context is None:  # DEC-109: configuration error, the task never ran
            error = "Coder Agent: no run context; invoke the graph with context=CoderRunContext()."
            logger.error(error)
            return {"progress": [error], "error": error}

        started = f"Coder Agent: starting {task.task_id} — {task.title}."
        try:
            prompt = _task_prompt(task, state.spec, list(state.code))
            result = run_agent(prompt, runtime.context.window, model)
        except Exception as exc:  # DEC-102: the node never raises out of the graph
            error = f"{type(exc).__name__}: {exc}"
            logger.error("Coder Agent failed on %s: %s", task.task_id, error)
            return {
                "tasks": _with_task(state.tasks, task.task_id, status="failed", result=None),
                "progress": [started, f"Coder Agent: {task.task_id} failed — {error}"],
                "error": error,
            }
        status = "done" if result.status == "success" else "failed"  # DEC-101
        finished = f"Coder Agent: {task.task_id} {status}. File: {result.main_file or 'none'}."
        return {
            "tasks": _with_task(state.tasks, task.task_id, status=status, result=result),
            "code": {**state.code, **_written_files(result)},
            "progress": [started, finished],
            "error": "",
        }

    return coder_node


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
        The explanation from Finish, or MAX_ITERATIONS_MESSAGE when the task
        hit the iteration limit.

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

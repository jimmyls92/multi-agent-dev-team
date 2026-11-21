"""LangGraph graph of the agent team (C2.3, DEC-094, DEC-197).

The team graph runs the PM and then the Coder-QA loop over the PM's tasks::

    START → pm →(route_after_pm)→ coder → reflect → qa →(route_after_qa)→ coder | END

The PM never raises; on failure, or without tasks, the run ends without
calling the Coder (DEC-087, DEC-110). The Coder runs one pass of the
current task, ``reflect`` evaluates it and sends the best version to the
QA in a ``review_request``, and the QA answers by A2A; its verdict closes
the task or sends it back to the Coder, until the review limit
(DEC-163, DEC-177, DEC-178). Each run gets its own memory window and
settings through the run context (DEC-104, DEC-197), starts with an empty
workspace (DEC-114) and has a step limit that ends a runaway loop with the
state kept (DEC-115, DEC-180).

The Coder also has its own graph, ``START → coder ⟲ → END``, run from a
state that already has tasks; there the Coder closes each task itself
(Lab 2.2, DEC-100, DEC-101).

Typical usage example:

    state = run("Build a REST API with GET /health")
    print(state.outcome, state.tasks)
    final = build_coder_graph().invoke(state, context=CoderRunContext())

Attributes:
    PM_NODE: Name of the PM node in the graph.
    CODER_NODE: Name of the Coder node in the graph.
    REFLECT_NODE: Name of the self-reflection node.
    QA_NODE: Name of the QA node.
"""

import logging
import os

from langchain_core.language_models import BaseChatModel
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

import orchestration.workspace as workspace
import tools.handlers
from agents.coder_agent import CoderRunContext, make_coder_node
from agents.coder_reflection import make_reflect_node
from agents.pm_agent import MAX_TASKS, make_pm_node
from agents.qa_agent import Review, make_qa_node
from orchestration.settings import LoopSettings, load_loop_settings
from orchestration.state import ProjectState

PM_NODE = "pm"
CODER_NODE = "coder"
REFLECT_NODE = "reflect"
QA_NODE = "qa"

logger = logging.getLogger(__name__)


def route_after_pm(state: ProjectState) -> str:
    """Returns the node that follows the PM: the Coder, or END (DEC-110).

    Args:
        state: State after the PM's step.

    Returns:
        ``CODER_NODE`` when ``error`` is empty and there is at least one
        task; ``END`` otherwise.
    """
    if not state.error and state.tasks:
        return CODER_NODE
    return END


def route_after_coder(state: ProjectState) -> str:
    """Returns the node that follows the Coder: itself again, or END (DEC-103).

    Args:
        state: State after the Coder's step.

    Returns:
        ``CODER_NODE`` while a task is pending and ``error`` is empty;
        ``END`` otherwise.
    """
    if not state.error and any(task.status == "pending" for task in state.tasks):
        return CODER_NODE
    return END


def route_after_pass(state: ProjectState) -> str:
    """Returns the node after a Coder pass in the team graph: reflect, or END on error.

    Args:
        state: State after the Coder's step.

    Returns:
        ``REFLECT_NODE`` when ``error`` is empty; ``END`` otherwise.
    """
    return END if state.error else REFLECT_NODE


def route_after_reflect(state: ProjectState) -> str:
    """Returns the node after reflect: the QA, or END on error.

    Args:
        state: State after the reflect step.

    Returns:
        ``QA_NODE`` when ``error`` is empty; ``END`` otherwise.
    """
    return END if state.error else QA_NODE


def route_after_qa(state: ProjectState) -> str:
    """Returns the node after the QA's verdict: the Coder again, or END (DEC-163, DEC-178).

    The QA has already set the task's status; this only reads it.

    Args:
        state: State after the QA's step.

    Returns:
        ``CODER_NODE`` while a task is in progress (sent back) or pending
        and ``error`` is empty; ``END`` otherwise.
    """
    open_tasks = any(task.status in ("in_progress", "pending") for task in state.tasks)
    return CODER_NODE if not state.error and open_tasks else END


def step_limit(settings: LoopSettings) -> int:
    """Returns the most graph steps a run may take (DEC-180).

    Args:
        settings: The run's loop settings.

    Returns:
        The PM, then coder, reflect and qa for each review of each task,
        plus a margin.
    """
    return 1 + MAX_TASKS * settings.qa_max_iterations * 3 + 3


def _add_coder(builder: StateGraph, model: BaseChatModel | None) -> None:
    """Adds the Coder node and its self-loop to a graph under construction.

    Args:
        builder: The graph being built; its context schema must be
            ``CoderRunContext``.
        model: Chat model for the Coder; None uses the configured one.
    """
    builder.add_node(CODER_NODE, make_coder_node(model))
    builder.add_conditional_edges(CODER_NODE, route_after_coder, [CODER_NODE, END])


def build_coder_graph(coder_model: BaseChatModel | None = None) -> CompiledStateGraph:
    """Returns the compiled Coder graph, run from a state that has tasks.

    Invoke it with ``context=CoderRunContext()`` so the run has its own
    memory window (DEC-104).

    Args:
        coder_model: Chat model for the Coder; None uses the configured one
            (``LLM_MODEL``).

    Returns:
        The compiled graph ``START → coder ⟲ → END``.
    """
    builder = StateGraph(ProjectState, context_schema=CoderRunContext)
    _add_coder(builder, coder_model)
    builder.add_edge(START, CODER_NODE)
    return builder.compile()


def build_graph(
    pm_model: BaseChatModel | None = None,
    coder_model: BaseChatModel | None = None,
    qa_review: Review | None = None,
) -> CompiledStateGraph:
    """Returns the compiled team graph: the PM, then the Coder-QA loop over its tasks.

    Invoke it with ``context=CoderRunContext()`` so the run has its own
    memory window and settings (DEC-104, DEC-197).

    Args:
        pm_model: Chat model for the PM; None uses the configured one
            (``PM_MODEL``).
        coder_model: Chat model for the Coder and its self-evaluation; None
            uses the configured one (``LLM_MODEL``).
        qa_review: Does the QA's work for one task; None uses ``run_qa``
            (DEC-197).

    Returns:
        The compiled graph ``START → pm → coder → reflect → qa ⟲ → END``.
    """
    builder = StateGraph(ProjectState, context_schema=CoderRunContext)
    builder.add_node(PM_NODE, make_pm_node(pm_model))
    builder.add_node(CODER_NODE, make_coder_node(coder_model, close_tasks=False))
    builder.add_node(REFLECT_NODE, make_reflect_node(coder_model))
    builder.add_node(QA_NODE, make_qa_node(qa_review))
    builder.add_edge(START, PM_NODE)
    builder.add_conditional_edges(PM_NODE, route_after_pm, [CODER_NODE, END])
    builder.add_conditional_edges(CODER_NODE, route_after_pass, [REFLECT_NODE, END])
    builder.add_conditional_edges(REFLECT_NODE, route_after_reflect, [QA_NODE, END])
    builder.add_conditional_edges(QA_NODE, route_after_qa, [CODER_NODE, END])
    return builder.compile()


def _failed(state: ProjectState, error: str) -> ProjectState:
    """Returns the state with an error set and noted in the progress log.

    Args:
        state: The state to end the run with.
        error: The failure message.

    Returns:
        A copy of the state with ``error`` and one more progress note.
    """
    logger.error(error)
    return state.model_copy(update={"error": error, "progress": [*state.progress, error]})


def run(
    requirement: str,
    pm_model: BaseChatModel | None = None,
    coder_model: BaseChatModel | None = None,
    qa_review: Review | None = None,
) -> ProjectState:
    """Returns the final state of one run of the team graph for a requirement.

    Never raises once the requirement is valid: invalid loop settings, a
    workspace that cannot be archived and a run that hits the step limit
    end with ``error`` set. The loop settings are read once, here, for the
    whole run (DEC-180, DEC-197). Each progress note is logged at INFO
    when the step that wrote it ends (DEC-120).

    Args:
        requirement: The user's requirement.
        pm_model: Chat model for the PM; None uses the configured one.
        coder_model: Chat model for the Coder; None uses the configured one.
        qa_review: Does the QA's work for one task; None uses ``run_qa``.

    Returns:
        The final state, validated as ``ProjectState`` (the graph yields
        dicts).

    Raises:
        ValidationError: If the requirement is empty.
    """
    state = ProjectState(requirement=requirement)
    try:
        settings = load_loop_settings(os.environ)
    except ValueError as exc:
        return _failed(state, f"Settings: {exc}")
    try:
        # DEC-114: read at call time, so the configured (or test) folders apply.
        archive = workspace.archive_workspace(tools.handlers.CODER_WORKSPACE_DIR, workspace.REPO_ROOT)
    except (ValueError, OSError) as exc:
        return _failed(state, f"Workspace: cannot archive the previous files — {exc}")
    if archive is not None:
        state = state.model_copy(
            update={"progress": [f"Workspace: previous files moved to {archive}."]}
        )
    for note in state.progress:
        logger.info(note)
    logged = len(state.progress)
    last = state.model_dump()
    limit = step_limit(settings)
    try:
        # DEC-115: stream keeps the last state, which invoke would lose on the limit.
        for last in build_graph(pm_model, coder_model, qa_review).stream(
            state,
            context=CoderRunContext(settings=settings),
            config={"recursion_limit": limit},
            stream_mode="values",
        ):
            # DEC-120: each step's notes are logged as soon as the step ends.
            for note in last["progress"][logged:]:
                logger.info(note)
            logged = len(last["progress"])
    except GraphRecursionError:
        return _failed(ProjectState.model_validate(last), f"Run stopped: step limit of {limit} reached.")
    return ProjectState.model_validate(last)

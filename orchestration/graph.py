"""LangGraph graph of the agent team (C2.3, DEC-094).

The team graph runs the PM and then the Coder over the PM's tasks::

    START → pm →(route_after_pm)→ coder ⟲ (route_after_coder) → END

The PM never raises; on failure, or without tasks, the run ends without
calling the Coder (DEC-087, DEC-110). The Coder runs one pending task per
step and loops back to itself while tasks are pending and there is no
error (DEC-103). Each run gets its own memory window through the run
context (DEC-104), starts with an empty workspace (DEC-114) and has a step
limit that ends a runaway loop with the state kept (DEC-115).

The Coder also has its own graph, ``START → coder ⟲ → END``, run from a
state that already has tasks (Lab 2.2, DEC-100).

Typical usage example:

    state = run("Build a REST API with GET /health")
    print(state.tasks)

    final = build_coder_graph().invoke(state, context=CoderRunContext())

Attributes:
    PM_NODE: Name of the PM node in the graph.
    CODER_NODE: Name of the Coder node in the graph.
    STEP_LIMIT: Most graph steps a run may take: the PM, one per task and a
        margin (DEC-115).
"""

import logging

from langchain_core.language_models import BaseChatModel
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

import orchestration.workspace as workspace
import tools.handlers
from agents.coder_agent import CoderRunContext, make_coder_node
from agents.pm_agent import MAX_TASKS, make_pm_node
from orchestration.state import ProjectState

PM_NODE = "pm"
CODER_NODE = "coder"
STEP_LIMIT = 1 + MAX_TASKS + 2  # DEC-115: PM, one step per task, margin

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
    pm_model: BaseChatModel | None = None, coder_model: BaseChatModel | None = None
) -> CompiledStateGraph:
    """Returns the compiled team graph: the PM, then the Coder over its tasks.

    Invoke it with ``context=CoderRunContext()`` so the run has its own
    memory window (DEC-104).

    Args:
        pm_model: Chat model for the PM; None uses the configured one
            (``PM_MODEL``).
        coder_model: Chat model for the Coder; None uses the configured one
            (``LLM_MODEL``).

    Returns:
        The compiled graph ``START → pm → coder ⟲ → END``.
    """
    builder = StateGraph(ProjectState, context_schema=CoderRunContext)
    builder.add_node(PM_NODE, make_pm_node(pm_model))
    _add_coder(builder, coder_model)
    builder.add_edge(START, PM_NODE)
    builder.add_conditional_edges(PM_NODE, route_after_pm, [CODER_NODE, END])
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
) -> ProjectState:
    """Returns the final state of one run of the team graph for a requirement.

    Never raises once the requirement is valid: a workspace that cannot be
    archived and a run that hits the step limit end with ``error`` set.

    Args:
        requirement: The user's requirement.
        pm_model: Chat model for the PM; None uses the configured one.
        coder_model: Chat model for the Coder; None uses the configured one.

    Returns:
        The final state, validated as ``ProjectState`` (the graph yields
        dicts).

    Raises:
        ValidationError: If the requirement is empty.
    """
    state = ProjectState(requirement=requirement)
    try:
        # DEC-114: read at call time, so the configured (or test) folders apply.
        archive = workspace.archive_workspace(tools.handlers.WORKSPACE_DIR, workspace.REPO_ROOT)
    except (ValueError, OSError) as exc:
        return _failed(state, f"Workspace: cannot archive the previous files — {exc}")
    if archive is not None:
        state = state.model_copy(
            update={"progress": [f"Workspace: previous files moved to {archive}."]}
        )

    last = state.model_dump()
    try:
        # DEC-115: stream keeps the last state, which invoke would lose on the limit.
        for last in build_graph(pm_model, coder_model).stream(
            state,
            context=CoderRunContext(),
            config={"recursion_limit": STEP_LIMIT},
            stream_mode="values",
        ):
            pass
    except GraphRecursionError:
        return _failed(
            ProjectState.model_validate(last), f"Run stopped: step limit of {STEP_LIMIT} reached."
        )
    return ProjectState.model_validate(last)

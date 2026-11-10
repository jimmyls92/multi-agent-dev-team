"""LangGraph graph of the agent team (C2.3, DEC-094).

For now the team graph has only the PM: ``START → pm → END``. The PM never
raises; a failure ends the run with ``error`` set (DEC-087).

The Coder has its own graph, ``START → coder ⟲ → END``, run from a state
that already has tasks (Lab 2.2, DEC-100): the node runs one pending task
per step and loops back to itself while tasks are pending and there is no
error (DEC-103). Each run gets its own memory window through the run
context (DEC-104). Lab 2.3 puts the Coder after the PM.

Typical usage example:

    state = run("Build a REST API with GET /health")
    print(state.tasks)

    final = build_coder_graph().invoke(state, context=CoderRunContext())

Attributes:
    CODER_NODE: Name of the Coder node in the graph.
"""

from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agents.coder_agent import CoderRunContext, make_coder_node
from agents.pm_agent import make_pm_node
from orchestration.state import ProjectState

CODER_NODE = "coder"


def build_graph(pm_model: BaseChatModel | None = None) -> CompiledStateGraph:
    """Returns the compiled graph over the shared project state.

    Args:
        pm_model: Chat model for the PM; None uses the configured one
            (``PM_MODEL``).

    Returns:
        The compiled graph ``START → pm → END``.
    """
    builder = StateGraph(ProjectState)
    builder.add_node("pm", make_pm_node(pm_model))
    builder.add_edge(START, "pm")
    builder.add_edge("pm", END)
    return builder.compile()


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


def run(requirement: str, pm_model: BaseChatModel | None = None) -> ProjectState:
    """Returns the final state of one run of the graph for a requirement.

    Args:
        requirement: The user's requirement.
        pm_model: Chat model for the PM; None uses the configured one.

    Returns:
        The final state, validated as ``ProjectState`` (``invoke`` returns a
        dict).

    Raises:
        ValidationError: If the requirement is empty.
    """
    initial = ProjectState(requirement=requirement)
    final = build_graph(pm_model).invoke(initial)
    return ProjectState.model_validate(final)

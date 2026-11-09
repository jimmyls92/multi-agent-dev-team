"""LangGraph graph of the agent team (C2.3, DEC-094).

For now the graph has only the PM: ``START → pm → END``. The PM never
raises; a failure ends the run with ``error`` set (DEC-087).

Typical usage example:

    state = run("Build a REST API with GET /health")
    print(state.tasks)
"""

from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agents.pm_agent import make_pm_node
from orchestration.state import ProjectState


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

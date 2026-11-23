"""Unit tests of the shared node guard (Lab 3.3, review R2).

Covers spec `lab_3_3_a2a_loop` AC-3.3-44 at the node level (DEC-202): a
node that raises returns an update with ``error`` and its task failed.
"""

import logging

import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from agents.coder_agent import CoderRunContext
from orchestration.node_guard import guard_node
from orchestration.state import ProjectState, TaskState


def _task(task_id: str, status: str) -> TaskState:
    """Returns a minimal task with the given status.

    Args:
        task_id: The task's ID.
        status: The task's status.

    Returns:
        The task.
    """
    return TaskState(task_id=task_id, title=task_id, description="d", priority=1,
                     acceptance_criteria=[{"given": "g", "when": "w", "then": "t"}],
                     covers=["REQ-1"], files=["a.py"], status=status)


def _boom(state: ProjectState, runtime: Runtime) -> dict:
    """Raises, as a node with a bug or a broken dependency would.

    Args:
        state: Current state; unused.
        runtime: The run's runtime; unused.

    Raises:
        OSError: Always.
    """
    raise OSError("disk full")


def test_ac_3_3_44_guard_marks_task_in_progress_failed(caplog):
    state = ProjectState(requirement="r", tasks=[_task("task_1", "done"), _task("task_2", "in_progress"),
                                                 _task("task_3", "pending")])

    with caplog.at_level(logging.ERROR):
        update = guard_node("Reflect", _boom)(state, Runtime(context=CoderRunContext()))

    assert update["error"] == "OSError: disk full"
    assert [t.status for t in update["tasks"]] == ["done", "failed", "pending"]
    assert update["tasks"][1].closed_reason == "Reflect error: OSError: disk full"
    assert update["progress"] == ["Reflect: failed — OSError: disk full"]
    [record] = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert "disk full" in record.getMessage() and record.exc_info is not None


def test_ac_3_3_44_guard_uses_given_task():
    state = ProjectState(requirement="r", tasks=[_task("task_1", "pending"), _task("task_2", "pending")])

    update = guard_node("Coder Agent", _boom, task_of=lambda s: s.tasks[0])(state, Runtime())

    assert [t.status for t in update["tasks"]] == ["failed", "pending"]


def test_ac_3_3_44_guard_without_task():
    update = guard_node("PM Agent", lambda state: 1 / 0)(ProjectState(requirement="r"))

    assert "tasks" not in update
    assert update["error"] == "ZeroDivisionError: division by zero"


def test_ac_3_3_44_guard_passes_result_through():
    def node(state: ProjectState) -> dict:
        """Returns a normal update.

        Args:
            state: Current state; unused.

        Returns:
            One progress note.
        """
        return {"progress": ["ok"]}

    assert guard_node("PM Agent", node)(ProjectState(requirement="r")) == {"progress": ["ok"]}


def test_ac_3_3_44_guard_keeps_runtime_injection():
    seen = []

    def node(state: ProjectState, runtime: Runtime[CoderRunContext]) -> dict:
        """Records the runtime context LangGraph injected.

        Args:
            state: Current state; unused.
            runtime: The run's runtime.

        Returns:
            One progress note.
        """
        seen.append(runtime.context)
        return {"progress": ["ok"]}

    builder = StateGraph(ProjectState, context_schema=CoderRunContext)
    builder.add_node("n", guard_node("Reflect", node))
    builder.add_edge(START, "n")
    builder.add_edge("n", END)
    context = CoderRunContext()

    builder.compile().invoke(ProjectState(requirement="r"), context=context)

    assert seen == [context]

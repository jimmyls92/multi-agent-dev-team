"""Shared guard that keeps every graph node from raising (DEC-202).

A node that raises would stop the LangGraph run with a traceback. Every
node of the team graph (PM, Coder, reflect, QA) is wrapped in
``guard_node``: an exception is logged with its traceback, the task the
node was working on is closed as failed and the error is returned in
``error``, which every router reads to end the run.

Typical usage example:

    def make_qa_node(review=None):
        def qa_node(state, runtime): ...
        return guard_node("QA", qa_node)
"""

import functools
import logging
from collections.abc import Callable

from orchestration.state import ProjectState, TaskState

logger = logging.getLogger(__name__)

TaskOf = Callable[[ProjectState], TaskState | None]


def task_in_progress(state: ProjectState) -> TaskState | None:
    """Returns the first task in progress, or None.

    Args:
        state: Current state.

    Returns:
        The task the Coder-QA loop is working on, if any.
    """
    return next((task for task in state.tasks if task.status == "in_progress"), None)


def guard_node(name: str, node: Callable[..., dict], task_of: TaskOf = task_in_progress) -> Callable[..., dict]:
    """Returns the node wrapped so that any exception becomes a failed task and ``error``.

    The wrapper keeps the node's signature (``functools.wraps``), so
    LangGraph still injects ``runtime`` into nodes that take it.

    Args:
        name: Name shown in the log and the progress note, e.g. ``"QA"``.
        node: The node function; takes the state and, optionally, the
            runtime.
        task_of: Returns the task the node works on in a given state; it
            is marked ``failed`` when the node raises. Defaults to the task
            in progress.

    Returns:
        The guarded node. It returns the node's update unchanged, or, when
        the node raises, an update with ``progress``, ``error`` and, if
        there was a task, ``tasks``.
    """

    @functools.wraps(node)
    def guarded(state: ProjectState, *args, **kwargs) -> dict:
        """Runs the node and turns any exception into an error update.

        Args:
            state: Current state.
            *args: Other positional arguments of the node (the runtime).
            **kwargs: Other keyword arguments of the node (the runtime).

        Returns:
            The node's update, or the error update.
        """
        try:
            return node(state, *args, **kwargs)
        except Exception as exc:  # DEC-202: no node raises out of the graph
            error = f"{type(exc).__name__}: {exc}"
            logger.exception("%s failed: %s", name, error)
            update = {"progress": [f"{name}: failed — {error}"], "error": error}
            task = task_of(state)
            if task is not None:
                update["tasks"] = [
                    t.model_copy(update={"status": "failed", "closed_reason": f"{name} error: {error}"})
                    if t.task_id == task.task_id else t
                    for t in state.tasks
                ]
            return update

    return guarded

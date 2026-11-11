"""Product Manager agent: turns a requirement into a spec and tasks (C2.1).

The PM makes two structured LLM calls, one for the specification and one
for the task list, and writes both into the shared state (DEC-087). Task
IDs, priorities and criterion IDs are assigned by code (DEC-090); task
lists over the limit are consolidated (DEC-082, DEC-092).

Typical usage example:

    pm_node = make_pm_node()
    update = pm_node(ProjectState(requirement="Build a REST API with /health"))
"""

import logging
import os
from collections.abc import Callable

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field, field_validator, model_validator

from agents.llm_helpers import structured_call
from llm_client import get_chat_model
from orchestration.state import (
    NonEmptyStr,
    ProjectSpec,
    ProjectState,
    SpecCriterion,
    TaskCriterion,
    TaskSpec,
    TaskState,
)

logger = logging.getLogger(__name__)

DEFAULT_PM_MODEL = "openai/gpt-4.1"  # DEC-086, DEC-093
MAX_TASKS = 8  # C2.4
MIN_TASKS = 2  # C2.1, DEC-081

SPEC_SYSTEM_PROMPT = """You are a senior technical product manager. Turn the user's software
requirement into a technical specification that a coding agent will implement without
asking questions.

- name: a short project name.
- description: what the project does, in one or two sentences.
- acceptance_criteria: observable behaviours the finished project must show, one per
  sentence. Together they must capture everything the requirement asks for, including
  input validation and error cases when requested. Do not add features nobody asked for.
- details: markdown with exactly these sections: ## Overview, ## Functional Requirements,
  ## Non-Functional Requirements, ## File Structure, ## Constraints & Assumptions.
  Be concrete: no "TBD" and no open questions; decide and state assumptions instead.

The project is written in Python."""

TASKS_SYSTEM_PROMPT = f"""You are a senior technical product manager. Split the
specification you receive into coding tasks for a coding agent.

- Use between {MIN_TASKS} and {MAX_TASKS} tasks, as few as possible: each task should be
  small enough for one short coding session.
- Order tasks by dependency: a task may only rely on files created by earlier tasks.
- Each description must be self-contained: the coding agent sees only its own task.
- acceptance_criteria: concrete checks of the task's code, each as given / when / then.
- covers: the IDs of the specification criteria the task implements. Every criterion ID
  must be covered by at least one task; use only IDs from the specification.
- files: relative paths of the files the task creates or edits. Several tasks may edit
  the same file.
- Every task creates or changes Python code that can be checked by running a script, so
  its files include at least one .py file. Dependency lists, documentation and
  configuration are never tasks of their own: list such files in a coding task's files.

The project is written in Python."""


class SpecDraft(BaseModel):
    """Specification as written by the LLM, before IDs are assigned (DEC-083).

    Attributes:
        name: Short name of the project.
        description: What the project does.
        details: Markdown with the five sections of the spec.
        acceptance_criteria: Criteria of the whole requirement, without IDs.
    """
    name: NonEmptyStr
    description: NonEmptyStr
    details: NonEmptyStr
    acceptance_criteria: list[NonEmptyStr] = Field(min_length=1)


class TaskDraft(BaseModel):
    """One task as written by the LLM, before ID and priority (DEC-090).

    Attributes:
        title: Short imperative title.
        description: Self-contained instructions for the Coder.
        acceptance_criteria: Given/When/Then checks (DEC-095).
        covers: IDs of the spec criteria the task covers.
        files: Files the task creates or edits.
    """
    title: NonEmptyStr
    description: NonEmptyStr
    acceptance_criteria: list[TaskCriterion] = Field(min_length=1)
    covers: list[NonEmptyStr] = Field(min_length=1)
    files: list[NonEmptyStr] = Field(min_length=1)

    @field_validator("files")
    @classmethod
    def _has_python_file(cls, files: list[str]) -> list[str]:
        """Returns the files if at least one is a Python file (DEC-117).

        Args:
            files: The task's files.

        Returns:
            The same files.

        Raises:
            ValueError: If no file ends in ``.py``.
        """
        # DEC-117: only a task with code to run can end done; others fail the demo.
        if not any(f.endswith(".py") for f in files):
            raise ValueError(
                f"files {files} have no .py file: every task must create or change "
                "Python code; put dependency or documentation files in a coding task"
            )
        return files


class TaskListBase(BaseModel):
    """Task list as written by the LLM, without the coverage check.

    There is no upper bound: lists over the limit are consolidated instead
    of retried (DEC-092). ``_task_list_schema`` adds the coverage check of
    each run.

    Attributes:
        tasks: The tasks in execution order.
    """
    tasks: list[TaskDraft] = Field(min_length=MIN_TASKS)


def _task_list_schema(criterion_ids: list[str]) -> type[TaskListBase]:
    """Returns a TaskList schema that checks coverage of this run's criteria.

    A coverage failure is a validation error, so the structured call retries
    it like any other (DEC-083, DEC-091).

    Args:
        criterion_ids: IDs of the spec criteria, e.g. ``["REQ-1", "REQ-2"]``.

    Returns:
        A subclass of ``TaskListBase`` with the coverage check, named
        ``TaskList`` because the class name is the tool name the LLM sees.
    """

    class TaskList(TaskListBase):
        """Task list whose ``covers`` must match the spec criteria exactly."""

        @model_validator(mode="after")
        def _check_coverage(self) -> "TaskList":
            """Returns the list if it covers every criterion and no unknown one.

            Returns:
                This task list.

            Raises:
                ValueError: If a task covers an unknown ID or a criterion is
                    not covered by any task.
            """
            covered = {req for task in self.tasks for req in task.covers}
            unknown = sorted(covered - set(criterion_ids))
            if unknown:
                raise ValueError(
                    f"unknown criterion IDs: {', '.join(unknown)}; "
                    f"use only {', '.join(criterion_ids)}"
                )
            missing = [req for req in criterion_ids if req not in covered]
            if missing:
                raise ValueError(f"{', '.join(missing)} not covered by any task")
            return self

    return TaskList


def _build_spec(requirement: str, model: BaseChatModel) -> ProjectSpec:
    """Returns the specification of a requirement, without tasks yet.

    Args:
        requirement: The user's requirement.
        model: Chat model for the PM.

    Returns:
        The spec with criteria numbered ``REQ-1``, ``REQ-2``... and no tasks.

    Raises:
        StructuredOutputError: If no valid spec comes back after the retry.
        Exception: Errors of the model call propagate.
    """
    draft = structured_call(model, SpecDraft, SPEC_SYSTEM_PROMPT, requirement)
    return ProjectSpec(
        name=draft.name,
        description=draft.description,
        details=draft.details,
        acceptance_criteria=[
            SpecCriterion(id=f"REQ-{k}", text=text)
            for k, text in enumerate(draft.acceptance_criteria, start=1)
        ],
        tasks=[],
    )


def _render_spec(spec: ProjectSpec) -> str:
    """Returns the specification as text for the task-list call.

    Args:
        spec: The specification without tasks.

    Returns:
        Name, description, numbered criteria and details.
    """
    criteria = "\n".join(f"- {c.id}: {c.text}" for c in spec.acceptance_criteria)
    return (
        f"# {spec.name}\n\n{spec.description}\n\n"
        f"## Acceptance criteria\n{criteria}\n\n{spec.details}"
    )


def _build_tasks(spec: ProjectSpec, model: BaseChatModel) -> list[TaskSpec]:
    """Returns the tasks for a specification, with IDs and priorities.

    Args:
        spec: The specification without tasks.
        model: Chat model for the PM.

    Returns:
        The tasks in execution order: ``task_k`` with priority ``k``
        (DEC-085, DEC-090); possibly more than ``MAX_TASKS``.

    Raises:
        StructuredOutputError: If no valid task list comes back after the
            retry.
        Exception: Errors of the model call propagate.
    """
    schema = _task_list_schema([c.id for c in spec.acceptance_criteria])
    task_list = structured_call(model, schema, TASKS_SYSTEM_PROMPT, _render_spec(spec))
    return [
        TaskSpec(task_id=f"task_{k}", priority=k, **draft.model_dump())
        for k, draft in enumerate(task_list.tasks, start=1)
    ]


def _group_sizes(n: int, groups: int) -> list[int]:
    """Returns the sizes of ``groups`` consecutive groups for ``n`` items.

    Sizes differ by at most one and the larger groups come first
    (DEC-092).

    Args:
        n: Number of items to split.
        groups: Number of groups, at most ``n``.

    Returns:
        The size of each group, in order; they add up to ``n``.
    """
    size, extra = divmod(n, groups)
    return [size + 1 if i < extra else size for i in range(groups)]


def _unique(items: list[str]) -> list[str]:
    """Returns the items without repetitions, keeping their first order.

    Args:
        items: Items that may repeat.

    Returns:
        The distinct items in order of first appearance.
    """
    return list(dict.fromkeys(items))


def _merge(group: list[TaskSpec], position: int) -> TaskSpec:
    """Returns one task that joins a group of consecutive tasks (DEC-082).

    Args:
        group: The tasks to join, in execution order.
        position: Position of the joined task in the new list, from 1; it
            gives the new task ID and priority (DEC-085).

    Returns:
        The joined task; ``merged_from`` lists the original task IDs.
    """
    if len(group) == 1:
        description = group[0].description
    else:
        description = "\n\n".join(
            f"Part {n} ({task.task_id}: {task.title}):\n{task.description}"
            for n, task in enumerate(group, start=1)
        )
    return TaskSpec(
        task_id=f"task_{position}",
        title=" + ".join(task.title for task in group),
        description=description,
        acceptance_criteria=[c for task in group for c in task.acceptance_criteria],
        covers=_unique([r for task in group for r in task.covers]),
        files=_unique([f for task in group for f in task.files]),
        priority=position,
        merged_from=[task.task_id for task in group],
    )


def consolidate_tasks(tasks: list[TaskSpec], max_tasks: int = MAX_TASKS) -> list[TaskSpec]:
    """Returns the task list reduced to at most ``max_tasks`` tasks (C2.4).

    Lists within the limit are returned unchanged. Longer lists are split
    into ``max_tasks`` consecutive groups of even size and each group is
    joined into one task, so no criterion, covered requirement or file is
    lost (DEC-082, DEC-092).

    Args:
        tasks: Tasks in execution order.
        max_tasks: Maximum number of tasks to keep.

    Returns:
        The tasks, at most ``max_tasks``, in execution order.

    Raises:
        ValueError: If ``max_tasks`` is lower than 1.
    """
    if max_tasks < 1:
        raise ValueError(f"max_tasks must be at least 1, got {max_tasks}")
    if len(tasks) <= max_tasks:
        return tasks
    merged = []
    start = 0
    for position, size in enumerate(_group_sizes(len(tasks), max_tasks), start=1):
        merged.append(_merge(tasks[start:start + size], position))
        start += size
    return merged


def make_pm_node(model: BaseChatModel | None = None) -> Callable[[ProjectState], dict]:
    """Returns the PM node function for the graph.

    Args:
        model: Chat model for the PM. If None, the node uses
            ``get_chat_model`` with ``PM_MODEL`` (default
            ``DEFAULT_PM_MODEL``), read when the node runs (DEC-093).

    Returns:
        The node: it takes the state and returns a partial update.
    """

    def pm_node(state: ProjectState) -> dict:
        """Returns the spec, the tasks and progress notes for the requirement.

        Never raises: any failure is logged and returned in ``error``
        (DEC-087).

        Args:
            state: Current state; only ``requirement`` is read.

        Returns:
            Update with ``spec``, ``tasks``, ``progress`` and ``error``.
        """
        progress = ["PM Agent: analysing requirement."]
        try:
            pm_model = model or get_chat_model(os.getenv("PM_MODEL", DEFAULT_PM_MODEL))
            spec = _build_spec(state.requirement, pm_model)
            progress.append("PM Agent: spec complete — decomposing into tasks.")
            planned = _build_tasks(spec, pm_model)
            tasks = consolidate_tasks(planned)
            if len(tasks) < len(planned):
                progress.append(
                    f"PM Agent: consolidated {len(planned)} tasks into {len(tasks)}."
                )
        except Exception as exc:  # DEC-087: the node never raises out of the graph
            error = f"{type(exc).__name__}: {exc}"
            logger.error("PM Agent failed: %s", error)
            return {
                "spec": None,
                "tasks": [],
                "progress": [*progress, f"PM Agent: failed — {error}"],
                "error": error,
            }
        progress.append(f"PM Agent: {len(tasks)} tasks created — handoff ready.")
        return {
            "spec": spec.model_copy(update={"tasks": tasks}),
            "tasks": [TaskState(**task.model_dump()) for task in tasks],
            "progress": progress,
            "error": "",
        }

    return pm_node

"""Shared project state of the agent team graph (C2.2, DEC-089, DEC-090).

The PM writes the specification and the task list; the Coder reads the
tasks, updates their status and accumulates the code. Every model is
Pydantic, so the same schema validates values at run time and serialises
the handoff to JSON (C2.3).

Typical usage example:

    state = ProjectState(requirement="Build a REST API with /health")
    payload = state.model_dump_json()
"""

import operator
from typing import Annotated, Literal

from pydantic import BaseModel, Field

NonEmptyStr = Annotated[str, Field(min_length=1)]

TaskStatus = Literal["pending", "in_progress", "done", "failed"]


class SpecCriterion(BaseModel):
    """One acceptance criterion of the specification (DEC-083).

    Attributes:
        id: Criterion ID that tasks refer to in ``covers``, e.g. ``"REQ-1"``.
        text: What must hold for the requirement to be met.
    """
    id: NonEmptyStr
    text: NonEmptyStr


class TaskCriterion(BaseModel):
    """One acceptance check of a task, in Given/When/Then form (DEC-095).

    Attributes:
        given: The starting situation, e.g. "the app is running".
        when: The action, e.g. "a client sends GET /health".
        then: The observable result, e.g. "it returns 200 with
            {'status': 'ok'}".
    """
    given: NonEmptyStr
    when: NonEmptyStr
    then: NonEmptyStr


class TaskSpec(BaseModel):
    """One task as planned by the PM: the handoff the Coder consumes (C2.3).

    Attributes:
        task_id: Task ID assigned by code, ``task_1``, ``task_2``... (DEC-090).
        title: Short imperative title.
        description: Self-contained instructions for the Coder.
        acceptance_criteria: Given/When/Then checks the task's code must
            pass (DEC-095).
        covers: IDs of the spec criteria this task covers (DEC-083).
        files: Files the task creates or edits; tasks may share files
            (DEC-084).
        priority: Position in the execution order, 1 runs first (DEC-085).
        merged_from: Original task IDs when the task results from
            consolidation; empty otherwise (DEC-082).
    """
    task_id: NonEmptyStr
    title: NonEmptyStr
    description: NonEmptyStr
    acceptance_criteria: list[TaskCriterion] = Field(min_length=1)
    covers: list[NonEmptyStr] = Field(min_length=1)
    files: list[NonEmptyStr] = Field(min_length=1)
    priority: int = Field(ge=1)
    merged_from: list[NonEmptyStr] = Field(default_factory=list)


class ProjectSpec(BaseModel):
    """The technical specification written by the PM (C2.1, DEC-083).

    It records what the PM decided and is not changed afterwards; execution
    progress lives in ``ProjectState.tasks`` (DEC-090).

    Attributes:
        name: Short name of the project.
        description: What the project does, in one or two sentences.
        details: Markdown with Overview, Functional Requirements,
            Non-Functional Requirements, File Structure and Constraints &
            Assumptions.
        acceptance_criteria: Criteria of the whole requirement, with IDs.
        tasks: The tasks in execution order.
    """
    name: NonEmptyStr
    description: NonEmptyStr
    details: NonEmptyStr
    acceptance_criteria: list[SpecCriterion] = Field(min_length=1)
    tasks: list[TaskSpec]


class TaskState(TaskSpec):
    """A task plus its execution status, updated by the Coder (C2.2).

    Attributes:
        status: Where the task stands in the execution.
    """
    status: TaskStatus = "pending"


class ProjectState(BaseModel):
    """State shared by every node of the graph (C2.2, DEC-090).

    Nodes return partial updates; ``progress`` is appended through its
    reducer and every other field is replaced.

    Attributes:
        requirement: The user's original requirement; never changed.
        spec: The PM's specification; None until the PM succeeds.
        tasks: The handoff task list with each task's status.
        code: Accumulated code output, file path to content.
        progress: Chronological progress notes of every node.
        error: Empty on success; the failure message otherwise (DEC-087).
    """
    requirement: NonEmptyStr
    spec: ProjectSpec | None = None
    tasks: list[TaskState] = Field(default_factory=list)
    code: dict[str, str] = Field(default_factory=dict)
    progress: Annotated[list[str], operator.add] = Field(default_factory=list)
    error: str = ""

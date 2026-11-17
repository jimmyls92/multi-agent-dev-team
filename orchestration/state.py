"""Shared project state of the agent team graph (C2.2, DEC-089, DEC-090).

The PM writes the specification and the task list; the Coder reads the
tasks, updates their status and accumulates the code; the QA returns a
report per task (DEC-153). Every model is
Pydantic, so the same schema validates values at run time and serialises
the handoff to JSON (C2.3).

Typical usage example:

    state = ProjectState(requirement="Build a REST API with /health")
    payload = state.model_dump_json()
"""

import operator
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

# Surrounding whitespace is stripped first, so blank text is rejected (C4.6).
NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

TaskStatus = Literal["pending", "in_progress", "done", "failed"]

Severity = Literal["High", "Medium", "Low"]

# Lower rank is more severe; a severity blocks when its rank is at most the
# threshold's (DEC-139).
_SEVERITY_RANK: dict[str, int] = {"High": 0, "Medium": 1, "Low": 2}


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


# --- Coder output (C1.4, C1.5, DEC-065, DEC-078, DEC-107) ------------------


class StepRecord(BaseModel):
    """Record of one action of the loop (C1.4, DEC-065, DEC-078).

    Attributes:
        iteration: Model call that produced the action, starting at 1.
        thought: The ``thought`` argument of the tool call (DEC-072); None
            when the model answered without a tool.
        action: Tool called, ``Finish`` included; None when the model
            answered without a tool.
        action_input: Arguments of the call without ``thought``.
        observation: Text sent back to the model: the tool's result, an
            error, or the nudge (DEC-073). None for the accepted Finish and
            for a text answer at the limit.
        rejected: True when validation rejected the tool call, so the tool
            did not run (DEC-076, DEC-106).
    """
    iteration: int
    thought: str | None = None
    action: str | None = None
    action_input: dict | None = None
    observation: str | None = None
    rejected: bool = False


class CoderResult(BaseModel):
    """Output of one whole task (C1.5, DEC-065).

    Attributes:
        status: How the task ended (DEC-055, DEC-056).
        plan: The plan from the planning step (DEC-071), as a numbered list.
        code: Content of main_file read from disk (DEC-052); empty without one.
        explanation: Explanation from Finish; empty without one.
        result: Output of the last valid execution (DEC-055, DEC-063);
            empty without one.
        main_file: Main file declared in Finish, if any.
        iterations: Model calls made in the tool loop (DEC-070).
        steps: Record of every action.
    """
    status: Literal["success", "failed_execution", "unverified", "max_iterations", "answered"]
    plan: str = ""
    code: str = ""
    explanation: str = ""
    result: str = ""
    main_file: str | None = None
    iterations: int = 0
    steps: list[StepRecord] = Field(default_factory=list)



class Issue(BaseModel):
    """One problem the QA found in a task (C3.1, DEC-149).

    Attributes:
        severity: How serious the problem is.
        location: Where it happens: a test, a file or a file and line.
        description: What is wrong, e.g. the assertion that failed.
        fix: What the Coder must change.
        source: Where the issue comes from: ``test`` (an executed test
            failed), ``review`` (the LLM's opinion) or ``qa`` (the QA could
            not do its job; not the Coder's fault).
        criterion: The Given/When/Then criterion broken; empty when none.
    """
    severity: Severity
    location: NonEmptyStr
    description: NonEmptyStr
    fix: NonEmptyStr
    source: Literal["test", "review", "qa"]
    criterion: str = ""

    @model_validator(mode="after")
    def _severity_matches_source(self) -> "Issue":
        """Checks that the severity is allowed for the issue's source.

        Returns:
            The issue unchanged.

        Raises:
            ValueError: If a ``test`` or ``qa`` issue is not High, or a
                ``review`` issue is High.
        """
        # DEC-139: only executed evidence (or the QA's own failure) blocks
        # by default; an LLM opinion is never High.
        if self.source == "review" and self.severity == "High":
            raise ValueError("a review issue must be Medium or Low")
        if self.source != "review" and self.severity != "High":
            raise ValueError(f"a {self.source} issue must be High")
        return self


class QAReport(BaseModel):
    """The QA's verdict on one task (C3.1, C3.3, DEC-149, DEC-153).

    Attributes:
        task_id: The task reviewed.
        issues: Problems found, from tests, the review or the QA itself.
        tests_passed: Tests that passed in the run.
        tests_failed: Tests that failed in the run.
        blocking_severity: Lowest severity that blocks approval.
        notes: Remarks on the run, e.g. "review unavailable".
        approved: Computed by the validator; any value given is ignored.
    """
    task_id: NonEmptyStr
    issues: list[Issue] = Field(default_factory=list)
    tests_passed: int = Field(default=0, ge=0)
    tests_failed: int = Field(default=0, ge=0)
    blocking_severity: Severity = "High"
    notes: list[str] = Field(default_factory=list)
    approved: bool = False

    @model_validator(mode="after")
    def _compute_approved(self) -> "QAReport":
        """Sets ``approved`` from the test counts and the issues.

        Returns:
            The report with ``approved`` True only if some test passed, none
            failed and no issue is at or above ``blocking_severity``.
        """
        # DEC-139, DEC-149: never approved without a passing test run,
        # whatever value the caller or an LLM gave.
        threshold = _SEVERITY_RANK[self.blocking_severity]
        blocking = any(_SEVERITY_RANK[issue.severity] <= threshold for issue in self.issues)
        self.approved = self.tests_passed > 0 and self.tests_failed == 0 and not blocking
        return self


class TaskState(TaskSpec):
    """A task plus its execution status and result, updated by the Coder (C2.2).

    Attributes:
        status: Where the task stands in the execution.
        result: The Coder's output for the task; None until the Coder runs
            it, or after a fatal error (DEC-102, DEC-107).
    """
    status: TaskStatus = "pending"
    result: CoderResult | None = None


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

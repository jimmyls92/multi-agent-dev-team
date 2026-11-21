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

from pydantic import BaseModel, Field, computed_field

from orchestration.a2a import A2AMessage
# DEC-188: the report models live in qa_report.py; re-exported for existing imports.
from orchestration.qa_report import Issue, NonEmptyStr, QAReport, Severity

__all__ = [
    "KIND_SEVERITY",
    "Bug",
    "CoderResult",
    "DefectKind",
    "FailedTest",
    "Issue",
    "NonEmptyStr",
    "ProjectSpec",
    "ProjectState",
    "QAReport",
    "Reflection",
    "ReviewRecord",
    "Severity",
    "SpecCriterion",
    "StepRecord",
    "TaskCriterion",
    "TaskSpec",
    "TaskState",
    "TaskStatus",
]

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


DefectKind = Literal[
    "logic_error",
    "crash",
    "security",
    "missing_edge_case",
    "unclear_error",
    "missing_type_annotation",
    "style",
    "naming",
    "docstring",
]

# DEC-182: the model picks a kind from definitions; the code fixes its severity.
KIND_SEVERITY: dict[str, Severity] = {
    "logic_error": "High",
    "crash": "High",
    "security": "High",
    "missing_edge_case": "Medium",
    "unclear_error": "Medium",
    "missing_type_annotation": "Low",
    "style": "Low",
    "naming": "Low",
    "docstring": "Low",
}


class Bug(BaseModel):
    """One defect found by the self-evaluation, with its diagnosis (DEC-183, DEC-196).

    Attributes:
        kind: Defect kind; the code maps it to a severity (DEC-182).
        location: File and function.
        evidence: A concrete input and the wrong result it gives.
        cause: Why the code fails.
        fix: The smallest change that fixes it.
    """
    kind: DefectKind
    location: NonEmptyStr
    evidence: NonEmptyStr
    cause: NonEmptyStr
    fix: NonEmptyStr

    @property
    def severity(self) -> Severity:
        """Returns the severity of the bug's kind."""
        return KIND_SEVERITY[self.kind]


class Reflection(BaseModel):
    """The version the reflect node sent to the QA and its evaluation (DEC-172, DEC-196).

    Attributes:
        version: Index of the version sent; 0 is the first pass's.
        high: High bugs of the version sent; None when its evaluation was
            unavailable (DEC-171).
        medium: Medium bugs, as ``high``.
        low: Low bugs, as ``high``.
        bugs: The bugs of the version sent, pending for the correction
            pass (DEC-187); empty when unavailable.
        improvements: Improvement passes run.
    """
    version: int = Field(default=0, ge=0)
    high: int | None = Field(default=None, ge=0)
    medium: int | None = Field(default=None, ge=0)
    low: int | None = Field(default=None, ge=0)
    bugs: list[Bug] = Field(default_factory=list)
    improvements: int = Field(default=0, ge=0)


class FailedTest(BaseModel):
    """A test of the QA that failed in one review (DEC-184).

    Attributes:
        name: The test's name, e.g. ``test_reverse_single``.
        criterion: The acceptance criterion the test checks; empty if
            unknown.
    """
    name: NonEmptyStr
    criterion: str = ""


class ReviewRecord(BaseModel):
    """What happened in one QA review of a task (DEC-184, DEC-194).

    Attributes:
        review: Review number n, starting at 1.
        explanation: The ``explanation`` of the version sent to the QA.
        high: High bugs of the sent version by the self-evaluation; None
            when the evaluation was unavailable (DEC-171).
        medium: Medium bugs, as ``high``.
        low: Low bugs, as ``high``.
        version: Index of the version sent, 0 for the pass before any
            improvement (DEC-172).
        tests_passed: Tests of the QA that passed.
        tests_failed: Tests of the QA that failed.
        failed_tests: Each failed test with its criterion.
    """
    review: int = Field(ge=1)
    explanation: str = ""
    high: int | None = Field(default=None, ge=0)
    medium: int | None = Field(default=None, ge=0)
    low: int | None = Field(default=None, ge=0)
    version: int = Field(default=0, ge=0)
    tests_passed: int = Field(default=0, ge=0)
    tests_failed: int = Field(default=0, ge=0)
    failed_tests: list[FailedTest] = Field(default_factory=list)


class TaskState(TaskSpec):
    """A task plus its execution status and result, updated by the Coder (C2.2).

    Attributes:
        status: Where the task stands in the execution.
        result: The Coder's output for the task; None until the Coder runs
            it, or after a fatal error (DEC-102, DEC-107).
        history: One record per QA review of the task, oldest first
            (DEC-184).
        reflection: What the reflect node sent in the current review;
            None before it runs (DEC-196).
        reviews: QA reviews of the task so far, n (DEC-163, DEC-178).
        qa_report: The QA's report of the last review; None before the
            first (DEC-178).
        closed_reason: Why the task closed unapproved, e.g. "review limit
            reached" or "out of time"; empty while open or once done
            (DEC-198).
    """
    status: TaskStatus = "pending"
    result: CoderResult | None = None
    history: list[ReviewRecord] = Field(default_factory=list)
    reflection: Reflection | None = None
    reviews: int = Field(default=0, ge=0)
    qa_report: QAReport | None = None
    closed_reason: str = ""


class ProjectState(BaseModel):
    """State shared by every node of the graph (C2.2, DEC-090).

    Nodes return partial updates; ``progress`` and ``messages`` are appended
    through their reducer and every other field is replaced.

    Attributes:
        requirement: The user's original requirement; never changed.
        spec: The PM's specification; None until the PM succeeds.
        tasks: The handoff task list with each task's status.
        code: Accumulated code output, file path to content.
        progress: Chronological progress notes of every node.
        messages: A2A messages between the agents, in send order; nodes
            append through ``orchestration.a2a.send`` only (DEC-175).
        error: Empty on success; the failure message otherwise (DEC-087).
        deadline: ``time.monotonic()`` value at which the run is out of
            time; None without a time limit. The routers check only this
            (DEC-168, DEC-198).
        deadline_at: The same moment as a local ISO time, for people only.
        outcome: Computed: ``success`` when the QA approved every task and
            there is no error, ``unresolved`` otherwise (DEC-181).
    """
    requirement: NonEmptyStr
    spec: ProjectSpec | None = None
    tasks: list[TaskState] = Field(default_factory=list)
    code: dict[str, str] = Field(default_factory=dict)
    progress: Annotated[list[str], operator.add] = Field(default_factory=list)
    messages: Annotated[list[A2AMessage], operator.add] = Field(default_factory=list)
    error: str = ""
    deadline: float | None = None
    deadline_at: str = ""

    @computed_field
    @property
    def outcome(self) -> Literal["success", "unresolved"]:
        """Returns ``success`` only when every task is done and there is no error (DEC-165, DEC-181)."""
        if not self.error and self.tasks and all(task.status == "done" for task in self.tasks):
            return "success"
        return "unresolved"

    def final_report(self) -> str:
        """Returns the report of every task not approved, empty on success (DEC-165, DEC-181).

        Returns:
            One block per task that is not done: why it closed, the review
            it stopped at and its blocking issues (or "not reviewed").
        """
        blocks = []
        for task in self.tasks:
            if task.status == "done":
                continue
            reason = task.closed_reason or ("not run" if task.status == "pending" else task.status)
            lines = [f"- {task.task_id} — {reason}; stopped at review {task.reviews}"]
            issues = task.qa_report.issues if task.qa_report else []
            lines += [f"    [{i.severity}] {i.location}: {i.description}" for i in issues]
            if not issues:
                lines.append("    not reviewed by the QA" if task.reviews == 0 else "    no issue reported")
            blocks.append("\n".join(lines))
        return "\n".join(blocks)

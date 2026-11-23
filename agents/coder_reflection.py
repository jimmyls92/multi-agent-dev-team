"""Self-reflection of the Coder agent: it evaluates its own version before the QA (C3.4).

One structured LLM call checks a version against a fixed rubric: one item
per acceptance criterion of the task (C0..Cn) plus E1-E11. Each item is
``ok``, ``bug`` or ``n/a`` with evidence, and each bug names its defect
kind and carries its diagnosis: location, evidence, cause and minimal
fix (DEC-182, DEC-183, DEC-193). The code, not the LLM, maps each kind to
a severity, so two versions can be ranked the same way every time.

The call sees only the version's files and the task; it reads and writes
no memory (DEC-173). If it gives no valid output in two calls, the
evaluation is unavailable and the version goes to the QA as it is
(DEC-171).

The ``reflect`` node runs the whole cycle between the Coder and the QA
(DEC-172, DEC-177, DEC-196): it evaluates the first pass's version, runs
up to ``REFLECTION_MAX_ROUNDS`` improvement passes while the best version
has any bug (DEC-201), puts the best version back on disk and sends it.

Attributes:
    EVALUATION_ATTEMPTS: Model calls allowed for one evaluation (DEC-171).
    EVALUATION_MODEL: Model of the evaluation call, from the
        ``EVALUATION_MODEL`` environment variable (DEC-200).
    RUBRIC_ITEMS: The fixed items E1-E11 and what each checks.
    EVALUATION_SYSTEM_PROMPT: Instructions for the evaluation call.

Typical usage example:

    evaluation = evaluate_version(task, {"linked_list.py": code}, model)
    if evaluation and evaluation.needs_improvement():
        ...
"""

import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Literal, NamedTuple

from langchain_core.language_models import BaseChatModel
from langgraph.runtime import Runtime
from pydantic import BaseModel, ConfigDict, Field, create_model, model_validator

import tools.handlers
import agents.coder_agent as coder_agent
from agents.coder_agent import (
    CoderRunContext,
    _resolved,
    _with_task,
    _written_files,
    improvement_prompt,
    run_agent,
)
from agents.llm_helpers import PYTHON_ENVIRONMENT, structured_call
from orchestration.a2a import A2AMessage, send
# DEC-196: the bug models live in the state; re-exported for existing imports.
from orchestration.state import (
    KIND_SEVERITY,
    Bug,
    CoderResult,
    DefectKind,
    NonEmptyStr,
    ProjectSpec,
    ProjectState,
    Reflection,
    TaskSpec,
    TaskState,
)

__all__ = [
    "KIND_SEVERITY",
    "RUBRIC_ITEMS",
    "Bug",
    "BugCounts",
    "DefectKind",
    "ItemCheck",
    "ItemVerdict",
    "SelfEvaluationBase",
    "best_version",
    "evaluate_version",
    "make_reflect_node",
    "reflect_task",
]

logger = logging.getLogger(__name__)

EVALUATION_ATTEMPTS = 2  # DEC-171: one corrective retry
# DEC-200: the small model left bug verdicts without a diagnosis; a larger one judges.
EVALUATION_MODEL = os.getenv("EVALUATION_MODEL", "openai/gpt-4.1")

RUBRIC_ITEMS: dict[str, str] = {
    "E1": "empty input: empty collections, empty strings, no elements",
    "E2": "one element and boundaries: first, last, single item, limits of ranges",
    "E3": "repeated values: duplicates are handled as the task says",
    "E4": "invalid input and errors: handled as the task says, with a clear message; no "
    "broad except that hides failures",
    "E5": "interface: files, names and signatures exactly as the task says",
    "E6": "state stays consistent across calls (e.g. size, head and tail after each operation)",
    "E7": "safe import and termination: importing runs nothing heavy, no endless loop or wait",
    "E8": "security: paths, injection, credentials; n/a when the code uses no files, "
    "network or processes",
    "E9": "type annotations on public functions",
    "E10": "style, naming and docstrings",
    "E11": "any other real defect that fits none of the items above, e.g. a file never "
    "closed or behaviour the description asks for but no criterion checks",
}

_KIND_HELP = """- logic_error: a wrong result on valid input.
- crash: an exception, hang or endless loop on valid input.
- security: path traversal, injection or hard-coded credentials.
- missing_edge_case: an edge case of the rubric is not handled.
- unclear_error: an error is raised or reported without a clear message.
- missing_type_annotation: a public function lacks type annotations.
- style: style problem. naming: unclear name. docstring: missing or wrong docstring."""

EVALUATION_SYSTEM_PROMPT = f"""You are a strict code reviewer checking one version of a task's code
before it goes to the QA team. Judge only the code you are given against the
task and its acceptance criteria.

The tool has one field per rubric item listed in the request (C0, C1... and
E1-E11); fill every field with one verdict:
- ok: you checked it and the code handles it; say briefly how.
- bug: the code fails it. List each bug. Every bug needs a concrete input and
  the wrong result it gives, traced through the code (evidence); no guesses.
- n/a: the item cannot apply to this code; say why. Criteria (C0, C1...)
  are never n/a.

For each bug give:
- kind, one of:
{_KIND_HELP}
- location: file and function.
- evidence: the concrete input and the wrong result.
- cause: why the code fails.
- fix: the smallest change that fixes it; never a rewrite, and never a change
  that breaks another criterion of the task.

Report each defect once, under the item it fits best; another item it also
affects is a bug only if it fails there in a different way, otherwise it is
ok and its evidence names the item where the defect is reported.

Do not invent problems: a version may have no bugs at all.

{PYTHON_ENVIRONMENT}"""


class ItemCheck(BaseModel):
    """The verdict on one rubric item, as the model fills it in one field (DEC-193, DEC-200).

    Attributes:
        verdict: ``ok``, ``bug`` or ``n/a``.
        evidence: Brief reason for the verdict.
        bugs: The item's bugs; at least one for ``bug``, none otherwise.
    """
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["ok", "bug", "n/a"]
    evidence: NonEmptyStr
    bugs: list[Bug] = Field(default_factory=list)

    @model_validator(mode="after")
    def _bugs_match_verdict(self) -> "ItemCheck":
        """Checks that only a ``bug`` verdict has bugs, and it has some.

        Returns:
            The verdict unchanged.

        Raises:
            ValueError: If a ``bug`` item has no bugs, or an ``ok`` or
                ``n/a`` item has any.
        """
        if self.verdict == "bug" and not self.bugs:
            raise ValueError("the item is a bug but lists no bug with its diagnosis")
        if self.verdict != "bug" and self.bugs:
            raise ValueError(f"the item is {self.verdict} but lists bugs")
        return self


class ItemVerdict(ItemCheck):
    """The verdict on one rubric item, with the item's name (DEC-193).

    Attributes:
        item: Rubric item, ``C0``..``Cn`` or ``E1``..``E11``.
    """
    item: NonEmptyStr


class BugCounts(NamedTuple):
    """Bugs of a version by severity; tuples compare in ranking order (DEC-182).

    Attributes:
        high: High bugs.
        medium: Medium bugs.
        low: Low bugs.
    """
    high: int
    medium: int
    low: int


class SelfEvaluationBase(BaseModel):
    """A self-evaluation, before the checks of one task's rubric.

    Attributes:
        items: One verdict per rubric item.
    """
    items: list[ItemVerdict]

    def bugs(self) -> list[Bug]:
        """Returns every bug of the evaluation, in item order."""
        return [bug for item in self.items for bug in item.bugs]

    def counts(self) -> BugCounts:
        """Returns the evaluation's bugs counted by severity."""
        severities = [bug.severity for bug in self.bugs()]
        return BugCounts(severities.count("High"), severities.count("Medium"), severities.count("Low"))

    def needs_improvement(self) -> bool:
        """Returns whether any bug, Low included, calls for an improvement pass (DEC-201)."""
        counts = self.counts()
        return counts.high + counts.medium + counts.low > 0


class _EvaluationSchema(BaseModel):
    """Base of the per-task schema the model fills: one required field per rubric item (DEC-200).

    Attributes:
        CRITERIA: Names of the task's criterion fields, ``C0``..``Cn``.
    """
    model_config = ConfigDict(extra="forbid")

    CRITERIA: ClassVar[tuple[str, ...]] = ()

    @model_validator(mode="after")
    def _criteria_apply(self) -> "_EvaluationSchema":
        """Checks that no acceptance criterion is ``n/a``.

        Returns:
            This evaluation.

        Raises:
            ValueError: If a criterion field is ``n/a``.
        """
        for name in self.CRITERIA:
            if getattr(self, name).verdict == "n/a":
                raise ValueError(f"criterion {name} cannot be n/a")
        return self

    def to_evaluation(self) -> SelfEvaluationBase:
        """Returns the evaluation as a list of named verdicts, in rubric order."""
        return SelfEvaluationBase(items=[
            ItemVerdict(item=name, **getattr(self, name).model_dump())
            for name in type(self).model_fields
        ])


def _evaluation_schema(task: TaskSpec) -> type[_EvaluationSchema]:
    """Returns the SelfEvaluation schema of one task: a required field per rubric item (DEC-193, DEC-200).

    The model cannot leave an item out or merge the list, since the tool
    call needs every field by name.

    Args:
        task: The task; its criteria become fields ``C0``..``Cn``.

    Returns:
        A model named ``SelfEvaluation``, the tool name the LLM sees, with
        fields ``C0``..``Cn`` then ``E1``..``E11``.
    """
    criteria = {
        f"C{k}": f"Acceptance criterion: Given {c.given}, When {c.when}, Then {c.then}"
        for k, c in enumerate(task.acceptance_criteria)
    }
    fields = {
        name: (ItemCheck, Field(description=text))
        for name, text in {**criteria, **RUBRIC_ITEMS}.items()
    }
    schema = create_model("SelfEvaluation", __base__=_EvaluationSchema, **fields)
    schema.CRITERIA = tuple(criteria)
    return schema


def _render_request(task: TaskSpec, files: Mapping[str, str]) -> str:
    """Returns the request of the evaluation call: the task and the version's files.

    Args:
        task: The task the version implements.
        files: File name to content of the version.

    Returns:
        Task, criteria, rubric items and code, in Markdown.
    """
    criteria = "\n".join(
        f"- C{k}: Given {c.given}, When {c.when}, Then {c.then}"
        for k, c in enumerate(task.acceptance_criteria)
    )
    rubric = "\n".join(f"- {item}: {text}" for item, text in RUBRIC_ITEMS.items())
    code = "\n\n".join(
        f"### {name}\n```python\n{content}\n```" for name, content in files.items()
    ) or "(no file of the task exists)"
    return (
        f"# Task {task.task_id}: {task.title}\n\n{task.description}\n\n"
        f"## Acceptance criteria\n{criteria}\n\n## Rubric items\n{rubric}\n\n## Code\n{code}"
    )


def evaluate_version(
    task: TaskSpec, files: Mapping[str, str], model: BaseChatModel
) -> SelfEvaluationBase | None:
    """Returns the self-evaluation of one version of a task, or None if unavailable.

    The call sees only the version's files and the task, and uses no
    memory (DEC-173). It gets one corrective retry (DEC-171).

    Args:
        task: The task the version implements.
        files: File name to content of the version.
        model: Chat model of the Coder.

    Returns:
        The validated evaluation; None, with a WARNING "critique
        unavailable", if no output of ``EVALUATION_ATTEMPTS`` calls was
        valid or the call failed.
    """
    schema = _evaluation_schema(task)
    try:
        evaluation = structured_call(
            model, schema, EVALUATION_SYSTEM_PROMPT, _render_request(task, files),
            max_attempts=EVALUATION_ATTEMPTS,
        ).to_evaluation()
    except Exception as e:
        logger.warning("%s: critique unavailable: %s: %s", task.task_id, type(e).__name__, e)
        return None
    logger.info(
        "%s: self-evaluation: %d High, %d Medium, %d Low",
        task.task_id,
        *evaluation.counts(),
    )
    return evaluation


def best_version(counts: list[BugCounts]) -> int:
    """Returns the index of the best version; on a tie, the latest wins (DEC-172, DEC-182).

    Args:
        counts: Bug counts of each version, oldest first.

    Returns:
        The index of the version with the fewest High bugs, then Medium,
        then Low.
    """
    best = 0
    for index, current in enumerate(counts):
        if current <= counts[best]:
            best = index
    return best


# --- The reflect node (DEC-172, DEC-177, DEC-196) ---------------------------


Snapshot = dict[str, bytes]

# Caches that Python and pytest rebuild on their own; never part of a version.
_CACHE_DIRS = frozenset({"__pycache__", ".pytest_cache"})


@dataclass
class _Version:
    """One version of the task's code kept by the reflect node.

    Attributes:
        index: 0 for the first pass's version, then 1, 2...
        result: The CoderResult of the pass that wrote it.
        snapshot: The whole workspace right after that pass.
        evaluation: Its self-evaluation; None when unavailable.
    """
    index: int
    result: CoderResult
    snapshot: Snapshot
    evaluation: SelfEvaluationBase | None


def _snapshot() -> Snapshot:
    """Returns every file of the Coder's workspace as bytes, caches left out (DEC-196).

    Returns:
        Path relative to the workspace to the file's bytes.
    """
    root = Path(tools.handlers.CODER_WORKSPACE_DIR)
    if not root.is_dir():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not _CACHE_DIRS.intersection(path.relative_to(root).parts)
    }


def _restore(snapshot: Snapshot) -> None:
    """Makes the Coder's workspace identical to a snapshot (DEC-196).

    Files missing from the snapshot are deleted; files that differ are
    rewritten.

    Args:
        snapshot: The workspace to restore.
    """
    root = Path(tools.handlers.CODER_WORKSPACE_DIR)
    for name in _snapshot():
        if name not in snapshot:
            (root / name).unlink()
    for name, content in snapshot.items():
        path = root / name
        if not path.is_file() or path.read_bytes() != content:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)


def _version_files(task: TaskState, result: CoderResult) -> dict[str, str]:
    """Returns the files a version is judged on: its planned files and those its pass wrote.

    Args:
        task: The task; its planned files that exist are included.
        result: The pass's result; the files it wrote are included.

    Returns:
        File name to content.
    """
    files = {}
    for name in task.files:
        path = _resolved(name)
        if path is not None and Path(path).is_file():
            try:
                files[name] = Path(path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                logger.warning("%s: cannot read %s for the evaluation: %s", task.task_id, name, exc)
    return {**files, **_written_files(result)}


def _log_evaluation(task: TaskState, version: _Version) -> None:
    """Logs at INFO each bug of a version's evaluation and its counts.

    Args:
        task: The task reviewed.
        version: A version with an evaluation.
    """
    for item in version.evaluation.items:
        for bug in item.bugs:
            logger.info(
                "%s: critique v%d: %s %s %s at %s: %s",
                task.task_id, version.index, item.item, bug.severity, bug.kind, bug.location, bug.cause,
            )
    logger.info("%s: v%d: %d High, %d Medium, %d Low", task.task_id, version.index,
                *version.evaluation.counts())


def _regressions(best: SelfEvaluationBase, worse: SelfEvaluationBase) -> list[Bug]:
    """Returns the bugs of a discarded version on items the best version had ``ok`` (DEC-172).

    Args:
        best: Evaluation of the best version.
        worse: Evaluation of the discarded version.

    Returns:
        The discarded version's bugs on those items.
    """
    ok = {item.item for item in best.items if item.verdict == "ok"}
    return [bug for item in worse.items if item.item in ok for bug in item.bugs]


def _reflection(version: _Version, improvements: int) -> Reflection:
    """Returns the record of the version sent.

    Args:
        version: The version sent.
        improvements: Improvement passes run.

    Returns:
        The version, its bug counts and bugs; counts None if unevaluated.
    """
    if version.evaluation is None:
        return Reflection(version=version.index, improvements=improvements)
    high, medium, low = version.evaluation.counts()
    return Reflection(
        version=version.index,
        high=high,
        medium=medium,
        low=low,
        bugs=version.evaluation.bugs(),
        improvements=improvements,
    )


def reflect_task(
    task: TaskState,
    spec: ProjectSpec | None,
    written: list[str],
    window,
    model: BaseChatModel | None,
    max_rounds: int,
    evaluation_model: BaseChatModel | None = None,
) -> tuple[CoderResult, Reflection]:
    """Evaluates the task's version, improves it and leaves the best one on disk (DEC-172).

    Each improvement starts from the best version so far and gets the
    regressions of the last discarded attempt. An improvement identical
    to its starting version is not evaluated; an improved version whose
    evaluation is unavailable is sent; a failed improvement pass restores
    the best version (DEC-196).

    Args:
        task: The task, with the first pass's result.
        spec: The PM's spec, or None.
        written: Files already written in this run.
        window: The Coder's window; improvement passes add their turn.
        model: Chat model of the Coder's improvement passes; None uses the
            configured one.
        max_rounds: ``REFLECTION_MAX_ROUNDS``.
        evaluation_model: Chat model of the evaluation; None uses ``model``
            (DEC-200).

    Returns:
        The result of the version sent and its reflection record.
    """
    judge = evaluation_model or model
    first = _Version(0, task.result, _snapshot(), None)
    first.evaluation = evaluate_version(task, _version_files(task, task.result), judge)
    if first.evaluation is None:
        return first.result, _reflection(first, 0)
    _log_evaluation(task, first)
    if not first.evaluation.needs_improvement():
        logger.info("%s: no improvement needed for v0", task.task_id)
    versions = [first]
    best = first
    regressions: list[Bug] = []
    discarded_explanation = ""
    rounds = 0
    while rounds < max_rounds and best.evaluation.needs_improvement():
        rounds += 1
        _restore(best.snapshot)
        prompt = improvement_prompt(
            task, spec, written, best.evaluation, regressions, discarded_explanation
        )
        try:
            result = run_agent(prompt, window, model)
        except Exception as exc:  # DEC-196: a failed improvement keeps the best version
            logger.warning("%s: improvement pass %d failed, keeping v%d: %s: %s",
                           task.task_id, rounds, best.index, type(exc).__name__, exc)
            _restore(best.snapshot)
            break
        snapshot = _snapshot()
        if snapshot == best.snapshot:
            logger.info("%s: improvement pass %d changed nothing; v%d stays",
                        task.task_id, rounds, best.index)
            break
        version = _Version(len(versions), result, snapshot, None)
        version.evaluation = evaluate_version(task, _version_files(task, result), judge)
        versions.append(version)
        if version.evaluation is None:  # DEC-196: sent unevaluated, it was written to fix bugs
            best = version
            break
        _log_evaluation(task, version)
        chosen = versions[best_version([v.evaluation.counts() for v in versions])]
        if chosen is not version:
            regressions = _regressions(chosen.evaluation, version.evaluation)
            discarded_explanation = result.explanation
        best = chosen
    _restore(best.snapshot)
    logger.info("%s: sent v%d after %d improvement pass(es)", task.task_id, best.index, rounds)
    return best.result, _reflection(best, rounds)


def _reviewed_task(state: ProjectState) -> TaskState | str:
    """Returns the one task in progress, or an error message (DEC-196).

    Args:
        state: Current state.

    Returns:
        The task in progress with a result, or why there is none.
    """
    current = [task for task in state.tasks if task.status == "in_progress"]
    if len(current) != 1:
        return f"Reflect: expected one task in progress, found {len(current)}."
    if current[0].result is None:
        return f"Reflect: {current[0].task_id} has no result to review."
    return current[0]


def make_reflect_node(
    model: BaseChatModel | None = None,
) -> Callable[[ProjectState, Runtime[CoderRunContext]], dict]:
    """Returns the reflect node, between the Coder and the QA (DEC-177).

    Args:
        model: Chat model of the Coder, also used for the evaluation when
            given (tests). None uses the Coder's configured model for the
            improvement passes and ``EVALUATION_MODEL`` for the evaluation,
            both through the Coder's own ``get_chat_model`` (DEC-193,
            DEC-200).

    Returns:
        The node: it takes the state and the run's runtime and returns a
        partial update.
    """

    def reflect_node(state: ProjectState, runtime: Runtime[CoderRunContext]) -> dict:
        """Reviews the task in progress and asks the QA to review the version chosen.

        Args:
            state: Current state; reads ``tasks``, ``spec``, ``code`` and
                ``messages``.
            runtime: The run's runtime; its context holds the window and the
                run's settings (DEC-197).

        Returns:
            Update with ``tasks`` (result and reflection of the version
            sent), ``code``, ``messages`` (the ``review_request``, DEC-197)
            and ``progress``; only ``progress`` and ``error`` when there is
            no single task in progress or no context.
        """
        task = _reviewed_task(state)
        error = task if isinstance(task, str) else ""
        if not error and runtime.context is None:
            error = "Reflect: no run context; invoke the graph with context=CoderRunContext()."
        if error:
            logger.error(error)
            return {"progress": [error], "error": error}

        settings = runtime.context.settings
        result, reflection = reflect_task(
            task, state.spec, list(state.code), runtime.context.window,
            model, settings.reflection_max_rounds,
            # DEC-200: tests pass one fake for both; otherwise the larger evaluation model.
            model or coder_agent.get_chat_model(EVALUATION_MODEL),
        )
        # A restored version may have removed files a discarded pass added.
        files = {name: content for name, content in state.code.items()
                 if (path := _resolved(name)) is not None and Path(path).is_file()}
        files.update(_written_files(result))
        review = task.reviews + 1
        request = A2AMessage(
            sender="coder",
            receiver="qa",
            intent="review_request",
            payload={"task_id": task.task_id, "review": review, "limit": settings.qa_max_iterations},
        )
        return {
            "tasks": _with_task(state.tasks, task.task_id, result=result, reflection=reflection),
            "code": files,
            "progress": [f"Reflect: {task.task_id} sends v{reflection.version} for review {review}."],
            "error": "",
            **send(state, request),
        }

    return reflect_node

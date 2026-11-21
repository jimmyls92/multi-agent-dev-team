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

Attributes:
    RUBRIC_ITEMS: The fixed items E1-E11 and what each checks.
    KIND_SEVERITY: Defect kind to severity (DEC-182).
    EVALUATION_SYSTEM_PROMPT: Instructions for the evaluation call.

Typical usage example:

    evaluation = evaluate_version(task, {"linked_list.py": code}, model)
    if evaluation and evaluation.needs_improvement():
        ...
"""

import logging
from collections.abc import Mapping
from typing import Literal, NamedTuple

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field, model_validator

from agents.llm_helpers import structured_call
from orchestration.state import NonEmptyStr, Severity, TaskSpec

logger = logging.getLogger(__name__)

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

Give exactly one verdict for every rubric item listed in the request:
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

Do not invent problems: a version may have no bugs at all."""


class Bug(BaseModel):
    """One defect found by the self-evaluation, with its diagnosis (DEC-183).

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


class ItemVerdict(BaseModel):
    """The verdict on one rubric item (DEC-193).

    Attributes:
        item: Rubric item, ``C0``..``Cn`` or ``E1``..``E11``.
        verdict: ``ok``, ``bug`` or ``n/a``.
        evidence: Brief reason for the verdict.
        bugs: The item's bugs; at least one for ``bug``, none otherwise.
    """
    item: NonEmptyStr
    verdict: Literal["ok", "bug", "n/a"]
    evidence: NonEmptyStr
    bugs: list[Bug] = Field(default_factory=list)

    @model_validator(mode="after")
    def _bugs_match_verdict(self) -> "ItemVerdict":
        """Checks that only a ``bug`` verdict has bugs, and it has some.

        Returns:
            The verdict unchanged.

        Raises:
            ValueError: If a ``bug`` item has no bugs, or an ``ok`` or
                ``n/a`` item has any.
        """
        if self.verdict == "bug" and not self.bugs:
            raise ValueError(f"item {self.item} is a bug but lists no bug with its diagnosis")
        if self.verdict != "bug" and self.bugs:
            raise ValueError(f"item {self.item} is {self.verdict} but lists bugs")
        return self


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
        """Returns whether a High or Medium bug calls for an improvement pass (DEC-182)."""
        counts = self.counts()
        return counts.high + counts.medium > 0


def _evaluation_schema(criteria_count: int) -> type[SelfEvaluationBase]:
    """Returns a SelfEvaluation schema with the rubric of one task (DEC-193).

    Args:
        criteria_count: Number of acceptance criteria of the task.

    Returns:
        A subclass of ``SelfEvaluationBase`` named ``SelfEvaluation``, the
        tool name the LLM sees.
    """
    criteria = [f"C{k}" for k in range(criteria_count)]
    expected = [*criteria, *RUBRIC_ITEMS]

    class SelfEvaluation(SelfEvaluationBase):
        """Self-evaluation with exactly one verdict per rubric item of the task."""

        @model_validator(mode="after")
        def _check_items(self) -> "SelfEvaluation":
            """Returns the evaluation if it covers each item exactly once.

            Returns:
                This evaluation.

            Raises:
                ValueError: If an item is unknown, repeated or missing, or a
                    criterion is ``n/a``.
            """
            given = [verdict.item for verdict in self.items]
            for item in given:
                if item not in expected:
                    raise ValueError(f"unknown item {item}; the items are {', '.join(expected)}")
                if given.count(item) > 1:
                    raise ValueError(f"item {item} is given more than once")
            missing = [item for item in expected if item not in given]
            if missing:
                raise ValueError(f"no verdict for {', '.join(missing)}")
            for verdict in self.items:
                if verdict.item in criteria and verdict.verdict == "n/a":
                    raise ValueError(f"criterion {verdict.item} cannot be n/a")
            return self

    return SelfEvaluation


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
        unavailable", if no output was valid or the call failed.
    """
    schema = _evaluation_schema(len(task.acceptance_criteria))
    try:
        evaluation = structured_call(
            model, schema, EVALUATION_SYSTEM_PROMPT, _render_request(task, files), max_attempts=2
        )
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

"""QA report models: the issues the QA finds and its verdict on a task (C3.1, DEC-149).

They live apart from ``orchestration.state`` because the A2A messages carry
a report and the state carries the messages (DEC-188); ``orchestration.state``
re-exports them.

Typical usage example:

    report = QAReport(task_id="task_1", tests_passed=2)
    assert report.approved
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

# Surrounding whitespace is stripped first, so blank text is rejected (C4.6).
NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

Severity = Literal["High", "Medium", "Low"]

# Lower rank is more severe; a severity blocks when its rank is at most the
# threshold's (DEC-139).
_SEVERITY_RANK: dict[str, int] = {"High": 0, "Medium": 1, "Low": 2}


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

    def blocking_issues(self) -> list[Issue]:
        """Returns the issues at or above ``blocking_severity`` (DEC-139).

        Returns:
            The blocking issues, in report order.
        """
        threshold = _SEVERITY_RANK[self.blocking_severity]
        return [issue for issue in self.issues if _SEVERITY_RANK[issue.severity] <= threshold]

    @model_validator(mode="after")
    def _compute_approved(self) -> "QAReport":
        """Sets ``approved`` from the test counts and the issues.

        Returns:
            The report with ``approved`` True only if some test passed, none
            failed and no issue is at or above ``blocking_severity``.
        """
        # DEC-139, DEC-149: never approved without a passing test run,
        # whatever value the caller or an LLM gave.
        self.approved = (
            self.tests_passed > 0 and self.tests_failed == 0 and not self.blocking_issues()
        )
        return self

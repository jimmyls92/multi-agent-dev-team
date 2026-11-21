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


class Issue(BaseModel):
    """One problem the QA found in a task (C3.1, DEC-149, DEC-174).

    Attributes:
        severity: How serious the problem is; always High, since every
            issue comes from executed evidence (DEC-174). Kept from the
            lab's schema.
        location: Where it happens: a test, a file or a file and line.
        description: What is wrong, e.g. the assertion that failed.
        fix: What the Coder must change.
        source: Where the issue comes from: ``test`` (an executed test
            failed or could not import the code) or ``qa`` (the QA could not
            do its job; not the Coder's fault).
        criterion: The Given/When/Then criterion broken; empty when none.
        test_code: The failing test function as written, decorators
            included; empty for any other issue (DEC-191).
    """
    severity: Severity
    location: NonEmptyStr
    description: NonEmptyStr
    fix: NonEmptyStr
    source: Literal["test", "qa"]
    criterion: str = ""
    test_code: str = ""

    @model_validator(mode="after")
    def _always_high(self) -> "Issue":
        """Checks that the issue is High.

        Returns:
            The issue unchanged.

        Raises:
            ValueError: If the severity is not High.
        """
        # DEC-174: only executed evidence (or the QA's own failure) is an
        # issue, and it always blocks.
        if self.severity != "High":
            raise ValueError(f"a {self.source} issue must be High")
        return self


class QAReport(BaseModel):
    """The QA's verdict on one task (C3.1, C3.3, DEC-149, DEC-153, DEC-174).

    Attributes:
        task_id: The task reviewed.
        issues: Problems found by the tests or the QA itself.
        tests_passed: Tests that passed in the run.
        tests_failed: Tests that failed in the run.
        notes: Remarks on the run, e.g. "review unavailable".
        approved: Computed by the validator; any value given is ignored.
    """
    task_id: NonEmptyStr
    issues: list[Issue] = Field(default_factory=list)
    tests_passed: int = Field(default=0, ge=0)
    tests_failed: int = Field(default=0, ge=0)
    notes: list[str] = Field(default_factory=list)
    approved: bool = False

    @model_validator(mode="after")
    def _compute_approved(self) -> "QAReport":
        """Sets ``approved`` from the test counts and the issues.

        Returns:
            The report with ``approved`` True only if some test passed, none
            failed and there is no issue.
        """
        # DEC-139, DEC-149, DEC-174: never approved without a passing test
        # run, whatever value the caller or an LLM gave.
        self.approved = self.tests_passed > 0 and self.tests_failed == 0 and not self.issues
        return self

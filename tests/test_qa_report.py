"""Tests of the QA's report models and settings (Lab 3.2, T2).

Covers spec `lab_3_2_qa_agent` AC-3.2-4, AC-3.2-5 and AC-3.2-6
(DEC-139, DEC-149, DEC-151, DEC-153, DEC-154).
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

import agents.qa_agent
from agents.qa_agent import load_qa_settings
from orchestration.state import QAReport

_REPO_ROOT = Path(agents.qa_agent.__file__).resolve().parent.parent


def _issue(**changes) -> dict:
    """Returns data for a valid ``test`` issue, with some fields changed.

    Args:
        **changes: Fields to override or add.

    Returns:
        A dict that ``Issue`` accepts unless ``changes`` breaks it.
    """
    data = {
        "severity": "High",
        "location": "test_task_1.py::test_insert_order",
        "description": "assert [1, 2, 3] == [3, 2, 1]",
        "fix": "Insert new values at the head of the list.",
        "source": "test",
        "criterion": "Given a list built with insert(1) then insert(2), ...",
    }
    data.update(changes)
    return data


def _report(issues: list[dict], passed: int, failed: int, threshold: str) -> QAReport:
    """Builds a report that claims to be approved.

    Args:
        issues: Issue data.
        passed: Tests that passed.
        failed: Tests that failed.
        threshold: Lowest severity that blocks.

    Returns:
        The validated report.
    """
    return QAReport(
        task_id="task_1",
        issues=issues,
        tests_passed=passed,
        tests_failed=failed,
        blocking_severity=threshold,
        approved=True,
    )


def test_ac_3_2_4_qa_settings(tmp_path):
    coder = (tmp_path / "coder").resolve()

    settings = load_qa_settings({}, exec_timeout=10, coder_dir=coder)
    assert settings.workspace_dir == _REPO_ROOT / "workspace_qa"
    assert settings.model == "openai/gpt-4.1-mini"
    assert settings.max_attempts == 2
    assert settings.blocking_severity == "High"
    assert settings.test_timeout == 2

    invalid = [
        ("QA_MAX_ATTEMPTS", "0"),
        ("QA_MAX_ATTEMPTS", "x"),
        ("QA_BLOCKING_SEVERITY", "Critical"),
        ("QA_TEST_TIMEOUT", "0"),
        ("QA_TEST_TIMEOUT", "10"),
        ("QA_WORKSPACE_DIR", str(coder)),
        ("QA_WORKSPACE_DIR", str(coder / "qa")),
        ("QA_WORKSPACE_DIR", str(tmp_path)),
        ("QA_WORKSPACE_DIR", " "),
    ]
    for name, value in invalid:
        with pytest.raises(ValueError, match=name):
            load_qa_settings({name: value}, exec_timeout=10, coder_dir=coder)


@pytest.mark.parametrize(
    "changes",
    [
        {"severity": "Critical"},
        {"source": "opinion"},
        {"fix": None},
        {"source": "review", "severity": "High"},
    ],
    ids=["critical", "opinion", "no-fix", "review-high"],
)
def test_ac_3_2_5_issue_validation(changes):
    data = _issue(**changes)
    data = {key: value for key, value in data.items() if value is not None}
    with pytest.raises(ValidationError):
        _report([data], passed=1, failed=1, threshold="High")


def test_ac_3_2_5_valid_issues_accepted():
    report = _report(
        [_issue(), _issue(source="review", severity="Low", criterion="")],
        passed=1,
        failed=1,
        threshold="High",
    )
    assert [issue.source for issue in report.issues] == ["test", "review"]


@pytest.mark.parametrize("source", ["test", "qa"])
def test_test_and_qa_issues_must_be_high(source):
    with pytest.raises(ValidationError):
        _report([_issue(source=source, severity="Medium")], passed=0, failed=1, threshold="High")


@pytest.mark.parametrize(
    ("issues", "passed", "failed", "threshold", "approved"),
    [
        ([_issue(source="review", severity="Medium")], 2, 0, "High", True),
        ([_issue(source="review", severity="Medium")], 2, 0, "Medium", False),
        ([_issue()], 1, 1, "High", False),
        ([], 0, 0, "Low", False),
        ([_issue(source="qa", criterion="")], 0, 0, "High", False),
    ],
    ids=["a-review-below-threshold", "b-review-at-threshold", "c-test-failed",
         "d-no-test-ran", "e-qa-issue"],
)
def test_ac_3_2_6_approved_rule(issues, passed, failed, threshold, approved):
    assert _report(issues, passed, failed, threshold).approved is approved

"""Tests of the QA's report models and settings (Lab 3.2, T2).

Covers spec `lab_3_2_qa_agent` AC-3.2-4, AC-3.2-5 and AC-3.2-6
(DEC-139, DEC-149, DEC-151, DEC-153, DEC-154), as changed by DEC-174, and
spec `lab_3_3_a2a_loop` AC-3.3-11 (DEC-174, DEC-191).
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


def _report(issues: list[dict], passed: int, failed: int) -> QAReport:
    """Builds a report that claims to be approved.

    Args:
        issues: Issue data.
        passed: Tests that passed.
        failed: Tests that failed.

    Returns:
        The validated report.
    """
    return QAReport(
        task_id="task_1",
        issues=issues,
        tests_passed=passed,
        tests_failed=failed,
        approved=True,
    )


def test_ac_3_2_4_qa_settings(tmp_path):
    coder = (tmp_path / "coder").resolve()

    settings = load_qa_settings({}, exec_timeout=10, coder_dir=coder)
    assert settings.workspace_dir == _REPO_ROOT / "workspace_qa"
    assert settings.model == "openai/gpt-4.1-mini"
    assert settings.max_attempts == 2
    assert settings.test_timeout == 2

    invalid = [
        ("QA_MAX_ATTEMPTS", "0"),
        ("QA_MAX_ATTEMPTS", "x"),
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
        {"source": "review", "severity": "Low"},
    ],
    ids=["critical", "opinion", "no-fix", "review"],
)
def test_ac_3_2_5_issue_validation(changes):
    data = _issue(**changes)
    data = {key: value for key, value in data.items() if value is not None}
    with pytest.raises(ValidationError):
        _report([data], passed=1, failed=1)


def test_ac_3_2_5_valid_issues_accepted():
    report = _report(
        [_issue(test_code="def test_insert_order():\n    assert False\n"), _issue(source="qa", criterion="")],
        passed=1,
        failed=1,
    )
    assert [issue.source for issue in report.issues] == ["test", "qa"]
    assert report.issues[1].test_code == ""


@pytest.mark.parametrize("source", ["test", "qa"])
def test_test_and_qa_issues_must_be_high(source):
    with pytest.raises(ValidationError):
        _report([_issue(source=source, severity="Medium")], passed=0, failed=1)


@pytest.mark.parametrize(
    ("issues", "passed", "failed", "approved"),
    [
        ([], 2, 0, True),
        ([_issue()], 1, 1, False),
        ([], 0, 0, False),
        ([_issue(source="qa", criterion="")], 0, 0, False),
        ([_issue(source="qa", criterion="")], 2, 0, False),
    ],
    ids=["a-all-passed", "c-test-failed", "d-no-test-ran", "e-qa-issue", "f-qa-issue-after-green"],
)
def test_ac_3_2_6_approved_rule(issues, passed, failed, approved):
    assert _report(issues, passed, failed).approved is approved


def test_ac_3_3_11_no_review_source(tmp_path, caplog):
    with pytest.raises(ValidationError):
        _report([_issue(source="review", severity="Medium")], passed=2, failed=0)

    coder = (tmp_path / "coder").resolve()
    settings = load_qa_settings({"QA_BLOCKING_SEVERITY": "Medium"}, exec_timeout=10, coder_dir=coder)
    assert not hasattr(settings, "blocking_severity")
    assert "QA_BLOCKING_SEVERITY" in caplog.text
    assert any(r.levelname == "WARNING" for r in caplog.records)

    env_example = (_REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "QA_BLOCKING_SEVERITY" not in env_example


@pytest.mark.parametrize(("exec_timeout", "expected"), [(1, 1), (2, 1), (3, 2), (10, 2)])
def test_ac_3_3_43_default_test_timeout_follows_exec_timeout(tmp_path, exec_timeout, expected):
    settings = load_qa_settings({}, exec_timeout=exec_timeout, coder_dir=(tmp_path / "coder").resolve())

    assert settings.test_timeout == expected


def test_ac_3_3_43_explicit_test_timeout_still_checked(tmp_path):
    with pytest.raises(ValueError, match="QA_TEST_TIMEOUT"):
        load_qa_settings({"QA_TEST_TIMEOUT": "2"}, exec_timeout=2, coder_dir=(tmp_path / "coder").resolve())

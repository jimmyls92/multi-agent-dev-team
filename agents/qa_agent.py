"""QA & Debugger agent (Lab 3.2).

Reviews one task of the PM's handoff: it reads the Coder's files through the
MCP server, writes pytest tests for the task's acceptance criteria and
returns a ``QAReport`` (``orchestration.state``) whose verdict comes from
the executed tests (DEC-137, DEC-139).

Its settings come from environment variables and are checked when the
module is imported, so a wrong value stops the program at startup
(DEC-151). ``write_tests`` asks the model for a test draft, validates it
with a per-task schema and writes it to the QA's folder (DEC-148); the
model sees the criteria and only the interface of the code (DEC-158).
``run_qa`` chains the steps and never raises: anything that stops it
becomes a ``qa`` issue in an unapproved report (DEC-142).

Attributes:
    DEFAULT_QA_MODEL: Small, fast model used when ``QA_MODEL`` is unset
        (C4.5, DEC-150).
    QA_SETTINGS: Settings read at import time from the environment.
    TESTS_SYSTEM_PROMPT: Instructions for writing the tests of a task.

Typical usage example:

    report = await run_qa(task)
    print(report.approved, report.issues)
"""

import ast
import asyncio
import logging
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TextIO, get_args

from dotenv import load_dotenv
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, ConfigDict, Field, model_validator

from agents.llm_helpers import PYTHON_ENVIRONMENT, StructuredOutputError, structured_call
from llm_client import get_chat_model
from orchestration.state import (
    Issue,
    NonEmptyStr,
    QAReport,
    Severity,
    TaskCriterion,
    TaskSpec,
)
from tools import handlers
from tools.code_executor import EXEC_TIMEOUT, PytestResult, run_pytest
from tools.mcp_client import read_multiple_files

load_dotenv()

logger = logging.getLogger(__name__)

DEFAULT_QA_MODEL = "openai/gpt-4.1-mini"  # DEC-150

_REPO_ROOT = Path(__file__).resolve().parent.parent


class QASettings(BaseModel):
    """The QA's validated settings (DEC-151).

    Attributes:
        workspace_dir: Absolute path of the QA's folder for its tests
            (DEC-140).
        model: Model the QA calls (DEC-150).
        max_attempts: Attempts the QA has to produce runnable tests
            (DEC-141).
        blocking_severity: Lowest severity that blocks approval (DEC-139).
        test_timeout: Seconds each test may run (DEC-152).
    """
    model_config = ConfigDict(frozen=True)

    workspace_dir: Path
    model: str
    max_attempts: int
    blocking_severity: Severity
    test_timeout: int


def _int_setting(env: Mapping[str, str], name: str, default: int, minimum: int) -> int:
    """Returns an integer setting, checked against its minimum.

    Args:
        env: Environment variables.
        name: Variable to read.
        default: Value when the variable is unset.
        minimum: Lowest value allowed.

    Returns:
        The variable's value as an integer, or ``default``.

    Raises:
        ValueError: If the value is not an integer or is below ``minimum``;
            the message names the variable.
    """
    raw = env.get(name, str(default))
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from None
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}, got {value}")
    return value


def load_qa_settings(
    env: Mapping[str, str], exec_timeout: int, coder_dir: Path
) -> QASettings:
    """Returns the QA's settings from the environment, with defaults.

    Args:
        env: Environment variables, usually ``os.environ``.
        exec_timeout: The whole run's timeout (``EXEC_TIMEOUT``); each test's
            timeout must be lower.
        coder_dir: The Coder's folder, which the QA's folder must not
            overlap.

    Returns:
        The validated settings.

    Raises:
        ValueError: If any value is invalid; the message names its variable.
    """
    folder = env.get("QA_WORKSPACE_DIR", "workspace_qa")
    if not folder.strip():
        raise ValueError("QA_WORKSPACE_DIR must not be empty")
    workspace_dir = (_REPO_ROOT / folder).resolve()
    # DEC-154: the Coder's tools must never reach the QA's tests (DEC-140).
    if workspace_dir.is_relative_to(coder_dir) or coder_dir.is_relative_to(workspace_dir):
        raise ValueError(
            f"QA_WORKSPACE_DIR {workspace_dir} must not overlap the Coder's "
            f"folder {coder_dir}"
        )

    model = env.get("QA_MODEL", DEFAULT_QA_MODEL)
    if not model.strip():
        raise ValueError("QA_MODEL must not be empty")

    severity = env.get("QA_BLOCKING_SEVERITY", "High")
    if severity not in get_args(Severity):
        raise ValueError(
            f"QA_BLOCKING_SEVERITY must be one of {', '.join(get_args(Severity))}, "
            f"got {severity!r}"
        )

    test_timeout = _int_setting(env, "QA_TEST_TIMEOUT", default=2, minimum=1)
    # DEC-152: a single test must time out before the whole run does.
    if test_timeout >= exec_timeout:
        raise ValueError(
            f"QA_TEST_TIMEOUT must be lower than EXEC_TIMEOUT ({exec_timeout}), "
            f"got {test_timeout}"
        )

    return QASettings(
        workspace_dir=workspace_dir,
        model=model,
        max_attempts=_int_setting(env, "QA_MAX_ATTEMPTS", default=2, minimum=1),
        blocking_severity=severity,
        test_timeout=test_timeout,
    )


QA_SETTINGS = load_qa_settings(os.environ, EXEC_TIMEOUT, handlers.CODER_WORKSPACE_DIR)


TESTS_SYSTEM_PROMPT = f"""You are the QA engineer of a software team. Write pytest tests that check
whether the code of one task meets each of its acceptance criteria.

Rules:
- Write at least one test for every criterion, and set criterion_index to the
  number of the criterion it checks.
- Each test's code is exactly one function named like the test, starting with
  test_. It is a plain synchronous function: no async, no fixtures from plugins.
- The preamble holds only imports and helper functions or classes; nothing
  else may run when the file is imported.
- Import the task's code by module name: a file linked_list.py is imported as
  `from linked_list import ...`. The tests run with the task's folder as the
  working directory and on the import path.
- You see only the interface of the code: signatures, types, decorators and
  docstrings, with bodies shown as `...`. Use it for names and how to call
  things. Take every expected value from the criteria, never from guesses
  about the implementation; if the code is wrong, your test must fail.
- Check behaviour with plain assert statements on observable results, as the
  criteria describe them. Do not test private details.
- Tests must be deterministic and fast: no network, no sleeping, no reading
  user input.
- {PYTHON_ENVIRONMENT}"""


class PytestCase(BaseModel):
    """One generated test (DEC-148).

    Attributes:
        criterion_index: Number of the acceptance criterion it checks,
            starting at 0.
        name: Name of the test function.
        code: Source of the test function.
    """
    criterion_index: int = Field(ge=0)
    name: NonEmptyStr
    code: NonEmptyStr


class PytestDraftBase(BaseModel):
    """A test file as written by the LLM, before the per-task checks.

    ``_pytest_draft_schema`` adds the checks of each task.

    Attributes:
        preamble: Imports and helpers placed before the tests.
        tests: The tests, at least one.
    """
    preamble: str = ""
    tests: list[PytestCase] = Field(min_length=1)

    def render(self) -> str:
        """Returns the test file's source.

        Returns:
            The preamble followed by each test, separated by blank lines.
        """
        parts = [self.preamble.strip()] if self.preamble.strip() else []
        parts += [test.code.strip() for test in self.tests]
        return "\n\n\n".join(parts) + "\n"


# DEC-152: the preamble may only define things, so importing the test file
# runs no code of the task.
_PREAMBLE_NODES = (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef)


def _parse(source: str, what: str) -> ast.Module:
    """Parses source without running it.

    Args:
        source: Python source.
        what: What the source is, for the error message.

    Returns:
        The parsed module.

    Raises:
        ValueError: If the source is not valid Python.
    """
    try:
        return ast.parse(source)
    except SyntaxError as e:
        raise ValueError(f"{what} is invalid Python: {e.msg} (line {e.lineno})") from None


def _pytest_draft_schema(criteria_count: int) -> type[PytestDraftBase]:
    """Returns a PytestDraft schema with the checks of one task (DEC-148).

    A failed check is a validation error, so the structured call sends it
    back to the model, as the PM does for coverage (DEC-091).

    Args:
        criteria_count: Number of acceptance criteria of the task.

    Returns:
        A subclass of ``PytestDraftBase`` with the checks, named ``PytestDraft``
        because the class name is the tool name the LLM sees.
    """

    class PytestDraft(PytestDraftBase):
        """Test draft that parses, runs nothing on import and covers every criterion."""

        @model_validator(mode="after")
        def _check(self) -> "PytestDraft":
            """Returns the draft if it passes every check.

            Returns:
                This draft.

            Raises:
                ValueError: If the preamble runs code, a test is not exactly
                    one function named like it, a name repeats or lacks the
                    ``test_`` prefix, a criterion index is unknown or a
                    criterion has no test.
            """
            for node in _parse(self.preamble, "the preamble").body:
                if not isinstance(node, _PREAMBLE_NODES):
                    raise ValueError(
                        f"the preamble may hold only imports, functions and classes; "
                        f"line {node.lineno} is a {type(node).__name__}"
                    )
            names: set[str] = set()
            for test in self.tests:
                if not test.name.startswith("test_"):
                    raise ValueError(f"test name {test.name!r} must start with 'test_'")
                if test.name in names:
                    raise ValueError(f"duplicate test name {test.name!r}")
                names.add(test.name)
                body = _parse(test.code, f"the code of {test.name}").body
                # DEC-157: one sync function, so nothing else runs on import.
                if (
                    len(body) != 1
                    or not isinstance(body[0], ast.FunctionDef)
                    or body[0].name != test.name
                ):
                    raise ValueError(
                        f"the code of {test.name} must be exactly one function named "
                        f"{test.name} (no async, nothing else; helpers go in the preamble)"
                    )
                if test.criterion_index >= criteria_count:
                    raise ValueError(
                        f"{test.name}: criterion_index {test.criterion_index} does not "
                        f"exist; use 0 to {criteria_count - 1}"
                    )
            covered = {test.criterion_index for test in self.tests}
            for index in range(criteria_count):
                if index not in covered:
                    raise ValueError(f"criterion {index} has no test")
            _parse(self.render(), "the assembled test file")
            return self

    return PytestDraft



class WrittenTests(BaseModel):
    """The test file the QA wrote for a task.

    Attributes:
        path: Absolute path of the test file.
        criteria: Test name to the index of the criterion it checks.
    """
    path: Path
    criteria: dict[str, int]


def _criterion_text(criterion: TaskCriterion) -> str:
    """Returns a criterion as one Given/When/Then sentence.

    Args:
        criterion: The criterion.

    Returns:
        ``"Given ..., When ..., Then ..."``.
    """
    return f"Given {criterion.given}, When {criterion.when}, Then {criterion.then}"


def _is_simple_literal(node: ast.expr) -> bool:
    """Returns whether a value is a short literal, safe to show (DEC-158).

    Args:
        node: The value's expression.

    Returns:
        True for a literal such as ``100``, ``"x"`` or ``(1, 2)`` whose
        source is at most 80 characters.
    """
    try:
        ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False
    return len(ast.unparse(node)) <= 80


def _skeleton_body(body: list[ast.stmt], in_class: bool) -> list[ast.stmt]:
    """Returns the interface statements of a module or class body (DEC-158).

    Args:
        body: Statements of the module or class.
        in_class: Whether the body is a class's; imports only count at
            module level.

    Returns:
        Docstring, imports, signatures with ``...`` bodies, typed fields
        and constants; every other statement is dropped.
    """
    kept: list[ast.stmt] = []
    for index, node in enumerate(body):
        if (
            index == 0
            and isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            kept.append(node)
        elif isinstance(node, (ast.Import, ast.ImportFrom)) and not in_class:
            kept.append(node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            docstring = ast.get_docstring(node, clean=False)
            node.body = [ast.Expr(ast.Constant(docstring))] if docstring is not None else []
            node.body.append(ast.Expr(ast.Constant(...)))
            kept.append(node)
        elif isinstance(node, ast.ClassDef):
            node.body = _skeleton_body(node.body, in_class=True) or [ast.Expr(ast.Constant(...))]
            kept.append(node)
        elif isinstance(node, ast.AnnAssign):
            if node.value is not None and not _is_simple_literal(node.value):
                node.value = ast.Constant(...)
            kept.append(node)
        elif isinstance(node, ast.Assign):
            if not _is_simple_literal(node.value):
                node.value = ast.Constant(...)
            kept.append(node)
    return kept


def _interface(name: str, source: str) -> str:
    """Returns the interface of a file: its code without bodies (DEC-158).

    Args:
        name: File name, for the message when it does not parse.
        source: The file's content.

    Returns:
        Python source with imports, signatures (types, defaults,
        decorators), typed fields, constants and docstrings; every body is
        ``...``. A file that does not parse gives a one-line comment saying
        so.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return f"# {name} could not be parsed: {e.msg} (line {e.lineno})"
    tree.body = _skeleton_body(tree.body, in_class=False)
    return ast.unparse(tree)


def _render_task(task: TaskSpec, sources: Mapping[str, str]) -> str:
    """Returns the task and its code's interface as the request for the test call.

    Args:
        task: The task to test.
        sources: File name to content, for the task's files.

    Returns:
        Title, description, numbered criteria and each file's interface
        (DEC-158).
    """
    criteria = "\n".join(
        f"{k}. {_criterion_text(c)}" for k, c in enumerate(task.acceptance_criteria)
    )
    files = "\n\n".join(
        f"### {name}\n```python\n{_interface(name, content)}\n```"
        for name, content in sources.items()
    ) or "(no file of the task could be read)"
    return (
        f"# Task {task.task_id}: {task.title}\n\n{task.description}\n\n"
        f"## Acceptance criteria\n{criteria}\n\n"
        f"## Code interface (bodies omitted)\n{files}"
    )


def write_tests(
    task: TaskSpec,
    sources: Mapping[str, str],
    model: BaseChatModel,
    settings: QASettings,
) -> WrittenTests:
    """Writes the pytest file of a task from a validated model draft.

    Args:
        task: The task to test.
        sources: File name to content, for the task's files; the model
            sees only their interface (DEC-158).
        model: Chat model for the QA.
        settings: The QA's settings; gives the folder and the attempts.

    Returns:
        The written file and the criterion each test checks.

    Raises:
        StructuredOutputError: If no draft is valid within
            ``settings.max_attempts`` model calls; nothing is written
            (DEC-141).
        Exception: Errors of the model call propagate.
    """
    schema = _pytest_draft_schema(len(task.acceptance_criteria))
    draft = structured_call(
        model,
        schema,
        TESTS_SYSTEM_PROMPT,
        _render_task(task, sources),
        max_attempts=settings.max_attempts,
    )
    folder = settings.workspace_dir / task.task_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"test_{task.task_id}.py"
    path.write_text(draft.render(), encoding="utf-8")
    return WrittenTests(
        path=path, criteria={test.name: test.criterion_index for test in draft.tests}
    )


def _tail(text: str, limit: int = 1500) -> str:
    """Returns the end of a long text.

    Args:
        text: The text.
        limit: Characters to keep.

    Returns:
        The text, or its last ``limit`` characters.
    """
    return text if len(text) <= limit else text[-limit:]


def _qa_failure(task: TaskSpec, step: str, description: str, severity: Severity) -> QAReport:
    """Returns an unapproved report for a QA that could not do its job (DEC-142).

    Args:
        task: The task reviewed.
        step: The step that failed, used as the issue's location.
        description: What went wrong.
        severity: The blocking threshold of the report.

    Returns:
        A report with one ``qa`` High issue.
    """
    issue = Issue(
        severity="High",
        location=step,
        description=description,
        fix="Nothing for the Coder: the QA could not check this task; run the QA again.",
        source="qa",
    )
    return QAReport(task_id=task.task_id, issues=[issue], blocking_severity=severity)


def _report_from_run(
    task: TaskSpec, written: WrittenTests, result: PytestResult, severity: Severity
) -> QAReport:
    """Returns the report of a test run (DEC-149).

    Each failed test is a ``test`` High issue tied to its criterion. A run
    that did not give test results is a ``qa`` High issue until the blame of
    DEC-152 arrives (Lab 3.2 T6).

    Args:
        task: The task reviewed.
        written: The test file and the criterion of each test.
        result: The pytest run.
        severity: The blocking threshold of the report.

    Returns:
        The report; ``approved`` is computed by ``QAReport``.
    """
    if result.status not in ("passed", "failed"):
        return _qa_failure(
            task,
            "test run",
            f"pytest could not run the tests ({result.status}): {_tail(result.output)}",
            severity,
        )
    issues = []
    for failure in result.failures:
        index = written.criteria.get(failure.name)
        criterion = (
            _criterion_text(task.acceptance_criteria[index]) if index is not None else ""
        )
        details = failure.details.strip().splitlines()
        description = failure.message.strip() or (details[-1] if details else "the test failed")
        issues.append(
            Issue(
                severity="High",
                location=f"{written.path.name}::{failure.name}",
                description=description,
                fix=f"Make {failure.name} pass; it failed with: {description}",
                source="test",
                criterion=criterion,
            )
        )
    return QAReport(
        task_id=task.task_id,
        issues=issues,
        tests_passed=result.passed,
        tests_failed=result.failed,
        blocking_severity=severity,
    )


async def run_qa(
    task: TaskSpec,
    model: BaseChatModel | None = None,
    settings: QASettings | None = None,
    coder_dir: Path | None = None,
    errlog: TextIO = sys.stderr,
) -> QAReport:
    """Reviews one task: reads its code, writes and runs its tests, reports.

    The steps are fixed (DEC-144). The task's files are read through the MCP
    server (DEC-140); the tests run in place against the Coder's folder,
    which is never changed (DEC-145). LLM calls run in a worker thread
    (DEC-150).

    Args:
        task: The task to review.
        model: Chat model; None builds ``settings.model``.
        settings: QA settings; None reads them from the environment now.
        coder_dir: The Coder's folder; None uses
            ``tools.handlers.CODER_WORKSPACE_DIR``.
        errlog: Where the MCP server's stderr goes; must be a real file.

    Returns:
        The report. Nothing is raised: a step that fails gives an
        unapproved report with a ``qa`` High issue naming the cause
        (DEC-142).
    """
    coder_dir = coder_dir or handlers.CODER_WORKSPACE_DIR
    severity: Severity = settings.blocking_severity if settings else "High"
    step = "settings"
    # DEC-142: every failure, expected or not, becomes a qa issue; the
    # traceback goes to the log so our own bugs stay visible.
    try:
        settings = settings or load_qa_settings(os.environ, EXEC_TIMEOUT, coder_dir)
        severity = settings.blocking_severity

        step = "MCP read"
        sources = await read_multiple_files(task.files, coder_dir, errlog)
        logger.info(
            "%s: read %d of %d task files through MCP: %s",
            task.task_id, len(sources), len(task.files), ", ".join(sources) or "none",
        )
        missing = [name for name in task.files if name not in sources]
        if missing:
            logger.warning("%s: files not readable: %s", task.task_id, ", ".join(missing))

        step = "test writing"
        model = model or get_chat_model(settings.model)
        written = await asyncio.to_thread(write_tests, task, sources, model, settings)
        logger.info("%s: wrote %s with %d tests", task.task_id, written.path, len(written.criteria))

        step = "test run"
        logger.info(
            "%s: running pytest on %s (test timeout %ds, run timeout %ds)",
            task.task_id, written.path.name, settings.test_timeout, EXEC_TIMEOUT,
        )
        result = await asyncio.to_thread(
            run_pytest, written.path, coder_dir, settings.test_timeout
        )
        logger.info(
            "%s: pytest %s: %d passed, %d failed",
            task.task_id, result.status, result.passed, result.failed,
        )
        report = _report_from_run(task, written, result, severity)
    except StructuredOutputError as e:
        logger.warning("%s: no valid test draft: %s", task.task_id, e)
        attempts = settings.max_attempts if settings else "?"
        report = _qa_failure(
            task, step, f"no runnable tests could be produced in {attempts} attempts: {e}", severity
        )
    except Exception as e:
        logger.exception("%s: QA step %r failed", task.task_id, step)
        report = _qa_failure(task, step, f"{type(e).__name__}: {e}", severity)

    logger.info(
        "%s: verdict %s, %d blocking issues",
        task.task_id,
        "approved" if report.approved else "not approved",
        len(report.blocking_issues()),
    )
    return report

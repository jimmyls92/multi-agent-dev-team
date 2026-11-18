"""QA & Debugger agent (Lab 3.2).

Reviews one task of the PM's handoff: it reads the Coder's files through the
MCP server, writes pytest tests for the task's acceptance criteria and
returns a ``QAReport`` (``orchestration.state``) whose verdict comes from
the executed tests (DEC-137, DEC-139).

Its settings come from environment variables and are checked when the
module is imported, so a wrong value stops the program at startup
(DEC-151). ``write_tests`` asks the model for a test draft, validates it
with a per-task schema and writes it to the QA's folder (DEC-148).

Attributes:
    DEFAULT_QA_MODEL: Small, fast model used when ``QA_MODEL`` is unset
        (C4.5, DEC-150).
    QA_SETTINGS: Settings read at import time from the environment.
    TESTS_SYSTEM_PROMPT: Instructions for writing the tests of a task.

Typical usage example:

    settings = load_qa_settings(os.environ, EXEC_TIMEOUT, CODER_WORKSPACE_DIR)
    print(settings.workspace_dir)
"""

import ast
import os
from collections.abc import Mapping
from pathlib import Path
from typing import get_args

from dotenv import load_dotenv
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, ConfigDict, Field, model_validator

from agents.llm_helpers import PYTHON_ENVIRONMENT, structured_call
from orchestration.state import NonEmptyStr, Severity, TaskSpec
from tools import handlers
from tools.code_executor import EXEC_TIMEOUT

load_dotenv()

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


def _render_task(task: TaskSpec, sources: Mapping[str, str]) -> str:
    """Returns the task and its code as the request for the test call.

    Args:
        task: The task to test.
        sources: File name to content, for the task's files.

    Returns:
        Title, description, numbered criteria and each file's content.
    """
    criteria = "\n".join(
        f"{k}. Given {c.given}, When {c.when}, Then {c.then}"
        for k, c in enumerate(task.acceptance_criteria)
    )
    files = "\n\n".join(
        f"### {name}\n```python\n{content}\n```" for name, content in sources.items()
    )
    return (
        f"# Task {task.task_id}: {task.title}\n\n{task.description}\n\n"
        f"## Acceptance criteria\n{criteria}\n\n## Code\n{files}"
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
        sources: File name to content, for the task's files.
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

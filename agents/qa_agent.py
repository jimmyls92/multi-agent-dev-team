"""QA & Debugger agent (Labs 3.2 and 3.3).

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
becomes a ``qa`` issue in an unapproved report (DEC-142). Each failure is
blamed on the file where it happens: the Coder's failures become issues,
the QA's own make it write a new draft within ``QA_MAX_ATTEMPTS`` model
calls (DEC-152, DEC-159). Only when a test failed, a second model call,
``review_code``, reads the whole code and writes the fix of each failing
test; it adds no issues and never decides approval (DEC-160, DEC-174).
Each failing test's issue carries the test's code (DEC-191).

Run as a module it is the demo: it reviews a bundled buggy linked list with
the real model and prints the report.

Attributes:
    DEFAULT_QA_MODEL: Small, fast model used when ``QA_MODEL`` is unset
        (C4.5, DEC-150).
    QA_SETTINGS: Settings read at import time from the environment.
    TESTS_SYSTEM_PROMPT: Instructions for writing the tests of a task.
    REVIEW_SYSTEM_PROMPT: Instructions for writing the fix of each failing test.

Typical usage example:

    report = await run_qa(task)
    print(report.approved, report.issues)

    python -m agents.qa_agent
"""

import ast
import asyncio
import builtins
import importlib.machinery
import logging
import os
import re
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, NamedTuple, TextIO

from dotenv import load_dotenv
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, ConfigDict, Field, model_validator

from agents.llm_helpers import PYTHON_ENVIRONMENT, StructuredOutputError, structured_call
from llm_client import get_chat_model
from orchestration.settings import int_setting
from orchestration.state import (
    Issue,
    NonEmptyStr,
    QAReport,
    TaskCriterion,
    TaskSpec,
)
from tools import code_executor, handlers
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
        test_timeout: Seconds each test may run (DEC-152).
    """
    model_config = ConfigDict(frozen=True)

    workspace_dir: Path
    model: str
    max_attempts: int
    test_timeout: int


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

    # DEC-174, DEC-191: the threshold is gone; a leftover value only warns.
    if "QA_BLOCKING_SEVERITY" in env:
        logger.warning(
            "QA_BLOCKING_SEVERITY is no longer used: every QA issue comes from an "
            "executed test and blocks approval (DEC-174); remove it from .env"
        )

    test_timeout = int_setting(env, "QA_TEST_TIMEOUT", default=2, minimum=1)
    # DEC-152: a single test must time out before the whole run does.
    if test_timeout >= exec_timeout:
        raise ValueError(
            f"QA_TEST_TIMEOUT must be lower than EXEC_TIMEOUT ({exec_timeout}), "
            f"got {test_timeout}"
        )

    return QASettings(
        workspace_dir=workspace_dir,
        model=model,
        max_attempts=int_setting(env, "QA_MAX_ATTEMPTS", default=2, minimum=1),
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


Owner = Literal["coder", "qa"]


class _ImportContext(NamedTuple):
    """What a test draft may import for one task (DEC-152).

    Attributes:
        modules: Module name to task file, for the task's Python files.
        defined: Module name to the names its file defines at top level,
            for the files the QA read; None when they cannot be known (the
            file does not parse or uses ``import *``).
        task_text: Title, description and criteria, to tell the names the
            task asks for.
        rejected: Task file to the MCP server's reason, for the files it
            refused to read.
    """
    modules: dict[str, str]
    defined: dict[str, frozenset[str] | None]
    task_text: str
    rejected: Mapping[str, str]


class _ImportProblem(NamedTuple):
    """One import of a draft that would fail, with its owner (DEC-152).

    Attributes:
        owner: ``coder`` when the Coder did not provide what the task asks
            for; ``qa`` when the draft asks for something that does not
            exist.
        file: The task file concerned; empty when none.
        message: What is wrong.
        fix: What the Coder must do; empty for the QA's problems.
    """
    owner: Owner
    file: str
    message: str
    fix: str = ""


def _defined_names(source: str) -> frozenset[str] | None:
    """Returns the names a module defines at top level.

    Looks into ``if``, ``try``, ``with`` and loop blocks, never into
    functions or classes.

    Args:
        source: The module's source.

    Returns:
        Functions, classes, assigned variables and imported names; None if
        the source does not parse or uses ``import *``.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    names: set[str] = set()

    def visit(body: list[ast.stmt]) -> bool:
        """Adds the names of a block; returns False on ``import *``.

        Args:
            body: Statements of the block.

        Returns:
            Whether every name could be known.
        """
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                names.update(n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name))
            elif isinstance(node, ast.Import):
                names.update(a.asname or a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                if any(a.name == "*" for a in node.names):
                    return False
                names.update(a.asname or a.name for a in node.names)
            else:
                blocks = [getattr(node, f, []) for f in ("body", "orelse", "finalbody")]
                blocks += [h.body for h in getattr(node, "handlers", [])]
                if not all(visit(b) for b in blocks if isinstance(b, list)):
                    return False
        return True

    return frozenset(names) if visit(tree.body) else None


def _import_context(
    task: TaskSpec, sources: Mapping[str, str], rejected: Mapping[str, str]
) -> _ImportContext:
    """Returns what a draft for the task may import.

    Args:
        task: The task to test.
        sources: File name to content, for the task files the QA read.
        rejected: File name to the server's reason, for the files it
            refused.

    Returns:
        The task's modules, the names each read file defines and the
        task's text.
    """
    modules = {
        name.removesuffix(".py").replace("/", "."): name
        for name in task.files
        if name.endswith(".py")
    }
    defined = {
        module: _defined_names(sources[name]) for module, name in modules.items() if name in sources
    }
    text = " ".join(
        [task.title, task.description] + [_criterion_text(c) for c in task.acceptance_criteria]
    )
    return _ImportContext(modules, defined, text, rejected)


def _is_installed(top_module: str) -> bool:
    """Returns whether a top-level module can be imported by the tests.

    The tests run with only the Coder's folder on the path, so this
    project's own folder does not count.

    Args:
        top_module: First part of a module name, e.g. ``pytest``.

    Returns:
        True for standard-library and installed modules.
    """
    if top_module in sys.stdlib_module_names or top_module in sys.builtin_module_names:
        return True
    paths = [entry for entry in sys.path if entry and Path(entry).resolve() != _REPO_ROOT]
    return importlib.machinery.PathFinder.find_spec(top_module, paths) is not None


def _module_problems(module: str, imports: _ImportContext) -> list[_ImportProblem]:
    """Returns the problem of importing one module, if any (DEC-152).

    Args:
        module: Full module name.
        imports: What the draft may import.

    Returns:
        A ``coder`` problem for a task file the Coder never created or the
        server could not read (with its reason), a ``qa`` problem for a
        module that is neither a task module nor installed, or nothing.
    """
    if module in imports.modules:
        if module in imports.defined:
            return []
        file = imports.modules[module]
        if file in imports.rejected and imports.rejected[file] != "no such file":
            return [_ImportProblem(
                "coder", file, f"{file} could not be read: {imports.rejected[file]}",
                f"Make {file} a readable UTF-8 Python file as the task describes.",
            )]
        return [_ImportProblem(
            "coder", file, f"{file} was not found in the Coder's folder",
            f"Create {file} as the task describes.",
        )]
    if any(task_module.startswith(module + ".") for task_module in imports.modules):
        return []
    if _is_installed(module.split(".")[0]):
        return []
    known = ", ".join(imports.modules) or "none"
    return [_ImportProblem(
        "qa", "", f"{module} is neither a task module ({known}) nor an installed package"
    )]


def _import_problems(tree: ast.Module, imports: _ImportContext) -> list[_ImportProblem]:
    """Returns the imports of a draft that would fail, each with its owner (DEC-152).

    A missing task file, or a missing name the task mentions, is the
    Coder's; anything else that does not exist is the QA's.

    Args:
        tree: The parsed test file.
        imports: What the draft may import.

    Returns:
        The problems, without repeats, in source order.
    """
    problems: list[_ImportProblem] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                problems += _module_problems(alias.name, imports)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                problems.append(_ImportProblem(
                    "qa", "", "relative imports are not allowed; import task modules by name"
                ))
                continue
            found = _module_problems(node.module, imports)
            problems += found
            names = imports.defined.get(node.module)
            if found or names is None:
                continue
            file = imports.modules[node.module]
            for alias in node.names:
                if alias.name in names:
                    continue
                if re.search(rf"\b{re.escape(alias.name)}\b", imports.task_text):
                    problems.append(_ImportProblem(
                        "coder", file, f"{file} does not define {alias.name}, which the task names",
                        f"Define {alias.name} in {file} as the task describes.",
                    ))
                else:
                    available = ", ".join(sorted(names)) or "nothing"
                    problems.append(_ImportProblem(
                        "qa", "", f"{file} does not define {alias.name}; it defines: {available}"
                    ))
    return list(dict.fromkeys(problems))


_MODULE_GLOBALS = frozenset({"__name__", "__file__", "__doc__"})

# DEC-141: a skipped or xfailed test counts as neither passed nor failed,
# so it could let a criterion through unverified.
_SKIP_NAMES = frozenset({"skip", "skipif", "xfail", "importorskip"})


def _skip_uses(tree: ast.Module) -> list[str]:
    """Returns the ways a test file skips or xfails tests.

    Args:
        tree: The parsed test file.

    Returns:
        The names found, e.g. ``["xfail"]``, sorted and without repeats.
    """
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in _SKIP_NAMES:
            found.add(node.attr)
        elif isinstance(node, ast.Name) and node.id in _SKIP_NAMES:
            found.add(node.id)
        elif isinstance(node, ast.alias) and node.name.split(".")[-1] in _SKIP_NAMES:
            found.add(node.name.split(".")[-1])
    return sorted(found)


def _undefined_names(tree: ast.Module) -> list[str]:
    """Returns the names a test file uses but never imports or defines (DEC-152).

    Scopes are not tracked: a name assigned or imported anywhere counts as
    defined. That still catches the usual mistake, a class used without its
    import, which would fail inside the test and be blamed on the Coder.

    Args:
        tree: The parsed test file.

    Returns:
        The undefined names, sorted; empty when the file uses ``import *``.
    """
    defined = set(dir(builtins)) | _MODULE_GLOBALS
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
            defined.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.arg):
            defined.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            defined.add(node.name)
        elif isinstance(node, ast.Import):
            defined.update(a.asname or a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if any(a.name == "*" for a in node.names):
                return []
            defined.update(a.asname or a.name for a in node.names)
    used = {
        node.id for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    return sorted(used - defined)


def _pytest_draft_schema(
    criteria_count: int, imports: _ImportContext
) -> type[PytestDraftBase]:
    """Returns a PytestDraft schema with the checks of one task (DEC-148).

    A failed check is a validation error, so the model is told what to
    correct (DEC-091, DEC-159).

    Args:
        criteria_count: Number of acceptance criteria of the task.
        imports: What the draft may import; the QA's import mistakes are
            rejected here, the Coder's are left for ``run_qa`` (DEC-152).

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
                    ``test_`` prefix, a criterion index is unknown, a
                    criterion has no test, an import is the QA's mistake, a
                    name is used without being imported or defined, or a
                    test is skipped or xfailed.
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
            tree = _parse(self.render(), "the assembled test file")
            mistakes = [p.message for p in _import_problems(tree, imports) if p.owner == "qa"]
            if mistakes:
                raise ValueError("bad imports: " + "; ".join(mistakes))
            skips = _skip_uses(tree)
            if skips:
                raise ValueError(
                    f"tests must not skip or xfail (found {', '.join(skips)}); every "
                    f"test must run and assert"
                )
            undefined = _undefined_names(tree)
            if undefined:
                raise ValueError(
                    f"names used but never imported or defined: {', '.join(undefined)}; "
                    f"import them in the preamble"
                )
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


def _test_code(path: Path, name: str) -> str:
    """Returns a test function of the QA's test file as written (DEC-191).

    Args:
        path: The test file.
        name: The test's name, without a parametrized ``[case]`` suffix.

    Returns:
        The function's lines, decorators included; empty if the file
        cannot be read or has no such function.
    """
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError, UnicodeDecodeError):
        return ""
    lines = source.splitlines(keepends=True)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            start = min([node.lineno] + [d.lineno for d in node.decorator_list])
            return "".join(lines[start - 1 : node.end_lineno])
    return ""


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


def _render_task(
    task: TaskSpec, sources: Mapping[str, str], rejected: Mapping[str, str]
) -> str:
    """Returns the task and its code's interface as the request for the test call.

    Args:
        task: The task to test.
        sources: File name to content, for the task's files.
        rejected: File name to the server's reason, for the files it
            refused.

    Returns:
        Title, description, numbered criteria and each file's interface
        (DEC-158).
    """
    criteria = "\n".join(
        f"{k}. {_criterion_text(c)}" for k, c in enumerate(task.acceptance_criteria)
    )
    files = [
        f"### {name}\n```python\n{_interface(name, content)}\n```"
        for name, content in sources.items()
    ] + [f"### {name}\n(could not be read: {reason})" for name, reason in rejected.items()]
    return (
        f"# Task {task.task_id}: {task.title}\n\n{task.description}\n\n"
        f"## Acceptance criteria\n{criteria}\n\n"
        f"## Code interface (bodies omitted)\n"
        + ("\n\n".join(files) or "(no file of the task could be read)")
    )


def write_tests(
    task: TaskSpec,
    sources: Mapping[str, str],
    model: BaseChatModel,
    settings: QASettings,
    feedback: str = "",
    rejected: Mapping[str, str] | None = None,
) -> WrittenTests:
    """Writes the pytest file of a task from one validated model draft.

    Makes exactly one model call; ``run_qa`` decides whether to try again
    (DEC-159).

    Args:
        task: The task to test.
        sources: File name to content, for the task's files; the model
            sees only their interface (DEC-158).
        model: Chat model for the QA.
        settings: The QA's settings; gives the folder.
        feedback: Why the previous draft could not be used, with its file
            when there is one; empty for the first draft.
        rejected: File name to the server's reason, for the task files it
            refused; None when none.

    Returns:
        The written file and the criterion each test checks.

    Raises:
        StructuredOutputError: If the draft is invalid; nothing is written.
        Exception: Errors of the model call propagate.
    """
    rejected = rejected or {}
    schema = _pytest_draft_schema(
        len(task.acceptance_criteria), _import_context(task, sources, rejected)
    )
    request = _render_task(task, sources, rejected)
    if feedback:
        request += f"\n\n## Your previous draft could not be used\n{feedback}"
    draft = structured_call(model, schema, TESTS_SYSTEM_PROMPT, request, max_attempts=1)
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


def _qa_failure(task: TaskSpec, step: str, description: str) -> QAReport:
    """Returns an unapproved report for a QA that could not do its job (DEC-142).

    Args:
        task: The task reviewed.
        step: The step that failed, used as the issue's location.
        description: What went wrong.

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
    return QAReport(task_id=task.task_id, issues=[issue])


_FRAME = re.compile(r"^\s*(?P<path>\S+?\.py):(?P<line>\d+):", re.MULTILINE)


class _Blame(NamedTuple):
    """Where a failure happened (DEC-152).

    Attributes:
        owner: ``coder`` for a file in the Coder's folder, ``qa`` otherwise.
        file: The file, relative to its folder; empty when no frame was in
            either folder.
        line: Line in that file; 0 when unknown.
    """
    owner: Owner
    file: str
    line: int


def _blame(traceback: str, coder_dir: Path, qa_dir: Path) -> _Blame:
    """Returns the owner of the deepest traceback frame in either folder (DEC-152).

    pytest prints each frame as ``path.py:line: ...``, relative to its
    working directory, which is the Coder's folder.

    Args:
        traceback: pytest's text for the failure.
        coder_dir: The Coder's folder.
        qa_dir: The folder of the task's test file.

    Returns:
        The blame; the QA's, with no file, when no frame is in either
        folder.
    """
    blame = _Blame("qa", "", 0)
    for match in _FRAME.finditer(traceback):
        path = (coder_dir / match["path"]).resolve()
        line = int(match["line"])
        if path.is_relative_to(coder_dir):
            blame = _Blame("coder", path.relative_to(coder_dir).as_posix(), line)
        elif path.is_relative_to(qa_dir):
            blame = _Blame("qa", path.name, line)
    return blame


def _error_line(output: str) -> str:
    """Returns the last ``E`` line of pytest's output: the error itself.

    Args:
        output: pytest's output.

    Returns:
        The line without its ``E`` marker, e.g. ``RuntimeError: boom``;
        empty when there is none.
    """
    lines = [line[1:].strip() for line in output.splitlines() if line.startswith("E ")]
    return lines[-1] if lines else ""


def _coder_report(task: TaskSpec, issues: list[Issue], result: PytestResult | None = None) -> QAReport:
    """Returns the report of a run whose failures are the Coder's.

    Args:
        task: The task reviewed.
        issues: The Coder's issues.
        result: The pytest run, for its counts; None when pytest did not run.

    Returns:
        The report; ``approved`` is computed by ``QAReport``.
    """
    return QAReport(
        task_id=task.task_id,
        issues=issues,
        tests_passed=result.passed if result else 0,
        tests_failed=result.failed if result else 0,
    )


def _judge_run(
    task: TaskSpec,
    written: WrittenTests,
    result: PytestResult,
    settings: QASettings,
    coder_dir: Path,
) -> QAReport | str:
    """Returns the report of a test run, or why the draft is the QA's fault.

    Each failure is blamed on the file where it happened (DEC-152). The
    Coder's failures are ``test`` High issues tied to their criterion
    (DEC-149). A whole run that times out is the Coder's, since the test
    file runs nothing at import (DEC-157). An unusable run is a ``qa``
    issue (DEC-156).

    Args:
        task: The task reviewed.
        written: The test file and the criterion of each test.
        result: The pytest run.
        settings: QA settings; gives the test timeout.
        coder_dir: The Coder's folder.

    Returns:
        The report, or the error to send back to the model when the QA's
        own tests broke (a collection error or a timeout in its code).
    """
    qa_dir = written.path.parent
    if result.status == "error":
        return _qa_failure(
            task, "test run", f"pytest could not run the tests: {_tail(result.output)}"
        )
    if result.status == "timed_out":
        files = ", ".join(task.files)
        # DEC-152, DEC-161: every test has its own timeout inside this bound,
        # so the run's own limit is hit by an import that hangs.
        issue = Issue(
            severity="High",
            location=files,
            description=f"the whole test run timed out: {result.output.splitlines()[0]} "
            f"Importing the task's code or a test hangs; no test result is available.",
            fix=f"Make sure importing {files} runs no endless loop or blocking call, "
            f"and that no function waits forever.",
            source="test",
        )
        return _coder_report(task, [issue])
    if result.status == "collection_error":
        blame = _blame(result.output, coder_dir, qa_dir)
        if blame.owner == "qa":
            return f"pytest could not collect your tests:\n{_tail(result.output)}"
        error = _error_line(result.output) or _tail(result.output, 300)
        issue = Issue(
            severity="High",
            location=f"{blame.file}:{blame.line}",
            description=f"{error} (raised while importing {blame.file}, line {blame.line})",
            fix=f"Fix {blame.file} so it can be imported; it raised: {error}",
            source="test",
        )
        return _coder_report(task, [issue])

    if result.skipped:
        return (
            f"tests {', '.join(result.skipped)} were skipped; tests must not skip or "
            f"xfail: every test must run and assert"
        )
    issues = []
    for failure in result.failures:
        if failure.timed_out:
            blame = _blame(failure.details, coder_dir, qa_dir)
            if blame.owner == "qa":
                return (
                    f"{failure.name} timed out after {settings.test_timeout}s in the test's "
                    f"own code (line {blame.line}); tests must be fast and must not wait "
                    f"or loop forever."
                )
            description = (
                f"{failure.name} timed out after {settings.test_timeout}s in "
                f"{blame.file} (line {blame.line})"
            )
        else:
            details = failure.details.strip().splitlines()
            description = failure.message.strip() or (details[-1] if details else "the test failed")
        # A parametrized test is reported as name[case].
        test_name = failure.name.split("[")[0]
        index = written.criteria.get(test_name)
        issues.append(
            Issue(
                severity="High",
                location=f"{written.path.name}::{failure.name}",
                description=description,
                fix=f"Make {failure.name} pass; it failed with: {description.splitlines()[0]}",
                source="test",
                criterion=_criterion_text(task.acceptance_criteria[index]) if index is not None else "",
                test_code=_test_code(written.path, test_name),
            )
        )
    return _coder_report(task, issues, result)


def _test_task(
    task: TaskSpec,
    sources: Mapping[str, str],
    rejected: Mapping[str, str],
    model: BaseChatModel,
    settings: QASettings,
    coder_dir: Path,
) -> tuple[QAReport, str]:
    """Writes and runs the task's tests, drafting again on the QA's own failures.

    Each draft is one model call, and at most ``settings.max_attempts``
    are made (DEC-141, DEC-159). A draft that imports a task file or name
    the Coder did not provide is not run: those are the Coder's issues
    (DEC-152).

    Args:
        task: The task to test.
        sources: File name to content, for the task files read.
        rejected: File name to the server's reason, for the files it
            refused.
        model: Chat model for the QA.
        settings: QA settings.
        coder_dir: The Coder's folder.

    Returns:
        The report of the first usable draft and that draft's source; or an
        unapproved report with a ``qa`` issue and an empty source when no
        draft was usable.
    """
    imports = _import_context(task, sources, rejected)
    feedback = ""
    for attempt in range(1, settings.max_attempts + 1):
        try:
            written = write_tests(task, sources, model, settings, feedback, rejected)
        except StructuredOutputError as e:
            logger.warning("%s: draft %d rejected: %s", task.task_id, attempt, e)
            feedback = f"It was rejected: {e}"
            continue
        logger.info("%s: wrote %s with %d tests", task.task_id, written.path, len(written.criteria))
        source = written.path.read_text(encoding="utf-8")

        missing = [p for p in _import_problems(ast.parse(source), imports) if p.owner == "coder"]
        if missing:
            logger.info(
                "%s: not running pytest; the Coder did not provide: %s",
                task.task_id, "; ".join(p.message for p in missing),
            )
            issues = [
                Issue(severity="High", location=p.file, description=p.message, fix=p.fix, source="test")
                for p in missing
            ]
            return _coder_report(task, issues), source

        # DEC-161: room for every test's own timeout, so one hang per test
        # never kills the run; the sandbox caps it at MAX_TIMEOUT.
        run_timeout = code_executor.EXEC_TIMEOUT + len(written.criteria) * settings.test_timeout
        result = run_pytest(written.path, coder_dir, settings.test_timeout, run_timeout)
        logger.info(
            "%s: pytest command (test timeout %ds, run timeout %ds, at most %ds): %s",
            task.task_id, settings.test_timeout, run_timeout, code_executor.MAX_TIMEOUT,
            " ".join(result.command),
        )
        logger.info(
            "%s: pytest %s: %d passed, %d failed",
            task.task_id, result.status, result.passed, result.failed,
        )
        judged = _judge_run(task, written, result, settings, coder_dir)
        if isinstance(judged, QAReport):
            return judged, source
        logger.warning("%s: draft %d broke by the QA's fault: %s", task.task_id, attempt, judged)
        feedback = f"```python\n{source}```\n{judged}"
    return _qa_failure(
        task,
        "test writing",
        f"no runnable tests could be produced in {settings.max_attempts} attempts; "
        f"last error: {_tail(feedback, 500)}",
    ), ""


REVIEW_SYSTEM_PROMPT = """You are a senior code reviewer in a software team. You get one task, its
acceptance criteria, the whole code, the pytest tests the QA ran and the
failures they found.

Rules:
- In fixes, give one entry per failure listed, with failure set to the
  failure's number in the list. The fix tells the developer what to change
  in which function so the test passes, based on the criterion and the
  code. No fix for anything not listed.
- Give only fixes: never report other problems of the code."""


class FailureFix(BaseModel):
    """The review's fix for one failure of the report (DEC-160).

    Attributes:
        failure: Number of the failure in the request's list, starting at 0.
        fix: What the Coder must change.
    """
    failure: int = Field(ge=0)
    fix: NonEmptyStr


class CodeReviewBase(BaseModel):
    """A code review as written by the LLM, before the per-report checks.

    Only fixes are allowed: any other field, such as issues of its own, is
    rejected (DEC-174).

    Attributes:
        fixes: One fix per failure of the report.
    """
    model_config = ConfigDict(extra="forbid")

    fixes: list[FailureFix] = Field(default_factory=list)


def _code_review_schema(failure_count: int) -> type[CodeReviewBase]:
    """Returns a CodeReview schema that needs one fix per failure (DEC-160).

    Failures are numbered, like the criteria of the tests (DEC-148): models
    copy a number more reliably than a location string.

    Args:
        failure_count: Number of the report's ``test`` issues.

    Returns:
        A subclass of ``CodeReviewBase`` named ``CodeReview``, the tool name
        the LLM sees.
    """

    class CodeReview(CodeReviewBase):
        """Review with exactly one fix per listed failure."""

        @model_validator(mode="after")
        def _check_fixes(self) -> "CodeReview":
            """Returns the review if its fixes match the failures.

            Returns:
                This review.

            Raises:
                ValueError: If a fix is repeated, names an unknown failure
                    or a failure has no fix.
            """
            given = [fix.failure for fix in self.fixes]
            for index in given:
                if given.count(index) > 1:
                    raise ValueError(f"more than one fix for failure {index}")
                if index >= failure_count:
                    known = f"0 to {failure_count - 1}" if failure_count else "none; leave fixes empty"
                    raise ValueError(f"failure {index} does not exist; failures: {known}")
            for index in range(failure_count):
                if index not in given:
                    raise ValueError(f"no fix for failure {index}")
            return self

    return CodeReview


def _render_review(
    task: TaskSpec, sources: Mapping[str, str], tests: str, failures: list[Issue]
) -> str:
    """Returns the request of the review call.

    Args:
        task: The task reviewed.
        sources: File name to content; the review sees the whole code.
        tests: Source of the test file run.
        failures: The report's ``test`` issues.

    Returns:
        Task, criteria, code, tests and failures, in Markdown.
    """
    criteria = "\n".join(
        f"{k}. {_criterion_text(c)}" for k, c in enumerate(task.acceptance_criteria)
    )
    files = "\n\n".join(
        f"### {name}\n```python\n{content}\n```" for name, content in sources.items()
    ) or "(no file of the task could be read)"
    listed = "\n".join(
        f"{k}. {issue.location}: {issue.description}" for k, issue in enumerate(failures)
    ) or "None: every test passed."
    return (
        f"# Task {task.task_id}: {task.title}\n\n{task.description}\n\n"
        f"## Acceptance criteria\n{criteria}\n\n## Code\n{files}\n\n"
        f"## Tests run\n```python\n{tests}\n```\n\n## Failures\n{listed}"
    )


def _rebuilt(report: QAReport, issues: list[Issue], notes: list[str]) -> QAReport:
    """Returns the report with new issues and notes, approval recomputed.

    Args:
        report: The report to change.
        issues: The new issues.
        notes: The new notes.

    Returns:
        A new validated report.
    """
    data = report.model_dump(exclude={"approved", "issues", "notes"})
    return QAReport(**data, issues=issues, notes=notes)


def review_code(
    task: TaskSpec,
    sources: Mapping[str, str],
    tests: str,
    report: QAReport,
    model: BaseChatModel,
    settings: QASettings,
) -> QAReport:
    """Gives each failing test of a report a fix that says where to change the code (DEC-160, DEC-174).

    The review sees the whole code. Its fix for each ``test`` issue
    replaces the default one; it never adds issues, and approval stays
    with the tests (DEC-139).

    Args:
        task: The task reviewed.
        sources: File name to content, for the task files read.
        tests: Source of the test file run.
        report: The report from the tests, with at least one ``test`` issue.
        model: Chat model for the QA.
        settings: QA settings; gives the review's attempts.

    Returns:
        The report with the review's fixes. If the review fails, the report
        unchanged with the note "review unavailable" (DEC-142). Nothing is
        raised.
    """
    failures = [issue for issue in report.issues if issue.source == "test"]
    schema = _code_review_schema(len(failures))
    try:
        review = structured_call(
            model,
            schema,
            REVIEW_SYSTEM_PROMPT,
            _render_review(task, sources, tests, failures),
            max_attempts=settings.max_attempts,
        )
    except Exception as e:
        logger.warning("%s: review unavailable: %s: %s", task.task_id, type(e).__name__, e)
        return _rebuilt(report, list(report.issues), report.notes + ["review unavailable"])

    fixes = {fix.failure: fix.fix for fix in review.fixes}
    issues = []
    number = 0
    for issue in report.issues:
        if issue.source == "test":
            issue = issue.model_copy(update={"fix": fixes[number]})
            number += 1
        issues.append(issue)
    logger.info("%s: review gave %d fixes", task.task_id, len(review.fixes))
    return _rebuilt(report, issues, report.notes)


async def run_qa(
    task: TaskSpec,
    model: BaseChatModel | None = None,
    settings: QASettings | None = None,
    coder_dir: Path | None = None,
    errlog: TextIO | None = None,
) -> QAReport:
    """Reviews one task: reads its code, writes and runs its tests, reports.

    The steps are fixed (DEC-144). The task's files are read through the MCP
    server (DEC-140); the tests run in place against the Coder's folder,
    which is never changed (DEC-145). Model calls and pytest run in a
    worker thread (DEC-150).

    Args:
        task: The task to review.
        model: Chat model; None builds ``settings.model``.
        settings: QA settings; None reads them from the environment now.
        coder_dir: The Coder's folder; None uses
            ``tools.handlers.CODER_WORKSPACE_DIR``.
        errlog: Where the MCP server's stderr goes; must be a real file.
            None uses ``sys.stderr`` as it is when the QA runs.

    Returns:
        The report. Nothing is raised: a step that fails gives an
        unapproved report with a ``qa`` High issue naming the cause
        (DEC-142).
    """
    coder_dir = coder_dir or handlers.CODER_WORKSPACE_DIR
    step = "settings"
    # DEC-142: every failure, expected or not, becomes a qa issue; the
    # traceback goes to the log so our own bugs stay visible.
    try:
        settings = settings or load_qa_settings(os.environ, code_executor.EXEC_TIMEOUT, coder_dir)

        step = "MCP read"
        files = await read_multiple_files(task.files, coder_dir, errlog or sys.stderr)
        sources = files.contents
        logger.info(
            "%s: read %d of %d task files through MCP: %s",
            task.task_id, len(sources), len(task.files), ", ".join(sources) or "none",
        )
        for name, reason in files.rejected.items():
            logger.warning("%s: %s not readable: %s", task.task_id, name, reason)

        step = "test writing"
        model = model or get_chat_model(settings.model)
        report, tests = await asyncio.to_thread(
            _test_task, task, sources, files.rejected, model, settings, coder_dir
        )

        # DEC-174: the review only explains failing tests; a qa failure or
        # an approved run makes no review call.
        if any(issue.source == "test" for issue in report.issues):
            step = "review"
            report = await asyncio.to_thread(
                review_code, task, sources, tests, report, model, settings
            )
    except Exception as e:
        logger.exception("%s: QA step %r failed", task.task_id, step)
        report = _qa_failure(task, step, f"{type(e).__name__}: {e}")

    logger.info(
        "%s: verdict %s, %d blocking issues",
        task.task_id,
        "approved" if report.approved else "not approved",
        len(report.issues),
    )
    return report


# The demo: the Module 3 linked list, with a bug in reverse (it empties the
# list instead of reversing it).
_DEMO_CODE = """class Node:
    def __init__(self, value):
        self.value = value
        self.next = None


class LinkedList:
    def __init__(self):
        self.head = None

    def insert(self, value):
        node = Node(value)
        node.next = self.head
        self.head = node

    def delete(self, value):
        previous, current = None, self.head
        while current:
            if current.value == value:
                if previous:
                    previous.next = current.next
                else:
                    self.head = current.next
                return True
            previous, current = current, current.next
        return False

    def search(self, value):
        current = self.head
        while current:
            if current.value == value:
                return True
            current = current.next
        return False

    def reverse(self):
        previous, current = None, self.head
        while current:
            following = current.next
            current.next = previous
            previous = current
            current = following
        self.head = current

    def to_list(self):
        values, current = [], self.head
        while current:
            values.append(current.value)
            current = current.next
        return values
"""

_DEMO_TASK = TaskSpec(
    task_id="task_1",
    title="Implement a linked list",
    description=(
        "Create linked_list.py with a LinkedList class: insert(value) adds at the "
        "head, delete(value) removes the first occurrence and returns whether it was "
        "found, search(value) returns whether the value is present, reverse() reverses "
        "the list in place and to_list() returns the values from head to tail."
    ),
    acceptance_criteria=[
        TaskCriterion(given="an empty list", when="insert(1) then insert(2)", then="to_list() is [2, 1]"),
        TaskCriterion(
            given="a list built with insert(1), insert(2), insert(3)",
            when="delete(2)",
            then="it returns True and to_list() is [3, 1]",
        ),
        TaskCriterion(
            given="a list built with insert(5)",
            when="search(5) and search(7)",
            then="they return True and False",
        ),
        TaskCriterion(
            given="a list built with insert(1), insert(2), insert(3)",
            when="reverse()",
            then="to_list() is [1, 2, 3]",
        ),
    ],
    covers=["REQ-1"],
    files=["linked_list.py"],
    priority=1,
)


def _print_report(report: QAReport) -> None:
    """Prints a QA report for people.

    Args:
        report: The report.
    """
    verdict = "APPROVED" if report.approved else "NOT APPROVED"
    print(f"\nQA verdict for {report.task_id}: {verdict}")
    print(f"Tests: {report.tests_passed} passed, {report.tests_failed} failed")
    print(f"Issues ({len(report.issues)}):")
    for issue in report.issues:
        print(f"  [{issue.severity}] {issue.source}: {issue.location}")
        if issue.criterion:
            print(f"      criterion: {issue.criterion}")
        print(f"      problem:   {issue.description}")
        print(f"      fix:       {issue.fix}")
    for note in report.notes:
        print(f"Note: {note}")


def main() -> int:
    """Runs the demo: the QA reviews a buggy linked list with the real model.

    The code goes to a temporary Coder folder; the tests go to the QA's
    folder (``QA_WORKSPACE_DIR``). The QA's steps are logged to stderr.

    Returns:
        The exit code: 0 once the report is printed.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    with tempfile.TemporaryDirectory() as folder:
        coder_dir = Path(folder).resolve()
        (coder_dir / "linked_list.py").write_text(_DEMO_CODE, encoding="utf-8")
        report = asyncio.run(run_qa(_DEMO_TASK, coder_dir=coder_dir))
    _print_report(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())

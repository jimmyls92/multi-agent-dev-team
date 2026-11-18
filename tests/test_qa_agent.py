"""Tests of the QA agent (Lab 3.2).

Covers spec `lab_3_2_qa_agent` AC-3.2-12 .. AC-3.2-26 and AC-3.2-28 ..
AC-3.2-31 (DEC-139, DEC-141, DEC-142, DEC-145, DEC-148, DEC-149, DEC-152,
DEC-157 .. DEC-161), with a
fake model, the linked-list task and, for ``run_qa``, the real MCP server
over stdio and the real pytest sandbox. AC-3.2-26 uses the real model.

Tests that script no review reply leave the review without answers, so it
is unavailable; they count only the test-writing calls.
"""

import ast
import copy
import logging
import time
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from mcp import StdioServerParameters

import tools.code_executor
import tools.mcp_client
from agents.llm_helpers import StructuredOutputError
from agents.qa_agent import (
    DEFAULT_QA_MODEL,
    TESTS_SYSTEM_PROMPT,
    QASettings,
    WrittenTests,
    _judge_run,
    run_qa,
    write_tests,
)
from orchestration.state import QAReport, TaskCriterion, TaskSpec
from tools.code_executor import PytestResult
from tests.fakes import ScriptedChatModel, tool_call_reply

LINKED_LIST = '''class LinkedList:
    def __init__(self):
        self.items = []

    def insert(self, value):
        self.items.insert(0, value)

    def search(self, value):
        return value in self.items

    def to_list(self):
        return list(self.items)
'''

TAIL_APPEND = LINKED_LIST.replace("self.items.insert(0, value)", "self.items.append(value)")

CRITERION_1 = "Given a list built with insert(1) then insert(2), When insert(3), Then to_list() is [3, 2, 1]"

VALID_DRAFT = {
    "preamble": "from linked_list import LinkedList\n",
    "tests": [
        {
            "criterion_index": 0,
            "name": "test_insert_search",
            "code": (
                "def test_insert_search():\n"
                "    ll = LinkedList()\n"
                "    ll.insert(5)\n"
                "    assert ll.search(5) is True\n"
            ),
        },
        {
            "criterion_index": 1,
            "name": "test_insert_order",
            "code": (
                "def test_insert_order():\n"
                "    ll = LinkedList()\n"
                "    ll.insert(1)\n"
                "    ll.insert(2)\n"
                "    ll.insert(3)\n"
                "    assert ll.to_list() == [3, 2, 1]\n"
            ),
        },
    ],
}


@pytest.fixture
def task() -> TaskSpec:
    """Returns the linked-list task with its two criteria.

    Returns:
        ``task_1`` with files ``["linked_list.py"]``.
    """
    return TaskSpec(
        task_id="task_1",
        title="Implement a linked list",
        description="Create linked_list.py with a LinkedList class: insert at "
        "the head, search and to_list.",
        acceptance_criteria=[
            TaskCriterion(given="an empty list", when="insert(5)", then="search(5) is True"),
            TaskCriterion(
                given="a list built with insert(1) then insert(2)",
                when="insert(3)",
                then="to_list() is [3, 2, 1]",
            ),
        ],
        covers=["REQ-1"],
        files=["linked_list.py"],
        priority=1,
    )


@pytest.fixture
def settings(tmp_path) -> QASettings:
    """Returns QA settings with a temporary QA folder and 2 attempts.

    Args:
        tmp_path: Pytest's per-test temporary directory.

    Returns:
        Settings whose ``workspace_dir`` is ``tmp_path / "workspace_qa"``.
    """
    return QASettings(
        workspace_dir=tmp_path / "workspace_qa",
        model="fake",
        max_attempts=2,
        blocking_severity="High",
        test_timeout=2,
    )


def _draft_reply(draft: dict, call_id: str = "draft_1") -> AIMessage:
    """Returns a scripted reply holding a test draft.

    Args:
        draft: Arguments of the ``PytestDraft`` call.
        call_id: ID of the tool call.

    Returns:
        The AI message calling the ``PytestDraft`` tool.
    """
    return tool_call_reply("PytestDraft", draft, call_id)


def _text(messages: list) -> str:
    """Returns the contents of a call's messages joined into one text.

    Args:
        messages: Messages received by one model call.

    Returns:
        All contents joined with spaces.
    """
    return " ".join(str(m.content) for m in messages)


def _review_reply(review: dict, call_id: str = "review_1") -> AIMessage:
    """Returns a scripted reply holding a code review.

    Args:
        review: Arguments of the ``CodeReview`` call.
        call_id: ID of the tool call.

    Returns:
        The AI message calling the ``CodeReview`` tool.
    """
    return tool_call_reply("CodeReview", review, call_id)


def _test_calls(model: ScriptedChatModel) -> list[list]:
    """Returns the model calls that asked for a test draft.

    Args:
        model: The fake model after the run.

    Returns:
        The calls whose system prompt is the test-writing one.
    """
    return [call for call in model.calls if call[0].content == TESTS_SYSTEM_PROMPT]


def _invalid(change: str) -> dict:
    """Returns the valid draft broken in one way.

    Args:
        change: Which way to break it.

    Returns:
        A draft that the per-task schema must reject.
    """
    draft = copy.deepcopy(VALID_DRAFT)
    first, second = draft["tests"]
    if change == "syntax":
        first["code"] = "def test_insert_search(:\n    pass\n"
    elif change == "duplicate":
        second["name"] = "test_insert_search"
        second["code"] = second["code"].replace("test_insert_order", "test_insert_search")
    elif change == "no-test-prefix":
        first["name"] = "check_insert_search"
        first["code"] = first["code"].replace("test_insert_search", "check_insert_search")
    elif change == "name-not-defined":
        first["code"] = first["code"].replace("test_insert_search", "test_other")
    elif change == "criterion-missing":
        second["criterion_index"] = 0
    elif change == "preamble-statement":
        draft["preamble"] += "ll = LinkedList()\n"
    elif change == "extra-statement":
        first["code"] = "ll = LinkedList()\n" + first["code"]
    elif change == "missing-import":
        draft["preamble"] = ""
    return draft


def test_ac_3_2_12_writes_test_file(task, settings):
    model = ScriptedChatModel([_draft_reply(VALID_DRAFT)])

    written = write_tests(task, {"linked_list.py": LINKED_LIST}, model, settings)

    assert written.path == settings.workspace_dir / "task_1" / "test_task_1.py"
    content = written.path.read_text()
    assert "from linked_list import LinkedList" in content
    defined = [node.name for node in ast.parse(content).body if isinstance(node, ast.FunctionDef)]
    assert defined == ["test_insert_search", "test_insert_order"]
    assert written.criteria == {"test_insert_search": 0, "test_insert_order": 1}


def test_write_tests_makes_one_call_per_draft(task, settings):
    model = ScriptedChatModel([_draft_reply(_invalid("syntax")), _draft_reply(VALID_DRAFT, "d2")])

    with pytest.raises(StructuredOutputError, match="invalid Python"):
        write_tests(task, {"linked_list.py": LINKED_LIST}, model, settings)

    assert len(model.calls) == 1
    assert not (settings.workspace_dir / "task_1" / "test_task_1.py").exists()


# --- run_qa ----------------------------------------------------------------


@pytest.fixture
def coder_dir(tmp_path) -> Path:
    """Returns a temporary Coder folder holding the correct linked list.

    Args:
        tmp_path: Pytest's per-test temporary directory.

    Returns:
        The resolved folder ``tmp_path / "coder"``.
    """
    folder = (tmp_path / "coder").resolve()
    folder.mkdir()
    (folder / "linked_list.py").write_text(LINKED_LIST)
    return folder


async def _run_qa(task, model, settings, coder_dir, log_path: Path) -> QAReport:
    """Runs the QA with the MCP server's stderr written to a file.

    Args:
        task: The task to review.
        model: Fake chat model.
        settings: QA settings.
        coder_dir: The Coder's folder.
        log_path: File for the server's stderr log.

    Returns:
        The QA's report.
    """
    with log_path.open("w") as errlog:
        return await run_qa(task, model=model, settings=settings, coder_dir=coder_dir, errlog=errlog)


def _snapshot(folder: Path) -> dict[str, bytes | None]:
    """Returns every path under a folder with its content.

    Args:
        folder: Folder to record.

    Returns:
        Relative path to file bytes; None for folders.
    """
    return {
        str(path.relative_to(folder)): path.read_bytes() if path.is_file() else None
        for path in sorted(folder.rglob("*"))
    }


@pytest.mark.timeout(60)
async def test_ac_3_2_18_reads_through_mcp(task, settings, coder_dir, tmp_path):
    (coder_dir / "linked_list.py").write_text(
        '"""A linked list."""\n'
        "class LinkedList:\n"
        '    """Singly linked list."""\n'
        "    size: int = 0\n"
        "\n"
        "    def __init__(self):\n"
        "        self.items = []\n"
        "\n"
        "    def insert(self, value: int, at_head: bool = True) -> None:\n"
        '        """Inserts a value."""\n'
        "        self.items.insert(0, value)\n"
        "\n"
        "    def search(self, value):\n"
        "        return value in self.items\n"
        "\n"
        "    def to_list(self):\n"
        "        return list(self.items)\n"
        "\n"
        "    @property\n"
        "    def empty(self) -> bool:\n"
        "        return not self.items\n"
    )
    model = ScriptedChatModel([_draft_reply(VALID_DRAFT)])
    log_path = tmp_path / "server.log"

    await _run_qa(task, model, settings, coder_dir, log_path)

    assert "read_file 'linked_list.py'" in log_path.read_text()
    request = _text(model.calls[0])
    for fragment in [
        "class LinkedList",
        "def insert(self, value: int, at_head: bool=True) -> None",
        "@property",
        "def empty(self) -> bool",
        "size: int = 0",
        "Inserts a value.",
        "search(5) is True",
        "to_list() is [3, 2, 1]",
    ]:
        assert fragment in request, fragment
    assert "self.items.insert(0, value)" not in request
    assert "return value in self.items" not in request


@pytest.mark.timeout(60)
async def test_ac_3_2_20_failure_becomes_issue_fallback_fix(task, settings, coder_dir, tmp_path):
    (coder_dir / "linked_list.py").write_text(TAIL_APPEND)
    model = ScriptedChatModel([_draft_reply(VALID_DRAFT)])

    report = await _run_qa(task, model, settings, coder_dir, tmp_path / "server.log")

    assert report.approved is False
    assert (report.tests_passed, report.tests_failed) == (1, 1)
    [issue] = report.issues
    assert (issue.source, issue.severity) == ("test", "High")
    assert issue.location == "test_task_1.py::test_insert_order"
    assert issue.criterion == CRITERION_1
    assert "[1, 2, 3]" in issue.description
    assert issue.fix.startswith("Make test_insert_order pass; it failed with: ")
    assert "[1, 2, 3]" in issue.fix


@pytest.mark.timeout(60)
async def test_correct_code_passes_without_issues(task, settings, coder_dir, tmp_path):
    model = ScriptedChatModel([_draft_reply(VALID_DRAFT)])

    report = await _run_qa(task, model, settings, coder_dir, tmp_path / "server.log")

    assert report.approved is True
    assert (report.tests_passed, report.tests_failed, report.issues) == (2, 0, [])


@pytest.mark.timeout(60)
async def test_ac_3_2_14_attempt_budget_report(task, settings, coder_dir, tmp_path):
    replies = [_draft_reply(_invalid("syntax"), f"draft_{k}") for k in range(1, 4)]
    model = ScriptedChatModel(replies)

    report = await _run_qa(task, model, settings, coder_dir, tmp_path / "server.log")

    assert len(_test_calls(model)) == 2
    assert report.approved is False
    [issue] = report.issues
    assert (issue.source, issue.severity) == ("qa", "High")
    assert "no runnable tests" in issue.description


@pytest.mark.timeout(60)
async def test_ac_3_2_23_mcp_server_cannot_start(task, settings, coder_dir, tmp_path, monkeypatch):
    broken = StdioServerParameters(command=str(tmp_path / "no-such-python"))
    monkeypatch.setattr(tools.mcp_client, "_server_parameters", lambda workspace: broken)
    model = ScriptedChatModel([_draft_reply(VALID_DRAFT)])

    report = await _run_qa(task, model, settings, coder_dir, tmp_path / "server.log")

    assert model.calls == []
    assert report.approved is False
    [issue] = report.issues
    assert (issue.source, issue.severity, issue.location) == ("qa", "High", "MCP read")
    assert "FileNotFoundError" in issue.description
    assert "no-such-python" in issue.description


@pytest.mark.timeout(60)
async def test_ac_3_2_23_model_raises(task, settings, coder_dir, tmp_path):
    model = ScriptedChatModel([RuntimeError("provider down")])

    report = await _run_qa(task, model, settings, coder_dir, tmp_path / "server.log")

    assert report.approved is False
    [issue] = report.issues
    assert (issue.source, issue.severity, issue.location) == ("qa", "High", "test writing")
    assert "RuntimeError: provider down" in issue.description


@pytest.mark.timeout(120)
async def test_ac_3_2_24_coder_folder_untouched(task, settings, coder_dir, tmp_path):
    for code, approved in [(LINKED_LIST, True), (TAIL_APPEND, False)]:
        (coder_dir / "linked_list.py").write_text(code)
        before = _snapshot(coder_dir)
        model = ScriptedChatModel([_draft_reply(VALID_DRAFT)])

        report = await _run_qa(task, model, settings, coder_dir, tmp_path / "server.log")

        assert report.approved is approved
        assert _snapshot(coder_dir) == before
    written = [path for path in settings.workspace_dir.rglob("*") if path.is_file()]
    assert written
    assert all(path.is_relative_to(settings.workspace_dir / "task_1") for path in written)


@pytest.mark.timeout(60)
async def test_ac_3_2_25_steps_logged(task, settings, coder_dir, tmp_path, caplog):
    (coder_dir / "linked_list.py").write_text(TAIL_APPEND)
    model = ScriptedChatModel([_draft_reply(VALID_DRAFT)])
    caplog.set_level(logging.INFO, logger="agents.qa_agent")

    await _run_qa(task, model, settings, coder_dir, tmp_path / "server.log")

    messages = [r.getMessage() for r in caplog.records if r.name == "agents.qa_agent" and r.levelno == logging.INFO]
    def logged(*fragments: str) -> bool:
        """Returns whether one INFO message holds every fragment.

        Args:
            *fragments: Texts that must appear together.

        Returns:
            True if some message contains them all.
        """
        return any(all(f in m for f in fragments) for m in messages)

    assert logged("read", "linked_list.py"), messages
    assert logged("wrote", "test_task_1.py", "2 tests"), messages
    assert logged("pytest command", "-m pytest", "--timeout=2"), messages
    assert logged("pytest", "1 passed", "1 failed"), messages
    assert logged("verdict", "not approved", "1 blocking"), messages


def _uncollectable() -> dict:
    """Returns a draft that passes the schema but fails at collection.

    Returns:
        The valid draft whose first test is parametrized with an argument
        its function does not take.
    """
    draft = copy.deepcopy(VALID_DRAFT)
    draft["preamble"] = "import pytest\nfrom linked_list import LinkedList\n"
    first = draft["tests"][0]
    first["code"] = '@pytest.mark.parametrize("x", [1])\n' + first["code"]
    return draft


def _report_files(settings: QASettings) -> list[Path]:
    """Returns the JUnit reports pytest left in the task's QA folder.

    Args:
        settings: QA settings.

    Returns:
        The ``junit.xml`` files; empty when pytest never ran.
    """
    return list((settings.workspace_dir / "task_1").glob("junit.xml"))


@pytest.mark.timeout(120)
@pytest.mark.parametrize(
    ("change", "error_text"),
    [
        ("syntax", "invalid Python"),
        ("duplicate", "duplicate test name"),
        ("no-test-prefix", "must start with 'test_'"),
        ("name-not-defined", "exactly one function named"),
        ("criterion-missing", "criterion 1 has no test"),
        ("preamble-statement", "preamble"),
        ("extra-statement", "exactly one function named"),
        ("missing-import", "never imported or defined: LinkedList"),
    ],
)
async def test_ac_3_2_13_invalid_draft_rejected(task, settings, coder_dir, tmp_path, change, error_text):
    model = ScriptedChatModel(
        [_draft_reply(_invalid(change), "draft_1"), _draft_reply(VALID_DRAFT, "draft_2")]
    )

    report = await _run_qa(task, model, settings, coder_dir, tmp_path / "server.log")

    assert len(_test_calls(model)) == 2
    assert error_text in _text(_test_calls(model)[1])
    assert report.approved is True
    assert report.tests_passed == 2
    body = ast.parse((settings.workspace_dir / "task_1" / "test_task_1.py").read_text()).body
    assert all(isinstance(node, (ast.ImportFrom, ast.FunctionDef)) for node in body)
    assert [node.name for node in body[1:]] == ["test_insert_search", "test_insert_order"]


@pytest.mark.timeout(120)
@pytest.mark.parametrize("broken", ["invalid", "uncollectable"])
async def test_ac_3_2_14_attempt_budget(task, settings, coder_dir, tmp_path, broken):
    draft = _invalid("syntax") if broken == "invalid" else _uncollectable()
    model = ScriptedChatModel([_draft_reply(draft, f"draft_{k}") for k in range(1, 4)])

    report = await _run_qa(task, model, settings, coder_dir, tmp_path / "server.log")

    assert len(_test_calls(model)) == 2
    assert report.approved is False
    [issue] = report.issues
    assert (issue.source, issue.severity) == ("qa", "High")
    assert "no runnable tests" in issue.description


@pytest.mark.timeout(120)
async def test_ac_3_2_15_test_collection_error_regenerates(task, settings, coder_dir, tmp_path):
    model = ScriptedChatModel([_draft_reply(_uncollectable(), "d1"), _draft_reply(VALID_DRAFT, "d2")])

    report = await _run_qa(task, model, settings, coder_dir, tmp_path / "server.log")

    assert len(_test_calls(model)) == 2
    assert "function uses no argument 'x'" in _text(_test_calls(model)[1])
    assert report.approved is True
    assert report.tests_passed == 2


@pytest.mark.timeout(120)
@pytest.mark.parametrize(
    ("case", "preamble", "coder_code", "regenerated", "named"),
    [
        ("a-unknown-module", "from linkedlist import LinkedList\n", LINKED_LIST, True, "linkedlist"),
        ("b-missing-file", None, None, False, "linked_list.py"),
        ("c-missing-task-name", None, "class Other:\n    pass\n", False, "LinkedList"),
        ("d-invented-name", "from linked_list import LinkedList, Node\n", LINKED_LIST, True, "Node"),
    ],
    ids=["a", "b", "c", "d"],
)
async def test_ac_3_2_16_import_check(
    task, settings, coder_dir, tmp_path, case, preamble, coder_code, regenerated, named
):
    if coder_code is None:
        (coder_dir / "linked_list.py").unlink()
    else:
        (coder_dir / "linked_list.py").write_text(coder_code)
    first = copy.deepcopy(VALID_DRAFT)
    if preamble is not None:
        first["preamble"] = preamble
    model = ScriptedChatModel([_draft_reply(first, "d1"), _draft_reply(VALID_DRAFT, "d2")])

    report = await _run_qa(task, model, settings, coder_dir, tmp_path / "server.log")

    if regenerated:
        assert len(_test_calls(model)) == 2
        assert named in _text(_test_calls(model)[1])
        assert report.approved is True
        assert report.tests_passed == 2
    else:
        assert len(_test_calls(model)) == 1
        assert _report_files(settings) == []
        assert report.approved is False
        [issue] = report.issues
        assert (issue.source, issue.severity) == ("test", "High")
        assert named in issue.description


@pytest.mark.timeout(120)
async def test_ac_3_2_17_coder_collection_error(task, settings, coder_dir, tmp_path):
    (coder_dir / "linked_list.py").write_text(LINKED_LIST + "\nraise RuntimeError('broken at import')\n")
    model = ScriptedChatModel([_draft_reply(VALID_DRAFT, "d1"), _draft_reply(VALID_DRAFT, "d2")])

    report = await _run_qa(task, model, settings, coder_dir, tmp_path / "server.log")

    assert len(_test_calls(model)) == 1
    assert report.approved is False
    [issue] = report.issues
    assert (issue.source, issue.severity) == ("test", "High")
    assert "RuntimeError" in issue.description
    assert "linked_list.py" in issue.description


@pytest.mark.timeout(120)
@pytest.mark.parametrize("case", ["a-coder-hangs", "b-test-hangs", "c-import-hangs"])
async def test_ac_3_2_22_timeouts(task, settings, coder_dir, tmp_path, monkeypatch, case):
    settings = settings.model_copy(update={"test_timeout": 1})
    monkeypatch.setattr(tools.code_executor, "EXEC_TIMEOUT", 5)
    first = VALID_DRAFT
    if case == "a-coder-hangs":
        (coder_dir / "linked_list.py").write_text(
            LINKED_LIST.replace("return value in self.items", "while True:\n            pass")
        )
    elif case == "b-test-hangs":
        first = copy.deepcopy(VALID_DRAFT)
        first["tests"][1]["code"] = "def test_insert_order():\n    while True:\n        pass\n"
    else:
        (coder_dir / "linked_list.py").write_text(LINKED_LIST + "\nwhile True:\n    pass\n")
    model = ScriptedChatModel([_draft_reply(first, "d1"), _draft_reply(VALID_DRAFT, "d2")])

    started = time.monotonic()
    report = await _run_qa(task, model, settings, coder_dir, tmp_path / "server.log")
    assert time.monotonic() - started < 15

    if case == "b-test-hangs":
        assert len(_test_calls(model)) == 2
        assert "timed out" in _text(_test_calls(model)[1])
        assert report.approved is True
        assert report.tests_passed == 2
        return
    assert len(_test_calls(model)) == 1
    assert report.approved is False
    [issue] = report.issues
    assert (issue.source, issue.severity) == ("test", "High")
    if case == "a-coder-hangs":
        assert issue.location == "test_task_1.py::test_insert_search"
        assert "timed out" in issue.description
        assert "linked_list.py" in issue.description
        assert report.tests_passed == 1
    else:
        assert "whole test run timed out" in issue.description


INSERT_ORDER = "test_task_1.py::test_insert_order"


@pytest.mark.timeout(60)
async def test_ac_3_2_19_correct_code_approved(task, settings, coder_dir, tmp_path):
    low = {
        "severity": "Low",
        "location": "linked_list.py: LinkedList",
        "description": "The class has no docstrings.",
        "fix": "Add docstrings to LinkedList and its methods.",
    }
    model = ScriptedChatModel([_draft_reply(VALID_DRAFT), _review_reply({"fixes": [], "issues": [low]})])

    report = await _run_qa(task, model, settings, coder_dir, tmp_path / "server.log")

    assert report.approved is True
    assert report.tests_passed == 2
    [issue] = report.issues
    assert (issue.source, issue.severity, issue.fix) == ("review", "Low", low["fix"])
    review_request = _text(model.calls[1])
    assert "self.items.insert(0, value)" in review_request


@pytest.mark.timeout(60)
async def test_ac_3_2_20_failure_gets_review_fix(task, settings, coder_dir, tmp_path):
    (coder_dir / "linked_list.py").write_text(TAIL_APPEND)
    fix = "In insert, use self.items.insert(0, value) so new values go to the head."
    model = ScriptedChatModel([
        _draft_reply(VALID_DRAFT),
        _review_reply({"fixes": [{"failure": 0, "fix": fix}], "issues": []}),
    ])

    report = await _run_qa(task, model, settings, coder_dir, tmp_path / "server.log")

    assert report.approved is False
    [issue] = report.issues
    assert (issue.source, issue.severity, issue.location) == ("test", "High", INSERT_ORDER)
    assert issue.criterion == CRITERION_1
    assert "[1, 2, 3]" in issue.description
    assert issue.fix == fix
    review_request = _text(model.calls[1])
    assert INSERT_ORDER in review_request
    assert "self.items.append(value)" in review_request


@pytest.mark.timeout(60)
async def test_review_missing_fix_is_corrected(task, settings, coder_dir, tmp_path):
    (coder_dir / "linked_list.py").write_text(TAIL_APPEND)
    fix = "In insert, add at the head."
    model = ScriptedChatModel([
        _draft_reply(VALID_DRAFT),
        _review_reply({"fixes": [], "issues": []}, "review_1"),
        _review_reply({"fixes": [{"failure": 0, "fix": fix}], "issues": []}, "review_2"),
    ])

    report = await _run_qa(task, model, settings, coder_dir, tmp_path / "server.log")

    assert "no fix for failure 0" in _text(model.calls[2])
    assert report.issues[0].fix == fix


@pytest.mark.timeout(120)
@pytest.mark.parametrize(
    ("case", "code", "threshold", "approved"),
    [
        ("a-correct-high", LINKED_LIST, "High", True),
        ("b-bug-high", TAIL_APPEND, "High", False),
        ("c-correct-medium", LINKED_LIST, "Medium", False),
    ],
    ids=["a", "b", "c"],
)
async def test_ac_3_2_21_review_unavailable(task, settings, coder_dir, tmp_path, case, code, threshold, approved):
    (coder_dir / "linked_list.py").write_text(code)
    settings = settings.model_copy(update={"blocking_severity": threshold})
    high = {"severity": "High", "location": "x", "description": "y", "fix": "z"}
    model = ScriptedChatModel([
        _draft_reply(VALID_DRAFT),
        _review_reply({"fixes": [], "issues": [high]}, "review_1"),
        _review_reply({"fixes": [], "issues": [high]}, "review_2"),
    ])

    report = await _run_qa(task, model, settings, coder_dir, tmp_path / "server.log")

    assert len(model.calls) == 3
    assert report.approved is approved
    assert "review unavailable" in report.notes
    assert all(issue.source != "review" for issue in report.issues)
    if case == "b-bug-high":
        [issue] = report.issues
        assert issue.fix.startswith("Make test_insert_order pass; it failed with: ")
    if case == "c-correct-medium":
        [issue] = report.issues
        assert (issue.source, issue.severity) == ("qa", "High")
        assert "review unavailable" in issue.description


@pytest.mark.llm
@pytest.mark.timeout(300)
async def test_ac_3_2_26_live_qa(task, settings, coder_dir, tmp_path):
    settings = settings.model_copy(update={"model": DEFAULT_QA_MODEL})

    (coder_dir / "linked_list.py").write_text(TAIL_APPEND)
    buggy = await run_qa(task, settings=settings, coder_dir=coder_dir)
    (coder_dir / "linked_list.py").write_text(LINKED_LIST)
    correct = await run_qa(task, settings=settings, coder_dir=coder_dir)

    assert buggy.approved is False
    assert any(
        issue.source == "test" and issue.severity == "High" and issue.criterion == CRITERION_1
        for issue in buggy.issues
    ), buggy.issues
    assert correct.approved is True, correct.issues



def _with_order_test(code: str, preamble: str = "import pytest\nfrom linked_list import LinkedList\n") -> dict:
    """Returns the valid draft with another code for the criterion-1 test.

    Args:
        code: The new code of ``test_insert_order``.
        preamble: The draft's preamble.

    Returns:
        The changed draft.
    """
    draft = copy.deepcopy(VALID_DRAFT)
    draft["preamble"] = preamble
    draft["tests"][1]["code"] = code
    return draft


ORDER_BODY = (
    "    ll = LinkedList()\n"
    "    ll.insert(1)\n"
    "    ll.insert(2)\n"
    "    ll.insert(3)\n"
    "    assert ll.to_list() == [3, 2, 1]\n"
)


@pytest.mark.timeout(120)
@pytest.mark.parametrize(
    "code",
    [
        "@pytest.mark.xfail\ndef test_insert_order():\n" + ORDER_BODY,
        "def test_insert_order():\n    pytest.skip('later')\n",
        "@pytest.mark.skipif(True, reason='later')\ndef test_insert_order():\n" + ORDER_BODY,
    ],
    ids=["xfail", "skip-call", "skipif"],
)
async def test_ac_3_2_28_skips_never_approve(task, settings, coder_dir, tmp_path, code):
    (coder_dir / "linked_list.py").write_text(TAIL_APPEND)
    model = ScriptedChatModel([_draft_reply(_with_order_test(code), "d1"), _draft_reply(VALID_DRAFT, "d2")])

    report = await _run_qa(task, model, settings, coder_dir, tmp_path / "server.log")

    assert len(_test_calls(model)) == 2
    assert "must not skip" in _text(_test_calls(model)[1])
    assert report.approved is False
    assert (report.tests_passed, report.tests_failed) == (1, 1)


def test_skipped_test_at_run_is_the_qa_fault(task, settings, tmp_path):
    written = WrittenTests(
        path=tmp_path / "qa" / "test_task_1.py",
        criteria={"test_insert_search": 0, "test_insert_order": 1},
    )
    result = PytestResult(status="passed", passed=1, skipped=["test_insert_order"])

    judged = _judge_run(task, written, result, settings, tmp_path / "coder")

    assert isinstance(judged, str)
    assert "test_insert_order" in judged
    assert "skipped" in judged


@pytest.mark.timeout(120)
async def test_ac_3_2_29_run_timeout_scales(task, settings, coder_dir, tmp_path, monkeypatch):
    settings = settings.model_copy(update={"test_timeout": 1})
    monkeypatch.setattr(tools.code_executor, "EXEC_TIMEOUT", 3)
    (coder_dir / "linked_list.py").write_text(
        LINKED_LIST.replace("self.items.insert(0, value)", "while True:\n            pass")
    )
    draft = copy.deepcopy(VALID_DRAFT)
    for k, test in enumerate(copy.deepcopy(VALID_DRAFT["tests"])):
        test["name"] = f"{test['name']}_again"
        test["code"] = test["code"].replace(f"def {VALID_DRAFT['tests'][k]['name']}", f"def {test['name']}")
        draft["tests"].append(test)
    model = ScriptedChatModel([_draft_reply(draft)])

    report = await _run_qa(task, model, settings, coder_dir, tmp_path / "server.log")

    assert report.approved is False
    assert report.tests_failed == 4
    assert len(report.issues) == 4
    for issue in report.issues:
        assert (issue.source, issue.severity) == ("test", "High")
        assert "timed out" in issue.description
        assert "linked_list.py" in issue.description


@pytest.mark.timeout(60)
async def test_ac_3_2_30_parametrized_failure_criterion(task, settings, coder_dir, tmp_path):
    (coder_dir / "linked_list.py").write_text(TAIL_APPEND)
    code = (
        '@pytest.mark.parametrize("n", [3])\n'
        "def test_insert_order(n):\n"
        "    ll = LinkedList()\n"
        "    ll.insert(1)\n"
        "    ll.insert(2)\n"
        "    ll.insert(n)\n"
        "    assert ll.to_list() == [3, 2, 1]\n"
    )
    model = ScriptedChatModel([_draft_reply(_with_order_test(code))])

    report = await _run_qa(task, model, settings, coder_dir, tmp_path / "server.log")

    [issue] = report.issues
    assert issue.location == "test_task_1.py::test_insert_order[3]"
    assert issue.criterion == CRITERION_1


@pytest.mark.timeout(60)
async def test_ac_3_2_31_unreadable_task_file(task, settings, coder_dir, tmp_path):
    (coder_dir / "linked_list.py").write_bytes(LINKED_LIST.encode() + b"# \xff\xfe\n")
    model = ScriptedChatModel([_draft_reply(VALID_DRAFT, "d1"), _draft_reply(VALID_DRAFT, "d2")])

    report = await _run_qa(task, model, settings, coder_dir, tmp_path / "server.log")

    assert len(_test_calls(model)) == 1
    assert _report_files(settings) == []
    assert report.approved is False
    [issue] = report.issues
    assert (issue.source, issue.severity, issue.location) == ("test", "High", "linked_list.py")
    assert "could not be read" in issue.description
    assert "utf-8" in issue.description.lower()
    assert "not found" not in issue.description


@pytest.mark.timeout(60)
async def test_review_fixes_match_by_failure_number(task, settings, coder_dir, tmp_path):
    task = task.model_copy(update={"description": task.description + " Nodes are Node objects."})
    (coder_dir / "linked_list.py").write_text("class Other:\n    pass\n")
    draft = copy.deepcopy(VALID_DRAFT)
    draft["preamble"] = "from linked_list import LinkedList, Node\n"
    model = ScriptedChatModel([
        _draft_reply(draft),
        _review_reply({"fixes": [{"failure": 0, "fix": "Add LinkedList."}, {"failure": 1, "fix": "Add Node."}]}),
    ])

    report = await _run_qa(task, model, settings, coder_dir, tmp_path / "server.log")

    assert [issue.fix for issue in report.issues] == ["Add LinkedList.", "Add Node."]

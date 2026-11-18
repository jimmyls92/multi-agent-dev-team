"""Tests of the QA agent (Lab 3.2).

Covers spec `lab_3_2_qa_agent` AC-3.2-12, AC-3.2-13, AC-3.2-14 (invalid
drafts), AC-3.2-18, AC-3.2-20 (fallback fix), AC-3.2-23, AC-3.2-24 and
AC-3.2-25 (DEC-141, DEC-142, DEC-145, DEC-148, DEC-149, DEC-152, DEC-157,
DEC-158), with a fake model, the linked-list task and, for ``run_qa``, the
real MCP server over stdio and the real pytest sandbox.
"""

import ast
import copy
import logging
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from mcp import StdioServerParameters

import tools.mcp_client
from agents.llm_helpers import StructuredOutputError
from agents.qa_agent import QASettings, run_qa, write_tests
from orchestration.state import QAReport, TaskCriterion, TaskSpec
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
    ],
)
def test_ac_3_2_13_invalid_draft_rejected(task, settings, change, error_text):
    model = ScriptedChatModel(
        [_draft_reply(_invalid(change), "draft_1"), _draft_reply(VALID_DRAFT, "draft_2")]
    )

    written = write_tests(task, {"linked_list.py": LINKED_LIST}, model, settings)

    assert len(model.calls) == 2
    assert error_text in _text(model.calls[1])
    assert written.criteria == {"test_insert_search": 0, "test_insert_order": 1}
    body = ast.parse(written.path.read_text()).body
    assert all(isinstance(node, (ast.ImportFrom, ast.FunctionDef)) for node in body)
    assert [node.name for node in body[1:]] == ["test_insert_search", "test_insert_order"]


def test_ac_3_2_14_attempt_budget_invalid_drafts(task, settings):
    replies = [_draft_reply(_invalid("syntax"), f"draft_{k}") for k in range(1, 4)]
    model = ScriptedChatModel(replies)

    with pytest.raises(StructuredOutputError):
        write_tests(task, {"linked_list.py": LINKED_LIST}, model, settings)

    assert len(model.calls) == 2
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

    assert len(model.calls) == 2
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
    assert "Error" in issue.description


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
    assert logged("pytest", "test timeout 2s"), messages
    assert logged("pytest", "1 passed", "1 failed"), messages
    assert logged("verdict", "not approved", "1 blocking"), messages

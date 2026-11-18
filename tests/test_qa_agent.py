"""Tests of the QA agent (Lab 3.2).

Covers spec `lab_3_2_qa_agent` AC-3.2-12, AC-3.2-13 and the invalid-draft
part of AC-3.2-14 (DEC-141, DEC-148, DEC-152, DEC-157), with a fake model
and the linked-list task.
"""

import ast
import copy

import pytest
from langchain_core.messages import AIMessage

from agents.llm_helpers import StructuredOutputError
from agents.qa_agent import QASettings, write_tests
from orchestration.state import TaskCriterion, TaskSpec
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

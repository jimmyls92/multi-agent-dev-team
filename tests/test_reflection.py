"""Tests of the Coder's self-evaluation (Lab 3.3, T4).

Covers spec `lab_3_3_a2a_loop` AC-3.3-12 .. AC-3.3-15 and the evaluation
part of AC-3.3-16 (DEC-171, DEC-173, DEC-182, DEC-183, DEC-193), with a
fake model and the linked-list task.
"""

import copy
import logging

import pytest

import memory
from agents.coder_reflection import (
    KIND_SEVERITY,
    RUBRIC_ITEMS,
    BugCounts,
    best_version,
    evaluate_version,
)
from memory import SlidingWindowBuffer
from orchestration.state import TaskCriterion, TaskSpec
from tests.fakes import ScriptedChatModel, tool_call_reply

LINKED_LIST = "class LinkedList:\n    def __init__(self):\n        self.items = []\n"


@pytest.fixture
def task() -> TaskSpec:
    """Returns the linked-list task with its two criteria.

    Returns:
        ``task_1`` with files ``["linked_list.py"]``.
    """
    return TaskSpec(
        task_id="task_1",
        title="Implement a linked list",
        description="Create linked_list.py with a LinkedList class: insert at the head, "
        "search and to_list.",
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


def _bug(kind: str = "logic_error", location: str = "linked_list.py: LinkedList.reverse") -> dict:
    """Returns data for one valid bug.

    Args:
        kind: The defect kind.
        location: File and function.

    Returns:
        The bug's arguments.
    """
    return {
        "kind": kind,
        "location": location,
        "evidence": "reverse() on [1] gives []",
        "cause": "the loop drops the last node",
        "fix": "keep the last node as the new head",
    }


def _items(bugs: dict[str, list[dict]] | None = None, na: tuple[str, ...] = ("E8",)) -> list[dict]:
    """Returns one verdict per rubric item of the task: ok, n/a or bug.

    Args:
        bugs: Item to its bugs; those items are ``bug``.
        na: Items that are ``n/a``.

    Returns:
        Verdicts for C0, C1 and E1..E11.
    """
    bugs = bugs or {}
    verdicts = []
    for item in ["C0", "C1", *RUBRIC_ITEMS]:
        if item in bugs:
            verdicts.append({"item": item, "verdict": "bug", "evidence": "see bugs", "bugs": bugs[item]})
        elif item in na:
            verdicts.append({"item": item, "verdict": "n/a", "evidence": "no files or network", "bugs": []})
        else:
            verdicts.append({"item": item, "verdict": "ok", "evidence": "checked", "bugs": []})
    return verdicts


def _reply(items: list[dict], call_id: str = "eval_1"):
    """Returns a scripted reply holding a self-evaluation.

    Args:
        items: The item verdicts.
        call_id: ID of the tool call.

    Returns:
        The AI message calling the ``SelfEvaluation`` tool.
    """
    return tool_call_reply("SelfEvaluation", {"items": items}, call_id)


def _text(messages: list) -> str:
    """Returns the text of every message of one model call.

    Args:
        messages: Messages the model received.

    Returns:
        Their contents joined.
    """
    return "\n".join(str(m.content) for m in messages)


def _invalid(case: str) -> list[dict]:
    """Returns item verdicts broken in one way.

    Args:
        case: Which check the verdicts break.

    Returns:
        The broken verdicts.
    """
    items = _items({"E2": [_bug()]})
    if case == "missing-item":
        items = [i for i in items if i["item"] != "E4"]
    elif case == "repeated-item":
        items.append(copy.deepcopy(items[1]))
    elif case == "unknown-criterion":
        items.append({"item": "C2", "verdict": "ok", "evidence": "x", "bugs": []})
    elif case == "criterion-na":
        items[0].update(verdict="n/a", bugs=[])
    elif case == "bug-without-evidence":
        next(i for i in items if i["item"] == "E2")["bugs"][0]["evidence"] = " "
    elif case == "unknown-kind":
        next(i for i in items if i["item"] == "E2")["bugs"][0]["kind"] = "typo"
    elif case == "bug-without-diagnosis":
        next(i for i in items if i["item"] == "E2")["bugs"] = []
    elif case == "ok-with-diagnosis":
        items[0]["bugs"] = [_bug()]
    return items


@pytest.mark.parametrize(
    ("case", "error"),
    [
        ("missing-item", "no verdict for E4"),
        ("repeated-item", "more than once"),
        ("unknown-criterion", "unknown item C2"),
        ("criterion-na", "cannot be n/a"),
        ("bug-without-evidence", "evidence"),
        ("unknown-kind", "kind"),
        ("bug-without-diagnosis", "lists no bug"),
        ("ok-with-diagnosis", "lists bugs"),
    ],
)
def test_ac_3_3_12_evaluation_schema(task, case, error):
    model = ScriptedChatModel([_reply(_invalid(case), "eval_1"), _reply(_items({"E2": [_bug()]}), "eval_2")])

    evaluation = evaluate_version(task, {"linked_list.py": LINKED_LIST}, model)

    assert len(model.calls) == 2
    assert error in _text(model.calls[1])
    assert evaluation.counts() == BugCounts(high=1, medium=0, low=0)


def test_ac_3_3_12_bug_needs_concrete_fields(task):
    model = ScriptedChatModel([_reply(_items({"E2": [_bug(), _bug("crash", "linked_list.py: delete")]}))])

    evaluation = evaluate_version(task, {"linked_list.py": LINKED_LIST}, model)

    [e2] = [i for i in evaluation.items if i.item == "E2"]
    assert [bug.kind for bug in e2.bugs] == ["logic_error", "crash"]
    assert evaluation.counts().high == 2


def test_ac_3_3_13_kind_to_severity(task):
    kinds = list(KIND_SEVERITY)
    model = ScriptedChatModel([_reply(_items({"E11": [_bug(kind) for kind in kinds]}))])

    evaluation = evaluate_version(task, {"linked_list.py": LINKED_LIST}, model)

    assert {k: v for k, v in KIND_SEVERITY.items() if v == "High"}.keys() == {"logic_error", "crash", "security"}
    assert {k for k, v in KIND_SEVERITY.items() if v == "Medium"} == {"missing_edge_case", "unclear_error"}
    assert {k for k, v in KIND_SEVERITY.items() if v == "Low"} == {
        "missing_type_annotation",
        "style",
        "naming",
        "docstring",
    }
    assert evaluation.counts() == BugCounts(high=3, medium=2, low=4)
    assert evaluation.needs_improvement() is True


def test_ac_3_3_13_low_bugs_need_no_improvement(task):
    model = ScriptedChatModel([_reply(_items({"E9": [_bug("missing_type_annotation")], "E10": [_bug("style")]}))])

    evaluation = evaluate_version(task, {"linked_list.py": LINKED_LIST}, model)

    assert evaluation.counts() == BugCounts(high=0, medium=0, low=2)
    assert evaluation.needs_improvement() is False


@pytest.mark.parametrize(
    ("v0", "v1", "best"),
    [
        ((1, 0, 0), (0, 9, 9), 1),
        ((0, 1, 0), (0, 0, 9), 1),
        ((0, 2, 0), (0, 1, 5), 1),
        ((0, 0, 1), (0, 0, 1), 1),
        ((0, 0, 0), (0, 0, 1), 0),
    ],
    ids=["high-beats-many-medium", "medium-beats-many-low", "fewer-medium", "tie-improved", "v0-better"],
)
def test_ac_3_3_14_ranking(v0, v1, best):
    assert best_version([BugCounts(*v0), BugCounts(*v1)]) == best


def test_ac_3_3_15_evaluation_context(task, monkeypatch):
    def refuse(*args, **kwargs):
        """Raises: the evaluation must not touch the memory.

        Raises:
            AssertionError: Always.
        """
        raise AssertionError("the self-evaluation used the memory")

    monkeypatch.setattr(memory, "get_collection", refuse)
    monkeypatch.setattr(memory, "build_context", refuse)
    monkeypatch.setattr(memory, "store_memory", refuse)
    window = SlidingWindowBuffer(max_turns=5)
    window.add_turn([{"role": "user", "content": "WINDOW TURN"}])
    before = window.get_messages()
    model = ScriptedChatModel([_reply(_items())])

    evaluate_version(task, {"linked_list.py": LINKED_LIST}, model)

    [call] = model.calls
    text = _text(call)
    assert "self.items = []" in text
    assert "to_list() is [3, 2, 1]" in text
    assert task.description in text
    assert "WINDOW TURN" not in text
    assert window.get_messages() == before


def test_ac_3_3_16_evaluation_unavailable(task, caplog):
    caplog.set_level(logging.WARNING)
    model = ScriptedChatModel([_reply(_invalid("missing-item"), "e1"), _reply(_invalid("criterion-na"), "e2")])

    evaluation = evaluate_version(task, {"linked_list.py": LINKED_LIST}, model)

    assert evaluation is None
    assert len(model.calls) == 2
    assert "critique unavailable" in caplog.text

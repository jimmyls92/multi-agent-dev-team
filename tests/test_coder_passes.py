"""Tests of the prompt of each Coder pass and of the task history (Lab 3.3, T5).

Covers spec `lab_3_3_a2a_loop` AC-3.3-17 .. AC-3.3-20 (DEC-184, DEC-185,
DEC-186, DEC-187, DEC-194, DEC-195), with the linked-list task and a
fake model.
"""

import pytest

import memory
import tools.file_io
from agents.coder_agent import (
    correction_prompt,
    first_pass_prompt,
    improvement_prompt,
    run_agent,
)
from agents.coder_reflection import Bug, ItemVerdict, SelfEvaluationBase
from memory import MEMORY_HEADING, SlidingWindowBuffer, store_memory
from orchestration.state import (
    FailedTest,
    Issue,
    ProjectSpec,
    QAReport,
    ReviewRecord,
    SpecCriterion,
    TaskCriterion,
    TaskState,
)
from tests.coder_helpers import all_text, successful_task
from tests.fakes import ScriptedChatModel

LINKED_LIST = "class LinkedList:\n    def __init__(self):\n        self.head = None\n"
BIG = "BIG_FILE_CONTENT = 1\n"
TEST_SOURCE = "def test_reverse_single():\n    assert LinkedList([1]).reverse().to_list() == [1]\n"


@pytest.fixture
def spec() -> ProjectSpec:
    """Returns the PM's spec of the linked-list project.

    Returns:
        A spec named ``Linked list``.
    """
    return ProjectSpec(
        name="Linked list",
        description="A singly linked list library.",
        details="One module, linked_list.py, with the LinkedList class.",
        tasks=[],
        acceptance_criteria=[
            SpecCriterion(id="REQ-1", text="The list keeps its elements in order.")
        ],
    )


@pytest.fixture
def task() -> TaskState:
    """Returns the linked-list task with two planned files.

    Returns:
        ``task_1`` planning ``linked_list.py`` and ``utils.py``.
    """
    return TaskState(
        task_id="task_1",
        title="Implement a linked list",
        description="Create linked_list.py with insert, search, to_list and reverse.",
        acceptance_criteria=[
            TaskCriterion(given="an empty list", when="insert(5)", then="search(5) is True"),
            TaskCriterion(given="a list [1]", when="reverse()", then="to_list() is [1]"),
        ],
        covers=["REQ-1"],
        files=["linked_list.py", "utils.py"],
        priority=1,
    )


def _bug(kind: str, location: str, tag: str) -> Bug:
    """Returns a bug whose fields all carry a tag, to find them in a prompt.

    Args:
        kind: The defect kind.
        location: File and function.
        tag: Text put in the evidence, cause and fix.

    Returns:
        The bug.
    """
    return Bug(
        kind=kind,
        location=location,
        evidence=f"EVIDENCE-{tag}",
        cause=f"CAUSE-{tag}",
        fix=f"FIX-{tag}",
    )


def _sections(prompt: str) -> dict[str, str]:
    """Returns the prompt split by its ``## `` headings.

    Args:
        prompt: A pass prompt.

    Returns:
        Heading (lower case, without ``## ``) to the text under it; the
        text before the first heading is under ``""``.
    """
    sections, name = {"": []}, ""
    for line in prompt.splitlines():
        if line.startswith("## "):
            name = line[3:].strip().lower()
            sections[name] = []
        else:
            sections[name].append(line)
    return {key: "\n".join(lines) for key, lines in sections.items()}


def _write(workspace, name: str, content: str) -> None:
    """Writes one file in the Coder's workspace.

    Args:
        workspace: The workspace directory.
        name: File name.
        content: File content.
    """
    path = workspace / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_ac_3_3_17_first_pass_prompt(task, spec, isolated_run, monkeypatch):
    _write(isolated_run, "linked_list.py", LINKED_LIST)
    _write(isolated_run, "big.py", BIG)
    _write(isolated_run.parent, "secret.txt", "SECRET_VALUE")
    outside = task.model_copy(update={"files": [*task.files, "../secret.txt"]})

    prompt = first_pass_prompt(outside, spec, ["linked_list.py", "big.py"])

    assert "Linked list" in prompt and spec.description in prompt
    assert task.description in prompt
    for criterion in task.acceptance_criteria:
        assert criterion.then in prompt
    assert LINKED_LIST in prompt
    assert "big.py" in prompt and BIG not in prompt
    assert "SECRET_VALUE" not in prompt
    assert "background" not in _sections(prompt)
    assert prompt.index(task.description) < prompt.index(LINKED_LIST)  # DEC-195

    monkeypatch.setattr(tools.file_io, "READ_MAX_CHARS", 20)
    _write(isolated_run, "linked_list.py", "x" * 50)
    prompt = first_pass_prompt(task, spec, ["linked_list.py"])
    assert "x" * 20 in prompt and "x" * 21 not in prompt
    assert "[truncated" in prompt


def test_ac_3_3_18_improvement_prompt(task, spec, isolated_run):
    _write(isolated_run, "linked_list.py", LINKED_LIST)
    high = _bug("logic_error", "linked_list.py: reverse", "HIGH")
    medium = _bug("missing_edge_case", "linked_list.py: search", "MEDIUM")
    low = _bug("style", "linked_list.py: LinkedList", "LOW")
    regression = _bug("crash", "linked_list.py: insert", "REGRESSION")
    evaluation = SelfEvaluationBase(
        items=[
            ItemVerdict(item="C1", verdict="bug", evidence="see bugs", bugs=[high]),
            ItemVerdict(item="E1", verdict="bug", evidence="see bugs", bugs=[medium]),
            ItemVerdict(item="E10", verdict="bug", evidence="see bugs", bugs=[low]),
        ]
    )

    prompt = improvement_prompt(
        task,
        spec,
        ["linked_list.py"],
        evaluation,
        regressions=[regression],
        discarded_explanation="DISCARDED-EXPLANATION",
    )

    sections = _sections(prompt)
    to_fix, pending = sections["to fix"], sections["pending"]
    for tag in ("HIGH", "MEDIUM", "REGRESSION"):
        for part in ("EVIDENCE", "CAUSE", "FIX"):
            assert f"{part}-{tag}" in to_fix
    assert "linked_list.py: reverse" in to_fix and "linked_list.py: insert" in to_fix
    assert "DISCARDED-EXPLANATION" in to_fix
    assert "LOW" not in to_fix
    assert "FIX-LOW" in pending and "only if trivial and safe" in pending
    assert prompt.index("## To fix") < prompt.index("## Pending")
    assert LINKED_LIST in prompt


def test_ac_3_3_19_correction_prompt(task, spec, isolated_run):
    _write(isolated_run, "linked_list.py", LINKED_LIST)
    failing = FailedTest(name="test_reverse_single", criterion="C1: reverse of [1]")
    history = [
        ReviewRecord(
            review=review,
            explanation=f"EXPLANATION-{review}",
            high=0,
            medium=review,
            low=0,
            version=review - 1,
            tests_passed=3,
            tests_failed=1,
            failed_tests=[failing],
        )
        for review in (1, 2)
    ]
    issue = Issue(
        severity="High",
        location="test_task_1.py::test_reverse_single",
        description="ERROR-assert [] == [1]",
        fix="FIX-keep the last node",
        source="test",
        criterion="CRITERION-reverse of [1]",
        test_code=TEST_SOURCE,
    )
    report = QAReport(task_id="task_1", issues=[issue], tests_passed=3, tests_failed=1)
    pending = [
        _bug("missing_edge_case", "linked_list.py: search", "MEDIUM"),
        _bug("docstring", "linked_list.py: LinkedList", "LOW"),
    ]
    task = task.model_copy(update={"history": history})

    prompt = correction_prompt(task, spec, ["linked_list.py"], report, pending)

    sections = _sections(prompt)
    to_fix, background = sections["to fix"], sections["background"]
    for part in ("test_reverse_single", "CRITERION-reverse of [1]", "ERROR-assert [] == [1]",
                 "FIX-keep the last node", TEST_SOURCE.strip()):
        assert part in to_fix
    for review in (1, 2):
        assert f"Review {review}" in background
        assert f"EXPLANATION-{review}" in background
        assert f"{review} Medium" in background
    assert "3 passed, 1 failed" in background
    assert "test_reverse_single fails for the 3rd time" in prompt
    assert "FIX-MEDIUM" in sections["pending"] and "FIX-LOW" in sections["pending"]
    assert "FIX-MEDIUM" not in to_fix
    assert prompt.index("## To fix") < prompt.index("## Pending")
    assert LINKED_LIST in prompt


def test_ac_3_3_19_history_in_state(task):
    record = ReviewRecord(
        review=1, explanation="e", version=0, tests_passed=2, tests_failed=0
    )
    assert task.history == []
    assert (record.high, record.medium, record.low) == (None, None, None)
    restored = TaskState.model_validate_json(
        task.model_copy(update={"history": [record]}).model_dump_json()
    )
    assert restored.history == [record]


def test_ac_3_3_20_passes_use_memory(task, spec, isolated_run, monkeypatch):
    monkeypatch.setattr(memory, "MEMORY_TOP_K", 20)
    store_memory("PLANTED-MEMORY: linked lists insert at the head")
    window = SlidingWindowBuffer(max_turns=10)
    window.add_turn([{"role": "user", "content": "WINDOW-TURN"}, {"role": "assistant", "content": "ok"}])
    evaluation = SelfEvaluationBase(
        items=[ItemVerdict(item="E1", verdict="bug", evidence="b",
                           bugs=[_bug("missing_edge_case", "linked_list.py: search", "M")])]
    )
    report = QAReport(
        task_id="task_1",
        issues=[Issue(severity="High", location="test_task_1.py::test_x", description="d",
                      fix="f", source="test")],
        tests_passed=1,
        tests_failed=1,
    )
    prompts = []
    model = ScriptedChatModel(
        successful_task(LINKED_LIST, "linked_list.py") * 3
    )

    for build in (
        lambda: first_pass_prompt(task, spec, []),
        lambda: improvement_prompt(task, spec, ["linked_list.py"], evaluation),
        lambda: correction_prompt(task, spec, ["linked_list.py"], report, []),
    ):
        prompts.append(build())
        turns = len(window._turns)
        run_agent(prompts[-1], window, model)
        assert len(window._turns) == turns + 1

    assert len(model.calls) == 3 * 4
    for call in model.calls:
        text = all_text(call)
        assert MEMORY_HEADING in text and "PLANTED-MEMORY" in text
        assert "WINDOW-TURN" in text
    stored = memory._collection.get()["documents"]
    for prompt in prompts:
        assert prompt in stored

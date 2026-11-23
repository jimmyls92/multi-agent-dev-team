"""Tests of the Coder's self-evaluation and the reflect node (Lab 3.3, T4, T6).

Covers spec `lab_3_3_a2a_loop` AC-3.3-12 .. AC-3.3-16 and AC-3.3-21 ..
AC-3.3-26 (DEC-171, DEC-172, DEC-173, DEC-182, DEC-183, DEC-193,
DEC-196), with a fake evaluation model, a fake Coder and the linked-list
task; AC-3.3-41 uses the real model and runs only with ``--run-llm``.
"""

import logging
import subprocess
import sys

import pytest
from langgraph.runtime import Runtime

import memory
from agents import coder_reflection
from agents.coder_agent import CoderRunContext
from agents.coder_reflection import (
    EVALUATION_ATTEMPTS,
    KIND_SEVERITY,
    RUBRIC_ITEMS,
    BugCounts,
    best_version,
    evaluate_version,
    make_reflect_node,
)
from memory import SlidingWindowBuffer
from orchestration.state import (
    CoderResult,
    ProjectState,
    StepRecord,
    TaskCriterion,
    TaskSpec,
    TaskState,
)
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
        The AI message calling the ``SelfEvaluation`` tool, one field per
        item (DEC-200).
    """
    fields = {i["item"]: {k: v for k, v in i.items() if k != "item"} for i in items}
    return tool_call_reply("SelfEvaluation", fields, call_id)


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
        ("missing-item", "Field required"),
        ("unknown-criterion", "Extra inputs are not permitted"),
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


def test_ac_3_3_21_any_bug_needs_improvement(task):
    model = ScriptedChatModel([
        _reply(_items({"E9": [_bug("missing_type_annotation")], "E10": [_bug("style")]}), "e0"),
        _reply(_items(), "e1"),
    ])

    low_only = evaluate_version(task, {"linked_list.py": LINKED_LIST}, model)
    clean = evaluate_version(task, {"linked_list.py": LINKED_LIST}, model)

    assert low_only.counts() == BugCounts(high=0, medium=0, low=2)
    assert low_only.needs_improvement() is True
    assert clean.counts() == BugCounts(high=0, medium=0, low=0)
    assert clean.needs_improvement() is False


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
    assert len(model.calls) == EVALUATION_ATTEMPTS == 2
    assert "critique unavailable" in caplog.text


# --- The reflect node (T6: AC-3.3-16, AC-3.3-21 .. AC-3.3-26, DEC-196) -------


V0 = "class LinkedList:\n    VERSION = 0\n"
V1 = "class LinkedList:\n    VERSION = 1\n"
V2 = "class LinkedList:\n    VERSION = 2\n"


class FakeCoder:
    """Replaces ``run_agent``: each pass writes given files and returns a result.

    Attributes:
        passes: Files each pass writes, in order; a pass given as an
            exception raises it instead.
        prompts: The prompt of every pass run.
        seen: The content of ``linked_list.py`` on disk when each pass
            started.
    """

    def __init__(self, workspace, passes: list[dict[str, str] | Exception]):
        """Keeps the workspace and the passes to replay.

        Args:
            workspace: The Coder's workspace directory.
            passes: Files written by each pass, or an exception to raise.
        """
        self.workspace = workspace
        self.passes = list(passes)
        self.prompts: list[str] = []
        self.seen: list[str | None] = []

    def __call__(self, prompt: str, window, model=None) -> CoderResult:
        """Runs the next pass: writes its files and returns its result.

        Args:
            prompt: The pass prompt.
            window: The Coder's window; unused.
            model: The Coder's model; unused.

        Returns:
            A ``success`` result whose steps write the pass's files.

        Raises:
            Exception: The pass's exception, if it was given one.
        """
        self.prompts.append(prompt)
        current = self.workspace / "linked_list.py"
        self.seen.append(current.read_text() if current.exists() else None)
        files = self.passes.pop(0)
        if isinstance(files, Exception):
            raise files
        number = len(self.prompts)
        for name, content in files.items():
            (self.workspace / name).write_text(content)
        return _result(files, f"EXPLANATION-v{number}")


def _result(files: dict[str, str], explanation: str, status: str = "success") -> CoderResult:
    """Returns a CoderResult whose steps write the given files.

    Args:
        files: File name to content.
        explanation: The result's explanation.
        status: The result's status.

    Returns:
        The result.
    """
    steps = [
        StepRecord(iteration=k, action="write_file", action_input={"path": name, "content": content})
        for k, (name, content) in enumerate(files.items(), start=1)
    ]
    return CoderResult(status=status, explanation=explanation, steps=steps,
                       main_file="linked_list.py", code=files.get("linked_list.py", ""))


def _state(task: TaskSpec, workspace, status: str = "success") -> ProjectState:
    """Returns a state whose task is in progress after its first pass wrote v0.

    Args:
        task: The linked-list task.
        workspace: The Coder's workspace; v0 is written there.
        status: Status of the first pass's result.

    Returns:
        The state.
    """
    (workspace / "linked_list.py").write_text(V0)
    v0 = _result({"linked_list.py": V0}, "EXPLANATION-v0", status)
    current = TaskState(**task.model_dump(), status="in_progress", result=v0)
    return ProjectState(requirement="r", tasks=[current], code={"linked_list.py": V0})


def _reflect(state: ProjectState, model, coder, monkeypatch, rounds: int = 1) -> dict:
    """Runs the reflect node once with a fake Coder.

    Args:
        state: State before the node.
        model: Fake evaluation model.
        coder: The fake Coder.
        monkeypatch: Pytest's monkeypatch fixture.
        rounds: ``REFLECTION_MAX_ROUNDS``.

    Returns:
        The node's update.
    """
    monkeypatch.setattr(coder_reflection, "run_agent", coder)
    monkeypatch.setenv("REFLECTION_MAX_ROUNDS", str(rounds))
    return make_reflect_node(model)(state, Runtime(context=CoderRunContext()))


def _sent(update: dict) -> TaskState:
    """Returns the reviewed task of a node update.

    Args:
        update: The reflect node's update.

    Returns:
        The task, with the result to send and its reflection.
    """
    [task] = update["tasks"]
    return task


def test_ac_3_3_16_unavailable_sends_v0(task, isolated_run, monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    model = ScriptedChatModel([_reply(_invalid("missing-item"), "e1"), _reply(_invalid("criterion-na"), "e2")])
    coder = FakeCoder(isolated_run, [])

    update = _reflect(_state(task, isolated_run), model, coder, monkeypatch)

    sent = _sent(update)
    assert len(model.calls) == EVALUATION_ATTEMPTS
    assert coder.prompts == []
    assert sent.result.explanation == "EXPLANATION-v0"
    assert (sent.reflection.version, sent.reflection.high) == (0, None)
    assert "critique unavailable" in caplog.text


def test_ac_3_3_21_low_only_improved(task, isolated_run, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    model = ScriptedChatModel([
        _reply(_items({"E9": [_bug("missing_type_annotation")], "E10": [_bug("style")]}), "e0"),
        _reply(_items(), "e1"),
    ])
    coder = FakeCoder(isolated_run, [{"linked_list.py": V1}])

    update = _reflect(_state(task, isolated_run), model, coder, monkeypatch)

    sent = _sent(update)
    assert len(coder.prompts) == 1
    assert (isolated_run / "linked_list.py").read_text() == V1
    assert sent.result.explanation == "EXPLANATION-v1"
    assert (sent.reflection.version, sent.reflection.low) == (1, 0)
    for part in ("E9", "E10", "v0: 0 High, 0 Medium, 2 Low", "sent v1"):
        assert part in caplog.text


def test_ac_3_3_21_clean_sent_unchanged(task, isolated_run, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    model = ScriptedChatModel([_reply(_items())])
    coder = FakeCoder(isolated_run, [])

    sent = _sent(_reflect(_state(task, isolated_run), model, coder, monkeypatch))

    assert coder.prompts == []
    assert (isolated_run / "linked_list.py").read_text() == V0
    assert sent.result.explanation == "EXPLANATION-v0"
    assert (sent.reflection.version, sent.reflection.low) == (0, 0)
    assert "no improvement needed" in caplog.text


def test_ac_3_3_22_improvement_sent(task, isolated_run, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    model = ScriptedChatModel([_reply(_items({"E2": [_bug()]}), "e0"), _reply(_items(), "e1")])
    coder = FakeCoder(isolated_run, [{"linked_list.py": V1}])

    update = _reflect(_state(task, isolated_run), model, coder, monkeypatch)

    sent = _sent(update)
    assert len(coder.prompts) == 1
    assert "the loop drops the last node" in coder.prompts[0]
    assert (isolated_run / "linked_list.py").read_text() == V1
    assert sent.result.explanation == "EXPLANATION-v1"
    assert update["code"]["linked_list.py"] == V1
    assert (sent.reflection.version, sent.reflection.high) == (1, 0)
    for part in ("E2", "linked_list.py: LinkedList.reverse", "the loop drops the last node",
                 "v0: 1 High, 0 Medium, 0 Low", "v1: 0 High, 0 Medium, 0 Low", "sent v1"):
        assert part in caplog.text


def test_ac_3_3_23_worse_improvement_restored(task, isolated_run, monkeypatch):
    model = ScriptedChatModel([
        _reply(_items({"E1": [_bug("missing_edge_case")]}), "e0"),
        _reply(_items({"E2": [_bug()]}), "e1"),
    ])
    coder = FakeCoder(isolated_run, [{"linked_list.py": V1, "helper.py": "X = 1\n"}])

    update = _reflect(_state(task, isolated_run), model, coder, monkeypatch)

    sent = _sent(update)
    assert sorted(p.name for p in isolated_run.iterdir()) == ["linked_list.py"]
    assert (isolated_run / "linked_list.py").read_text() == V0
    assert sent.result.explanation == "EXPLANATION-v0"
    assert sent.reflection.version == 0
    assert "helper.py" not in update["code"]


def test_ac_3_3_24_regressions_passed_on(task, isolated_run, monkeypatch):
    regression = _bug("logic_error", "linked_list.py: insert")
    regression["cause"] = "REGRESSION-CAUSE"
    model = ScriptedChatModel([
        _reply(_items({"E1": [_bug("missing_edge_case")]}), "e0"),
        _reply(_items({"C0": [regression]}), "e1"),
        _reply(_items({"E1": [_bug("missing_edge_case")]}), "e2"),
    ])
    coder = FakeCoder(isolated_run, [{"linked_list.py": V1}, {"linked_list.py": V2}])

    sent = _sent(_reflect(_state(task, isolated_run), model, coder, monkeypatch, rounds=2))

    assert len(coder.prompts) == 2
    assert coder.seen == [V0, V0]
    assert "REGRESSION-CAUSE" in coder.prompts[1]
    assert "EXPLANATION-v1" in coder.prompts[1]
    assert sent.reflection.version == 2


def test_ac_3_3_25_tie_goes_to_improved(task, isolated_run, monkeypatch):
    model = ScriptedChatModel([
        _reply(_items({"E1": [_bug("missing_edge_case")]}), "e0"),
        _reply(_items({"E3": [_bug("unclear_error")]}), "e1"),
    ])
    coder = FakeCoder(isolated_run, [{"linked_list.py": V1}])

    sent = _sent(_reflect(_state(task, isolated_run), model, coder, monkeypatch))

    assert sent.result.explanation == "EXPLANATION-v1"
    assert (isolated_run / "linked_list.py").read_text() == V1


def test_ac_3_3_26_limit_pass_evaluated(task, isolated_run, monkeypatch):
    model = ScriptedChatModel([_reply(_items())])
    coder = FakeCoder(isolated_run, [])

    sent = _sent(_reflect(_state(task, isolated_run, "max_iterations"), model, coder, monkeypatch))

    assert V0 in _text(model.calls[0])
    assert sent.result.status == "max_iterations"
    assert sent.reflection.version == 0


def test_dec_196_unchanged_improvement_not_evaluated(task, isolated_run, monkeypatch):
    model = ScriptedChatModel([_reply(_items({"E2": [_bug()]}))])
    coder = FakeCoder(isolated_run, [{"linked_list.py": V0}])

    sent = _sent(_reflect(_state(task, isolated_run), model, coder, monkeypatch))

    assert len(model.calls) == 1
    assert sent.reflection.version == 0
    assert sent.reflection.high == 1


def test_dec_196_improved_unavailable_sends_improved(task, isolated_run, monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    model = ScriptedChatModel([
        _reply(_items({"E2": [_bug()]}), "e0"),
        _reply(_invalid("missing-item"), "e1"),
        _reply(_invalid("missing-item"), "e2"),
    ])
    coder = FakeCoder(isolated_run, [{"linked_list.py": V1}, {"linked_list.py": V2}])

    sent = _sent(_reflect(_state(task, isolated_run), model, coder, monkeypatch, rounds=2))

    assert len(coder.prompts) == 1
    assert (isolated_run / "linked_list.py").read_text() == V1
    assert sent.result.explanation == "EXPLANATION-v1"
    assert (sent.reflection.version, sent.reflection.high) == (1, None)
    assert "critique unavailable" in caplog.text


def test_dec_196_failed_improvement_restores_best(task, isolated_run, monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    model = ScriptedChatModel([_reply(_items({"E2": [_bug()]}))])

    class HalfWritten(FakeCoder):
        """A pass that writes a file and then fails."""

        def __call__(self, prompt, window, model=None):
            """Writes a broken file, then raises like an API error.

            Raises:
                RuntimeError: Always.
            """
            (self.workspace / "linked_list.py").write_text("broken")
            raise RuntimeError("API down")

    sent = _sent(_reflect(_state(task, isolated_run), model, HalfWritten(isolated_run, []), monkeypatch))

    assert (isolated_run / "linked_list.py").read_text() == V0
    assert sent.result.explanation == "EXPLANATION-v0"
    assert "API down" in caplog.text


@pytest.mark.parametrize("statuses", [("done",), ("in_progress", "in_progress")], ids=["none", "two"])
def test_dec_196_one_task_in_progress(task, isolated_run, monkeypatch, statuses):
    state = _state(task, isolated_run)
    tasks = [state.tasks[0].model_copy(update={"task_id": f"task_{k}", "status": s})
             for k, s in enumerate(statuses, start=1)]
    model = ScriptedChatModel([])

    update = _reflect(state.model_copy(update={"tasks": tasks}), model, FakeCoder(isolated_run, []), monkeypatch)

    assert update["error"]
    assert "tasks" not in update
    assert model.calls == []


PLANTED = '''class Node:
    def __init__(self, value, next=None):
        self.value = value
        self.next = next


class LinkedList:
    def __init__(self):
        self.head = None

    def insert(self, value):
        self.head = Node(value, self.head)

    def search(self, value):
        node = self.head
        while node is not None:
            if node.value == value:
                return True
            node = node.next
        return False

    def to_list(self):
        values, node = [], self.head
        while node is not None:
            values.append(node.value)
            node = node.next
        return values

    def reverse(self):
        previous, current = None, self.head
        if current is not None:
            following = current.next
            current.next = previous
            previous, current = current, following
        self.head = previous
'''


@pytest.mark.llm
@pytest.mark.timeout(900)
def test_ac_3_3_41_live_planted_bug(task, isolated_run, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setenv("REFLECTION_MAX_ROUNDS", "1")
    reverse_task = task.model_copy(update={
        "description": "Create linked_list.py with a LinkedList class: insert at the head, search, "
        "to_list and reverse (reverses the list in place).",
        "acceptance_criteria": [
            *task.acceptance_criteria,
            TaskCriterion(given="a list whose to_list() is [1, 2, 3]", when="reverse()",
                          then="to_list() is [3, 2, 1]"),
        ],
    })
    (isolated_run / "linked_list.py").write_text(PLANTED)
    v0 = CoderResult(status="success", explanation="Wrote linked_list.py.", main_file="linked_list.py",
                     code=PLANTED, steps=[StepRecord(iteration=1, action="write_file",
                                                     action_input={"path": "linked_list.py", "content": PLANTED})])
    current = TaskState(**reverse_task.model_dump(), status="in_progress", result=v0)
    state = ProjectState(requirement="r", tasks=[current], code={"linked_list.py": PLANTED})

    update = make_reflect_node()(state, Runtime(context=CoderRunContext()))

    [sent] = update["tasks"]
    critiques = [r.getMessage() for r in caplog.records if "critique v0" in r.getMessage()]
    assert any("reverse" in c and (" High " in c or " Medium " in c) for c in critiques), critiques
    assert sent.reflection.improvements == 1
    check = subprocess.run(
        [sys.executable, "-c", "from linked_list import LinkedList\nl = LinkedList()\n"
         "for v in (3, 2, 1):\n    l.insert(v)\nl.reverse()\nprint(l.to_list())"],
        cwd=isolated_run, capture_output=True, text=True, timeout=10,
    )
    # The last line is the check's own print; the module may print more.
    assert check.stdout.strip().splitlines()[-1:] == ["[3, 2, 1]"], check.stdout + check.stderr

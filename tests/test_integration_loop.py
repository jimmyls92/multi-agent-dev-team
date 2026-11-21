"""Integration tests of the Coder-QA loop through ``run()`` (Lab 3.3, T7).

Covers spec `lab_3_3_a2a_loop` AC-3.3-29 .. AC-3.3-34 and AC-3.3-36
(DEC-163, DEC-164, DEC-168, DEC-169, DEC-170, DEC-176, DEC-178, DEC-197,
DEC-198), with a fake PM, a fake
Coder, a clean fake evaluation and a fake QA; AC-3.3-31 runs the real QA
with a fake test-writing model. AC-3.3-40 runs the whole team with the
real models and only runs with ``--run-llm`` (DEC-199).
"""

import logging
import time

import pytest

import agents.coder_agent as coder_agent
import agents.coder_reflection as coder_reflection
import agents.qa_agent as qa_agent
from agents.coder_reflection import SelfEvaluationBase
from agents.qa_agent import QASettings, run_qa
from orchestration.graph import run
from orchestration.state import CoderResult, Issue, QAReport, StepRecord, TaskSpec
from tests.fakes import ScriptedChatModel
from tests.test_pm_agent import REQUIREMENT, _spec_reply, _tasks_reply
from tests.test_qa_agent import LINKED_LIST, TAIL_APPEND, VALID_DRAFT, _draft_reply, _review_reply

FIX = "In insert, use self.items.insert(0, value) so new values go to the head."


def _task_draft(k: int, files: list[str] | None = None) -> dict:
    """Returns a PM task draft covering every spec criterion when ``k`` is 1.

    Args:
        k: Task number.
        files: Planned files; ``["file_<k>.py"]`` by default.

    Returns:
        The task draft.
    """
    return {
        "title": f"Task {k}",
        "description": f"Do part {k}.",
        "acceptance_criteria": [{"given": "the app runs", "when": f"step {k}", "then": "it works"}],
        "covers": ["REQ-1", "REQ-2", "REQ-3"] if k == 1 else ["REQ-1"],
        "files": files or [f"file_{k}.py"],
    }


def _pm(*drafts: dict) -> ScriptedChatModel:
    """Returns a fake PM that plans the given tasks, plus a second one if only one is given.

    The PM plans at least two tasks; the extra ``task_2`` is approved at
    once by ``FakeQA`` unless a test scripts it.

    Args:
        *drafts: Task drafts.

    Returns:
        The PM's fake model.
    """
    drafts = list(drafts) if len(drafts) > 1 else [*drafts, _task_draft(2)]
    return ScriptedChatModel([_spec_reply(), _tasks_reply(drafts)])


def _result(path: str, content: str, explanation: str) -> CoderResult:
    """Returns a successful CoderResult whose one step writes a file.

    Args:
        path: File written.
        content: Its content.
        explanation: The result's explanation.

    Returns:
        The result.
    """
    step = StepRecord(iteration=1, action="write_file", action_input={"path": path, "content": content})
    return CoderResult(status="success", code=content, explanation=explanation, main_file=path, steps=[step])


class FakeCoder:
    """Replaces the Coder's ReACT pass: writes the task's first file.

    Attributes:
        prompts: The prompt of every pass.
    """

    def __init__(self, workspace, content=lambda prompt: "X = 1\n"):
        """Keeps the workspace and how each pass's content is chosen.

        Args:
            workspace: The Coder's workspace.
            content: Returns the file content for a prompt.
        """
        self.workspace = workspace
        self.content = content
        self.prompts: list[str] = []

    def __call__(self, prompt: str, window, model=None) -> CoderResult:
        """Writes the planned file named in the prompt and returns the result.

        Args:
            prompt: The pass prompt.
            window: The Coder's window; unused.
            model: The Coder's model; unused.

        Returns:
            A successful result.
        """
        self.prompts.append(prompt)
        path = prompt.split("Planned files: ", 1)[1].split(",")[0].split("\n")[0].strip()
        content = self.content(prompt)
        (self.workspace / path).write_text(content)
        return _result(path, content, f"pass {len(self.prompts)}")


class FakeQA:
    """Replaces the QA's work: returns the next scripted report of each task.

    Attributes:
        calls: Task IDs reviewed, in order.
    """

    def __init__(self, scripts: dict[str, list]):
        """Keeps the scripted reports.

        Args:
            scripts: Task ID to its reports; the last one repeats. A task
                without a script is approved.
        """
        self.scripts = scripts
        self.calls: list[str] = []

    async def __call__(self, task: TaskSpec) -> QAReport:
        """Returns the task's next report.

        Args:
            task: The task to review.

        Returns:
            A report built by the scripted function for the task.
        """
        self.calls.append(task.task_id)
        script = self.scripts.setdefault(task.task_id, [approved])
        build = script.pop(0) if len(script) > 1 else script[0]
        return build(task.task_id)


def failing(task_id: str) -> QAReport:
    """Returns an unapproved report with one failing test.

    Args:
        task_id: The task reviewed.

    Returns:
        One test passed, one failed with its fix.
    """
    issue = Issue(severity="High", location="test_task.py::test_order", description="assert [1] == [2]",
                  fix=FIX, source="test", criterion="C0")
    return QAReport(task_id=task_id, issues=[issue], tests_passed=1, tests_failed=1)


def approved(task_id: str) -> QAReport:
    """Returns an approved report.

    Args:
        task_id: The task reviewed.

    Returns:
        Two tests passed, no issues.
    """
    return QAReport(task_id=task_id, tests_passed=2)


def qa_broken(task_id: str) -> QAReport:
    """Returns a report holding only a ``qa`` issue: the QA could not work.

    Args:
        task_id: The task reviewed.

    Returns:
        An unapproved report with no tests run.
    """
    issue = Issue(severity="High", location="QA", description="QA step 'MCP read' failed",
                  fix="Nothing for the Coder to change.", source="qa")
    return QAReport(task_id=task_id, issues=[issue])


@pytest.fixture
def loop(isolated_run, monkeypatch):
    """Gives the loop a fake Coder and a clean self-evaluation.

    Args:
        isolated_run: The temporary workspace.
        monkeypatch: Pytest's monkeypatch fixture.

    Returns:
        The fake Coder.
    """
    coder = FakeCoder(isolated_run)
    monkeypatch.setattr(coder_agent, "run_agent", coder)
    monkeypatch.setattr(coder_reflection, "run_agent", coder)
    monkeypatch.setattr(coder_reflection, "evaluate_version", lambda *a, **k: SelfEvaluationBase(items=[]))
    return coder


def _intents(state, task_id: str = "task_1") -> list[tuple[str, str]]:
    """Returns each A2A message about one task as (intent, correlation id).

    Args:
        state: A final state.
        task_id: The task whose messages are returned.

    Returns:
        The messages in send order.
    """
    return [(m.intent, m.correlation_id) for m in state.messages if m.payload["task_id"] == task_id]


def test_ac_3_3_29_loop_success(loop):
    qa = FakeQA({"task_1": [failing, approved]})

    final = run(REQUIREMENT, pm_model=_pm(_task_draft(1)), coder_model=ScriptedChatModel([]), qa_review=qa)

    intents = _intents(final)
    assert [i for i, _ in intents] == ["review_request", "fix_instruction", "review_request", "approved"]
    assert intents[0][1] == intents[1][1] != intents[2][1] == intents[3][1]
    task = final.tasks[0]
    assert (task.status, task.reviews) == ("done", 2)
    assert task.qa_report.approved
    assert final.outcome == "success"
    assert len(loop.prompts) == 3
    assert FIX in loop.prompts[1]


@pytest.mark.parametrize(("env", "limit"), [(None, 5), ("3", 3)], ids=["default", "three"])
def test_ac_3_3_30_loop_max_iterations(loop, monkeypatch, env, limit):
    if env is None:
        monkeypatch.delenv("QA_MAX_ITERATIONS", raising=False)
    else:
        monkeypatch.setenv("QA_MAX_ITERATIONS", env)
    qa = FakeQA({"task_1": [failing]})

    final = run(REQUIREMENT, pm_model=_pm(_task_draft(1)), coder_model=ScriptedChatModel([]), qa_review=qa)

    intents = [i for i, _ in _intents(final)]
    assert intents.count("review_request") == limit
    assert intents[-1] == "unresolved"
    assert intents.count("fix_instruction") == limit - 1
    last = [m for m in final.messages if m.payload["task_id"] == "task_1"][-1]
    assert last.payload["reason"] == "review limit reached"
    assert last.payload["report"]["issues"][0]["location"] == "test_task.py::test_order"
    task = final.tasks[0]
    assert (task.status, task.reviews) == ("failed", limit)
    assert qa.calls.count("task_1") == limit
    assert final.outcome == "unresolved"


@pytest.mark.timeout(120)
def test_ac_3_3_31_feedback_drives_revision(isolated_run, monkeypatch, tmp_path):
    coder = FakeCoder(isolated_run, lambda prompt: LINKED_LIST if FIX in prompt else TAIL_APPEND)
    monkeypatch.setattr(coder_agent, "run_agent", coder)
    monkeypatch.setattr(coder_reflection, "run_agent", coder)
    monkeypatch.setattr(coder_reflection, "evaluate_version", lambda *a, **k: SelfEvaluationBase(items=[]))
    qa_model = ScriptedChatModel([
        _draft_reply(VALID_DRAFT, "draft_1"),
        _review_reply({"fixes": [{"failure": 0, "fix": FIX}]}),
        _draft_reply(VALID_DRAFT, "draft_2"),
    ])
    settings = QASettings(workspace_dir=tmp_path / "workspace_qa", model="fake", max_attempts=2, test_timeout=2)
    log = (tmp_path / "server.log").open("w")
    draft = {
        "title": "Implement a linked list",
        "description": "Create linked_list.py with a LinkedList class: insert at the head, search and to_list.",
        "acceptance_criteria": [
            {"given": "an empty list", "when": "insert(5)", "then": "search(5) is True"},
            {"given": "a list built with insert(1) then insert(2)", "when": "insert(3)",
             "then": "to_list() is [3, 2, 1]"},
        ],
        "covers": ["REQ-1", "REQ-2", "REQ-3"],
        "files": ["linked_list.py"],
    }

    def review(task):
        """Runs the real QA on the linked list with the fake test-writing model."""
        if task.task_id != "task_1":
            return approved(task.task_id)
        return run_qa(task, model=qa_model, settings=settings, coder_dir=isolated_run, errlog=log)

    final = run(REQUIREMENT, pm_model=_pm(draft), coder_model=ScriptedChatModel([]), qa_review=review)
    log.close()

    task = final.tasks[0]
    first, second = task.history
    [issue] = [m for m in final.messages if m.intent == "fix_instruction"][0].payload["report"]["issues"]
    assert issue["source"] == "test" and "to_list() is [3, 2, 1]" in issue["criterion"]
    assert FIX in coder.prompts[1]
    assert (first.tests_failed, second.tests_failed, second.tests_passed) == (1, 0, 2)
    assert (task.status, task.reviews) == ("done", 2)
    assert len(_intents(final)) == 4
    assert (isolated_run / "linked_list.py").read_text() == LINKED_LIST


def test_ac_3_3_32_qa_failure_retry(loop):
    qa = FakeQA({"task_1": [qa_broken, approved]})

    final = run(REQUIREMENT, pm_model=_pm(_task_draft(1)), coder_model=ScriptedChatModel([]), qa_review=qa)

    task = final.tasks[0]
    assert qa.calls[:2] == ["task_1", "task_1"]
    assert len(loop.prompts) == 2
    assert (task.status, task.reviews) == ("done", 1)
    assert [i for i, _ in _intents(final)] == ["review_request", "approved"]


def test_ac_3_3_32_qa_failure_twice(loop):
    qa = FakeQA({"task_1": [qa_broken]})

    final = run(REQUIREMENT, pm_model=_pm(_task_draft(1)), coder_model=ScriptedChatModel([]), qa_review=qa)

    task = final.tasks[0]
    assert qa.calls.count("task_1") == 2
    assert len(loop.prompts) == 2
    assert task.status == "failed"
    last = [m for m in final.messages if m.payload["task_id"] == "task_1"][-1]
    assert (last.intent, last.payload["reason"]) == ("unresolved", "the QA could not review it")
    assert final.outcome == "unresolved"


def test_ac_3_3_33_protocol_error(loop, monkeypatch, caplog):
    caplog.set_level(logging.ERROR)
    real = qa_agent._verdict_message

    def wrong_id(request, intent, payload):
        """Builds the verdict, with a wrong correlation id for task_1."""
        message = real(request, intent, payload)
        if payload["task_id"] == "task_1":
            return message.model_copy(update={"correlation_id": "wrong-id"})
        return message

    monkeypatch.setattr(qa_agent, "_verdict_message", wrong_id)
    qa = FakeQA({"task_1": [approved], "task_2": [approved]})

    final = run(REQUIREMENT, pm_model=_pm(_task_draft(1), _task_draft(2)),
                coder_model=ScriptedChatModel([]), qa_review=qa)

    task_1, task_2 = final.tasks
    assert "wrong-id" in caplog.text
    assert task_1.status == "failed"
    assert "protocol" in task_1.qa_report.issues[0].description.lower()
    assert task_2.status == "done"
    assert final.error == ""
    assert final.outcome == "unresolved"
    assert all(m.correlation_id != "wrong-id" for m in final.messages)


def test_ac_3_3_34_next_task_after_failure(loop, monkeypatch):
    monkeypatch.setenv("QA_MAX_ITERATIONS", "2")
    qa = FakeQA({"task_1": [failing], "task_2": [approved]})

    final = run(REQUIREMENT, pm_model=_pm(_task_draft(1), _task_draft(2)),
                coder_model=ScriptedChatModel([]), qa_review=qa)

    task_1, task_2 = final.tasks
    assert (task_1.status, task_1.reviews) == ("failed", 2)
    assert (task_2.status, task_2.reviews) == ("done", 1)
    assert final.outcome == "unresolved"


def test_ac_3_3_36_out_of_time(loop, monkeypatch):
    monkeypatch.setenv("RUN_TIMEOUT", "1")
    real_pass = loop.__call__

    def slow_first_task(prompt, window, model=None):
        """Runs the fake pass; task_1's first pass takes 2 s."""
        if "Task task_1:" in prompt and not loop.prompts:
            time.sleep(2)
        return real_pass(prompt, window, model)

    monkeypatch.setattr(coder_agent, "run_agent", slow_first_task)
    qa = FakeQA({})

    final = run(REQUIREMENT, pm_model=_pm(_task_draft(1), _task_draft(2), _task_draft(3)),
                coder_model=ScriptedChatModel([]), qa_review=qa)

    task_1, task_2, task_3 = final.tasks
    assert qa.calls == []
    assert [t.status for t in final.tasks] == ["failed", "failed", "failed"]
    assert {t.closed_reason for t in final.tasks} == {"out of time"}
    assert final.outcome == "unresolved"
    assert final.error == ""
    assert task_1.result is not None and "file_1.py" in final.code
    assert final.deadline_at and any("out of time" in note for note in final.progress)
    assert "out of time" in final.final_report()


LINKED_LIST_REQUIREMENT = (
    "Implement a Python module that contains a linked list class with insert, delete, search, "
    "and reverse methods. All methods must be covered by tests."
)


@pytest.mark.llm
@pytest.mark.timeout(1800)
def test_ac_3_3_40_linked_list_demo(isolated_run, tmp_path, monkeypatch):
    qa_dir = tmp_path / "workspace_qa"
    monkeypatch.setenv("QA_WORKSPACE_DIR", str(qa_dir))

    final = run(LINKED_LIST_REQUIREMENT)

    assert final.outcome == "success", final.final_report() or final.error
    tests = "\n".join(path.read_text() for path in qa_dir.rglob("test_*.py"))
    for method in ("insert", "delete", "search", "reverse"):
        assert f".{method}(" in tests, method
    requests = {m.correlation_id for m in final.messages if m.intent == "review_request"}
    approvals = [m.correlation_id for m in final.messages if m.intent == "approved"]
    assert approvals and set(approvals) <= requests

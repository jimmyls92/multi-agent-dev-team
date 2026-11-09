"""Tests for the PM Agent (spec `lab_2_1_pm_agent`, AC-2.1-5, AC-2.1-6)."""

from agents.pm_agent import consolidate_tasks
from orchestration.state import TaskSpec


def _task(k: int) -> TaskSpec:
    """Returns a planned task whose fields all carry its number.

    Args:
        k: Task number; gives ``task_k``, ``REQ-k``, ``file_k.py`` and
            priority ``k``.

    Returns:
        The task.
    """
    return TaskSpec(
        task_id=f"task_{k}",
        title=f"Title {k}",
        description=f"Description {k}",
        acceptance_criteria=[{"given": f"given {k}", "when": f"when {k}", "then": f"then {k}"}],
        covers=[f"REQ-{k}"],
        files=[f"file_{k}.py"],
        priority=k,
    )


def test_ac_2_1_5_consolidates_to_eight():
    originals = [_task(k) for k in range(1, 12)]

    tasks = consolidate_tasks(originals)

    assert len(tasks) == 8
    assert [t.merged_from for t in tasks] == [
        ["task_1", "task_2"],
        ["task_3", "task_4"],
        ["task_5", "task_6"],
        ["task_7"],
        ["task_8"],
        ["task_9"],
        ["task_10"],
        ["task_11"],
    ]
    for task in tasks:
        absorbed = [o for o in originals if o.task_id in task.merged_from]
        assert task.acceptance_criteria == [c for o in absorbed for c in o.acceptance_criteria]
        assert task.covers == [r for o in absorbed for r in o.covers]
        assert task.files == [f for o in absorbed for f in o.files]
    assert [t.task_id for t in tasks] == [f"task_{k}" for k in range(1, 9)]
    assert [t.priority for t in tasks] == list(range(1, 9))


def test_ac_2_1_6_eight_or_fewer_unchanged():
    originals = [_task(k) for k in range(1, 9)]

    tasks = consolidate_tasks(originals)

    assert tasks == originals
    assert all(t.merged_from == [] for t in tasks)

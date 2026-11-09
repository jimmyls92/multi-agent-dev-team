"""Product Manager agent: turns a requirement into a spec and tasks (C2.1).

For now this module holds the task consolidation that keeps the task list
within the limit of C2.4 (DEC-082, DEC-092).

Typical usage example:

    tasks = consolidate_tasks(tasks)
"""

from orchestration.state import TaskSpec

MAX_TASKS = 8  # C2.4


def _group_sizes(n: int, groups: int) -> list[int]:
    """Returns the sizes of ``groups`` consecutive groups for ``n`` items.

    Sizes differ by at most one and the larger groups come first
    (DEC-092).

    Args:
        n: Number of items to split.
        groups: Number of groups, at most ``n``.

    Returns:
        The size of each group, in order; they add up to ``n``.
    """
    size, extra = divmod(n, groups)
    return [size + 1 if i < extra else size for i in range(groups)]


def _unique(items: list[str]) -> list[str]:
    """Returns the items without repetitions, keeping their first order.

    Args:
        items: Items that may repeat.

    Returns:
        The distinct items in order of first appearance.
    """
    return list(dict.fromkeys(items))


def _merge(group: list[TaskSpec], position: int) -> TaskSpec:
    """Returns one task that joins a group of consecutive tasks (DEC-082).

    Args:
        group: The tasks to join, in execution order.
        position: Position of the joined task in the new list, from 1; it
            gives the new task ID and priority (DEC-085).

    Returns:
        The joined task; ``merged_from`` lists the original task IDs.
    """
    if len(group) == 1:
        description = group[0].description
    else:
        description = "\n\n".join(
            f"Part {n} ({task.task_id}: {task.title}):\n{task.description}"
            for n, task in enumerate(group, start=1)
        )
    return TaskSpec(
        task_id=f"task_{position}",
        title=" + ".join(task.title for task in group),
        description=description,
        acceptance_criteria=[c for task in group for c in task.acceptance_criteria],
        covers=_unique([r for task in group for r in task.covers]),
        files=_unique([f for task in group for f in task.files]),
        priority=position,
        merged_from=[task.task_id for task in group],
    )


def consolidate_tasks(tasks: list[TaskSpec], max_tasks: int = MAX_TASKS) -> list[TaskSpec]:
    """Returns the task list reduced to at most ``max_tasks`` tasks (C2.4).

    Lists within the limit are returned unchanged. Longer lists are split
    into ``max_tasks`` consecutive groups of even size and each group is
    joined into one task, so no criterion, covered requirement or file is
    lost (DEC-082, DEC-092).

    Args:
        tasks: Tasks in execution order.
        max_tasks: Maximum number of tasks to keep.

    Returns:
        The tasks, at most ``max_tasks``, in execution order.

    Raises:
        ValueError: If ``max_tasks`` is lower than 1.
    """
    if max_tasks < 1:
        raise ValueError(f"max_tasks must be at least 1, got {max_tasks}")
    if len(tasks) <= max_tasks:
        return tasks
    merged = []
    start = 0
    for position, size in enumerate(_group_sizes(len(tasks), max_tasks), start=1):
        merged.append(_merge(tasks[start:start + size], position))
        start += size
    return merged

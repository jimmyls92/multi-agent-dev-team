"""Entry point of the agent team (DEC-094, DEC-096, DEC-111).

Runs the graph for a requirement and prints the result: a readable summary
ending with a ``RESULT:`` verdict line by default, or the whole state as
JSON with ``--json``. The exit code is 0 only when the run succeeded.

Typical usage example:

    python main.py "Build a CLI tool that counts word frequency in a file"
    python main.py --json
"""

import argparse
import logging
import os

import tools.handlers
from orchestration.graph import run
from orchestration.state import ProjectState, TaskState

# The graded Module 2 demo task (course guide, Part A2).
DEMO_REQUIREMENT = (
    "Build a REST API with two endpoints: GET /health (returns {status: ok}) and "
    "POST /echo (returns the JSON body it receives). Include basic input validation."
)
# Longest excerpt of a task's output printed in its result line.
RESULT_EXCERPT_CHARS = 100


def _verdict(state: ProjectState) -> tuple[int, str]:
    """Returns the exit code and the verdict line of a run (DEC-111).

    A run succeeds only with no error and every task done.

    Args:
        state: Final state of the run.

    Returns:
        ``(0, "RESULT: success")`` on success; exit code 1 with an
        ``error`` or ``incomplete`` verdict otherwise.
    """
    if state.error:
        return 1, f"RESULT: error — {state.error}"
    if not state.tasks:
        return 1, "RESULT: incomplete — no tasks were planned"
    unfinished = [task.task_id for task in state.tasks if task.status != "done"]
    if unfinished:
        return 1, f"RESULT: incomplete — {', '.join(unfinished)} failed"
    return 0, "RESULT: success"


def _result_line(task: TaskState) -> str:
    """Returns the summary line of a task's Coder result.

    Args:
        task: A task the Coder ran (``task.result`` is not None).

    Returns:
        Main file, iterations and the first non-empty line of the output,
        cut to ``RESULT_EXCERPT_CHARS``.
    """
    result = task.result
    lines = [line.strip() for line in result.result.splitlines() if line.strip()]
    excerpt = lines[0][:RESULT_EXCERPT_CHARS] if lines else "(no output)"
    return (
        f"    result: main file {result.main_file or 'none'} · "
        f"{result.iterations} iterations · {excerpt}"
    )


def _print_state(state: ProjectState) -> None:
    """Prints the progress notes, the spec and tasks, the files and the error.

    The spec and tasks are printed whenever the PM produced them, also when
    a later error ended the run.

    Args:
        state: Final state of the run.
    """
    print("[PROGRESS]")
    for note in state.progress:
        print(f"  {note}")
    spec = state.spec
    if spec is not None:
        print(f"\n[SPEC] {spec.name}\n  {spec.description}")
        print("\n[ACCEPTANCE CRITERIA]")
        for criterion in spec.acceptance_criteria:
            print(f"  {criterion.id}: {criterion.text}")
        print(f"\n[TASKS] {len(state.tasks)}")
        for task in state.tasks:
            print(f"  {task.task_id} · priority {task.priority} · {task.status} · {task.title}")
            print(f"    files: {', '.join(task.files)} · covers: {', '.join(task.covers)}")
            if task.merged_from:
                print(f"    merged from: {', '.join(task.merged_from)}")
            for c in task.acceptance_criteria:
                print(f"    - Given {c.given}, when {c.when}, then {c.then}")
            if task.result is not None:
                print(_result_line(task))
        print(f"\n[WORKSPACE] {tools.handlers.WORKSPACE_DIR}")
        print(f"  files: {', '.join(state.code) or 'none'}")
    if state.error:
        print(f"\nERROR: {state.error}")


def main(argv: list[str] | None = None) -> int:
    """Runs the graph from the command line.

    Args:
        argv: Command-line arguments without the program name. Defaults to
            sys.argv[1:].

    Returns:
        The exit code: 0 on success, 1 if a task failed or the run ended
        with an error (DEC-111).

    Raises:
        SystemExit: With code 2 on invalid usage, e.g. an empty requirement
            (raised by argparse).
    """
    parser = argparse.ArgumentParser(prog="python main.py", description="Multi-agent dev team.")
    parser.add_argument(
        "requirement",
        nargs="?",
        default=DEMO_REQUIREMENT,
        help="what to build (default: the graded REST API demo task)",
    )
    parser.add_argument("--json", action="store_true", help="print the whole final state as JSON")
    args = parser.parse_args(argv)
    if not args.requirement.strip():
        parser.error("the requirement must not be empty")  # exits with code 2

    # DEC-023: the entry point configures logging; an invalid LOG_LEVEL fails here.
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())

    state = run(args.requirement)
    exit_code, verdict = _verdict(state)
    if args.json:
        print(state.model_dump_json(indent=2))
    else:
        _print_state(state)
        print(f"\n{verdict}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

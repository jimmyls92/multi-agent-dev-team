"""Entry point of the agent team (DEC-094, DEC-096).

Runs the graph for a requirement and prints the result: a readable summary
by default, or the whole state as JSON with ``--json``.

Typical usage example:

    python main.py "Build a CLI tool that counts word frequency in a file"
    python main.py --json
"""

import argparse
import logging
import os

from orchestration.graph import run
from orchestration.state import ProjectState

# The graded Module 2 demo task (course guide, Part A2).
DEMO_REQUIREMENT = (
    "Build a REST API with two endpoints: GET /health (returns {status: ok}) and "
    "POST /echo (returns the JSON body it receives). Include basic input validation."
)


def _print_state(state: ProjectState) -> None:
    """Prints the progress notes and then the error or the spec and tasks.

    Args:
        state: Final state of the run.
    """
    print("[PROGRESS]")
    for note in state.progress:
        print(f"  {note}")
    if state.error:
        print(f"\nERROR: {state.error}")
        return
    spec = state.spec
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


def main(argv: list[str] | None = None) -> int:
    """Runs the graph from the command line.

    Args:
        argv: Command-line arguments without the program name. Defaults to
            sys.argv[1:].

    Returns:
        The exit code: 0 on success, 1 if the run ended with an error.

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
    if args.json:
        print(state.model_dump_json(indent=2))
    else:
        _print_state(state)
    return 1 if state.error else 0


if __name__ == "__main__":
    raise SystemExit(main())

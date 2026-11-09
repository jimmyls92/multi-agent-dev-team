# Spec: Lab <n>.<m> — <topic>

- **Status:** draft | approved | in progress | in review | done
- **Sources:** lab handout `docs/labs/lab_<n>_<m>_<topic>.md`, project guide (Module <n>), rubric C<n>.x
- **Decisions:** DEC-NNN, DEC-NNN (the why lives there; do not repeat it here)

## Goal

One or two sentences: what exists at the end of this spec that did not exist before.

## Lab vs project

Where the lab handout and the project/rubric disagree. The project wins.

| Lab says | Project requires | What we do |
|---|---|---|
| ... | ... | ... |

## Acceptance criteria

Every AC must translate into a test without further thought.
`Origin`: `C<x>.<y>` (rubric), `lab` or `ours`.
`Verify`: `unit` (fake model), `integration`, `llm` (real key, `--run-llm`) or `manual`.

### AC-<n>.<m>-1 — <short title>

- **Origin:** C<x>.<y>
- **Verify:** unit — `tests/test_<module>.py::test_ac_<n>_<m>_1_<name>`
- **Given** ...
- **When** ...
- **Then** ...

## Tasks

Each task covers at least one AC, is reviewable in ~15 minutes and ends in one commit.
Task status: todo | map | in progress | review | done

### T1 — <title> · todo

- **Covers:** AC-<n>.<m>-1, AC-<n>.<m>-2
- **Map** (approved before writing code):
  - Files: `path/to/file.py` (new | modified)
  - `function_name(arg: Type) -> ReturnType` — what it does in one line
  - Data flow: `a()` → `b()` → state key `x`
- **Run it yourself:** `command that shows the result or a forced failure`
- **Review notes:** answers to the "what if...?" questions, anything worth remembering

## Independent review

- **Date:**
- **Findings and triage:** fix (→ task R1) | discard (reason) | backlog (IMP-NNN)

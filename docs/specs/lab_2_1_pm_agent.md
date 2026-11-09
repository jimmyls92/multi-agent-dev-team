# Spec: Lab 2.1 — PM Agent

- **Status:** approved
- **Sources:** lab handout `docs/labs/lab_2_1_pm_agent.md`, project guide
  (Module 2, `docs/course_reference.txt` Part A2), rubric C2.1–C2.5
- **Decisions:** DEC-081..DEC-095 (the why lives there; do not repeat it here)

## Goal

A PM Agent that turns a free-text requirement into a validated, structured
specification and an ordered task list of 2–8 tasks covering every spec
criterion, written into a typed shared state (`ProjectState`) by a LangGraph
graph in `orchestration/`, runnable with `python main.py "requirement"`. The
state already has the fields the Coder will fill in Lab 2.3.

## Lab vs project

| Lab says | Project requires | What we do |
|---|---|---|
| Spec is free markdown | C2.1: name, description, acceptance criteria, tasks | `ProjectSpec` model; the markdown goes in `details` (DEC-083) |
| `json.loads()` on the raw reply, no validation | C1.3/C4.6: Pydantic before acting | `ToolStrategy` with Pydantic schemas, one corrective retry (DEC-088, DEC-091) |
| 2–4 tasks | C2.4: at most 8, consolidate the excess | 2–8 asked; >8 consolidated in code (DEC-081, DEC-082, DEC-092) |
| `CodingTask` without priority | C2.3: priority in the handoff | `priority` = execution order (DEC-085) |
| Unique `file_path` per task | — | `files: list[str]`, may repeat across tasks (DEC-084) |
| Acceptance criteria as free strings | C3.1 (later): QA writes behavioural tests | Task criteria are structured Given/When/Then (DEC-095) |
| `PMState` TypedDict, status always `"pending"`, no code | C2.2: per-task status and accumulated code | Pydantic `ProjectState` with `tasks[].status` and `code` (DEC-089, DEC-090) |
| Helicone client, `gpt-4.1-mini` | C4.5: larger model for the PM | `get_chat_model(PM_MODEL)`, default `openai/gpt-4.1` (DEC-093) |
| `graph.py`, `state.py`, `main.py` in the root | C1.1/C2.3: graph in `orchestration/` | DEC-094 layout |
| Default requirement `/health` + `/items` | Graded demo `/health` + `/echo` + validation | The `llm` AC uses the graded demo |

## Acceptance criteria

`Origin`: `C<x>.<y>` (rubric), `lab` or `ours`.
`Verify`: `unit` (fake model), `integration`, `llm` (real key, `--run-llm`)
or `manual`.

"Fake model" = a `GenericFakeChatModel` subclass that returns scripted
`Spec`/`TaskList` tool calls and records the messages of every call.
"Valid outputs" = a spec draft with criteria `REQ-1`, `REQ-2`, `REQ-3` and a
task list of 2 tasks that together cover all three.

### Shared state

#### AC-2.1-1 — The state rejects invalid values

- **Origin:** C2.2
- **Verify:** unit — `tests/test_state.py::test_ac_2_1_1_state_rejects_invalid_values`
- **Given** a `ProjectState` built from valid data
- **When** it is validated again with a task whose `status` is `"finished"`
  (not one of `pending`, `in_progress`, `done`, `failed`)
- **Then** a `ValidationError` is raised

#### AC-2.1-2 — The state round-trips through JSON

- **Origin:** C2.3
- **Verify:** unit — `tests/test_state.py::test_ac_2_1_2_state_json_round_trip`
- **Given** a `ProjectState` with a spec, two tasks, a `code` entry and
  progress notes
- **When** it is dumped with `model_dump_json()` and loaded back with
  `ProjectState.model_validate_json()`
- **Then** the loaded state equals the original

#### AC-2.1-20 — Task criteria must be Given/When/Then

- **Origin:** ours (DEC-095)
- **Verify:** unit — `tests/test_state.py::test_ac_2_1_20_task_criteria_need_given_when_then`
- **Given** valid state data
- **When** one task acceptance criterion has no `then` and the data is
  validated as `ProjectState`
- **Then** a `ValidationError` is raised

### Structured call helper

#### AC-2.1-3 — Invalid output gets one corrective retry

- **Origin:** ours (DEC-088, DEC-091)
- **Verify:** unit — `tests/test_llm_helpers.py::test_ac_2_1_3_corrective_retry`
- **Given** a fake model whose first output fails the schema's validation
  and whose second output is valid
- **When** the structured-call helper runs
- **Then** it returns the second output as a schema instance, the model was
  called exactly twice, and the second call's messages contain the
  validation error text of the first output

#### AC-2.1-4 — A second invalid output raises

- **Origin:** ours (DEC-088, DEC-091)
- **Verify:** unit — `tests/test_llm_helpers.py::test_ac_2_1_4_second_invalid_raises`
- **Given** a fake model whose first two outputs are invalid (a third valid
  one is scripted after them)
- **When** the structured-call helper runs
- **Then** it raises an exception whose message contains the last
  validation error, and the model was called exactly twice

### Consolidation

#### AC-2.1-5 — More than 8 tasks become 8 without losing anything

- **Origin:** C2.4
- **Verify:** unit — `tests/test_pm_agent.py::test_ac_2_1_5_consolidates_to_eight`
- **Given** 11 tasks `task_1`..`task_11`, each with its own acceptance
  criteria, covered criterion IDs and files
- **When** `consolidate_tasks` runs with the default limit
- **Then** it returns 8 tasks whose `merged_from` are
  `[task_1, task_2]`, `[task_3, task_4]`, `[task_5, task_6]`, `[task_7]`,
  …, `[task_11]`; every original acceptance criterion, covered ID and file
  appears in exactly the task that absorbed it; IDs are `task_1`..`task_8`
  and priorities 1..8 in order

#### AC-2.1-6 — 8 tasks or fewer are left unchanged

- **Origin:** C2.4
- **Verify:** unit — `tests/test_pm_agent.py::test_ac_2_1_6_eight_or_fewer_unchanged`
- **Given** 8 tasks
- **When** `consolidate_tasks` runs
- **Then** it returns the same 8 tasks, all with empty `merged_from`

### PM node

#### AC-2.1-7 — The PM writes a structured spec and its tasks into state

- **Origin:** C2.1, C2.3
- **Verify:** unit — `tests/test_pm_agent.py::test_ac_2_1_7_writes_spec_and_tasks`
- **Given** a fake model with valid outputs and a state with a requirement
  and a stale `error`
- **When** `pm_node` runs and its update is applied to the state
- **Then** `spec` has non-empty `name`, `description` and `details`, the
  three criteria and the two tasks; `tasks` holds the same tasks with
  `status == "pending"`, `task_id` `task_1`, `task_2`, `priority` 1, 2, a
  non-empty `description` and non-empty `acceptance_criteria`; `error == ""`

#### AC-2.1-8 — Two calls: requirement first, then the spec

- **Origin:** lab, DEC-087
- **Verify:** unit — `tests/test_pm_agent.py::test_ac_2_1_8_two_calls_in_order`
- **Given** a fake model with valid outputs
- **When** `pm_node` runs
- **Then** the model was called exactly twice; the first call's messages
  contain the requirement; the second call's messages contain the spec's
  name and every criterion ID

#### AC-2.1-9 — An uncovered criterion is corrected by the retry

- **Origin:** C2.1, DEC-083, DEC-088
- **Verify:** unit — `tests/test_pm_agent.py::test_ac_2_1_9_uncovered_criterion_retried`
- **Given** a fake model whose first task list covers only `REQ-1` and
  `REQ-2`, and whose second covers all three criteria
- **When** `pm_node` runs
- **Then** the state's tasks are the second list, the second task-list call
  contains a message naming `REQ-3` as not covered, and the model was
  called three times in total

#### AC-2.1-10 — A task covering an unknown criterion is rejected

- **Origin:** DEC-083
- **Verify:** unit — `tests/test_pm_agent.py::test_ac_2_1_10_unknown_criterion_rejected`
- **Given** a fake model whose task lists both cover all criteria but also
  reference `REQ-9`, which the spec does not have
- **When** `pm_node` runs
- **Then** the state has `error` mentioning `REQ-9`, `spec is None` and
  `tasks == []`

#### AC-2.1-11 — Fewer than 2 tasks is invalid

- **Origin:** C2.1, DEC-081
- **Verify:** unit — `tests/test_pm_agent.py::test_ac_2_1_11_single_task_retried`
- **Given** a fake model whose first task list has 1 task (covering all
  criteria) and whose second has 2
- **When** `pm_node` runs
- **Then** the state has the 2 tasks of the second list

#### AC-2.1-12 — More than 8 tasks from the LLM are consolidated in the node

- **Origin:** C2.4
- **Verify:** unit — `tests/test_pm_agent.py::test_ac_2_1_12_node_consolidates`
- **Given** a fake model whose task list has 11 tasks covering all criteria
- **When** `pm_node` runs
- **Then** the model was called exactly twice (no retry), `spec.tasks` and
  `tasks` have 8 tasks, every spec criterion is covered by some task, and
  a progress note says 11 tasks were consolidated into 8

#### AC-2.1-13 — Progress notes

- **Origin:** lab
- **Verify:** unit — `tests/test_pm_agent.py::test_ac_2_1_13_progress_notes`
- **Given** a fake model with valid outputs
- **When** `pm_node` runs
- **Then** `progress` in the update is a list of three strings, the last
  one containing the task count (`2`)

#### AC-2.1-14 — A failure ends in state, logged, without raising

- **Origin:** lab, DEC-087
- **Verify:** unit — `tests/test_pm_agent.py::test_ac_2_1_14_failure_in_state`
- **Given** a fake model that raises `RuntimeError("API down")` on its
  first call
- **When** `pm_node` runs
- **Then** it does not raise; the update has `error` containing
  `API down`, `spec is None`, `tasks == []`, a progress note with the
  error; and an ERROR log record contains `API down`

#### AC-2.1-15 — The PM uses `PM_MODEL`

- **Origin:** C4.5, DEC-093
- **Verify:** unit — `tests/test_pm_agent.py::test_ac_2_1_15_uses_pm_model`
- **Given** `PM_MODEL=some/model` in the environment and `get_chat_model`
  replaced by a recorder that returns the fake model
- **When** `pm_node` runs without an explicit model
- **Then** `get_chat_model` was called with `some/model`; and without
  `PM_MODEL` set, with `openai/gpt-4.1`

### Graph and entry point

#### AC-2.1-16 — The graph runs the PM and leaves a valid state

- **Origin:** C2.5 (handoff test), C2.3
- **Verify:** integration — `tests/test_integration_pm.py::test_ac_2_1_16_graph_writes_task_list`
- **Given** the graph from `build_graph()` with the PM on a fake model with
  valid outputs, and an initial state with only the requirement
- **When** the graph is invoked
- **Then** the final state validates as `ProjectState`, has a non-empty
  task list where each task has ID, description, acceptance criteria,
  priority and `status == "pending"`, and `requirement` is unchanged

#### AC-2.1-17 — A PM failure reaches END

- **Origin:** lab, DEC-087
- **Verify:** integration — `tests/test_integration_pm.py::test_ac_2_1_17_graph_failure_reaches_end`
- **Given** the graph with a PM model that always raises
- **When** the graph is invoked
- **Then** it returns without raising, with a non-empty `error` and an
  empty task list

#### AC-2.1-18 — `main.py` prints the result and signals failure

- **Origin:** ours (DEC-087, DEC-094)
- **Verify:** unit — `tests/test_main.py::test_ac_2_1_18_main_output_and_exit_code`
- **Given** two runs of the PM on a fake model: in the first the model
  returns valid outputs; in the second the model raises an exception
  (`RuntimeError("API down")`) on its first call
- **When** `main(["requirement"])` runs in each case
- **Then** on success it returns 0 and stdout contains the spec name, each
  task ID with its priority and files, and the progress notes; on failure
  it returns 1 and stdout contains the error

#### AC-2.1-19 — The graded demo requirement gives a covering spec

- **Origin:** C2.1
- **Verify:** llm — `tests/test_integration_pm.py::test_ac_2_1_19_demo_requirement` (`--run-llm`)
- **Given** the real PM model and the graded demo requirement (`/health`
  and `/echo` with basic input validation)
- **When** the graph is invoked
- **Then** `error == ""`, there are 2 to 8 tasks, every criterion is
  covered, and the spec text mentions `/health`, `/echo` and validation

## Tasks

Task status: todo | map | in progress | review | done

Each task runs: map (approved) → tests for its ACs, failing (red) → code
until they pass (green) → guided review → commit.

### T1 — Shared state models · done

- **Covers:** AC-2.1-1, AC-2.1-2, AC-2.1-20
- **Map:**
  - Files: `orchestration/state.py` (new), `tests/test_state.py` (new)
  - `SpecCriterion`, `TaskCriterion` (Given/When/Then), `TaskSpec`, `ProjectSpec`, `TaskState`, `ProjectState`
    — the state models of DEC-090; `TaskStatus` literal
  - LLM draft schemas stay out (they live in `agents/pm_agent.py`, T4);
    the state checks shape, not cross-field consistency; `code` has no
    reducer until Lab 2.3
  - Data flow: requirement → PM → `spec` + `tasks` (pending) → Coder →
    `tasks[i].status`, `code`; `progress` appended by its reducer
- **Run it yourself:** `.venv/bin/python -m pytest tests/test_state.py -v`
- **Review notes:**
  - Added during review: task criteria as Given/When/Then (DEC-095,
    AC-2.1-20); spec criterion IDs use `REQ-`.

### T2 — Structured-call helper · todo

- **Covers:** AC-2.1-3, AC-2.1-4
- **Map:** —
- **Run it yourself:** —
- **Review notes:** —

### T3 — Task consolidation · todo

- **Covers:** AC-2.1-5, AC-2.1-6
- **Map:** —
- **Run it yourself:** —
- **Review notes:** —

### T4 — PM node · todo

- **Covers:** AC-2.1-7 .. AC-2.1-15
- **Map:** —
- **Run it yourself:** —
- **Review notes:** —

### T5 — Graph, `main.py` and demo run · todo

- **Covers:** AC-2.1-16 .. AC-2.1-19
- **Map:** —
- **Run it yourself:** —
- **Review notes:** —

### T6 — Docs: README and `.env.example` · todo

- **Covers:** documentation matches the system (`PM_MODEL`, how to run the
  PM, state and graph diagram); C2.6's two-agent diagram comes in Lab 2.3
- **Map:** —
- **Run it yourself:** —
- **Review notes:** —

## Independent review

- **Date:**
- **Findings and triage:**

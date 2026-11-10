# Spec: Lab 2.2 — Coder node

- **Status:** done
- **Sources:** lab handout `docs/labs/lab_2_2_coder_node.md`, project guide
  (Module 2, `docs/course_reference.txt` Part A2, instruction 9), rubric
  C1.2–C1.5, C2.2, C2.3
- **Decisions:** DEC-097..DEC-109 (the why lives there; do not repeat it here)

## Goal

The Module 1 Coder runs as a self-looping LangGraph node over the PM's task
list: one graph step per task, in priority order, recording in the shared
state each task's status and full `CoderResult` and the code on disk, with
one memory window per run. It is tested from a prepared state; the PM→Coder
wiring is Lab 2.3 (DEC-100).

## Lab vs project

| Lab says | Project requires | What we do |
|---|---|---|
| Hand-written ReACT loop with the raw OpenAI client | C1.4: ReACT; DEC-068/069 | Reuse `run_agent` (`create_agent`); optional `model` for tests (DEC-105) |
| 8 iterations | C1.4: 10 | `MAX_ITERATIONS = 10` unchanged |
| `{"done": true}` parsed from text with `json.loads()` | C1.3: Pydantic before acting | Validated `Finish` tool (DEC-073), unchanged |
| `CodeArtifact` (`code` from the LLM's JSON, `tests_suggested`) | C1.5: `code`, `explanation`, `plan`, real `result` | `CoderResult` stored per task in `TaskState.result` (DEC-101, DEC-107) |
| `current_task_index` and `routing` fields | C2.2: typed state, no ad-hoc fields | Router reads task statuses (DEC-103) |
| `tasks` never written | C2.2: per-task status | `pending → done | failed` (DEC-101) |
| `artifacts` list with `operator.add` | C2.2: accumulated code | `code` = files written, read from disk (DEC-106) |
| Task description + criteria only | — | Plus spec name/description and files already written (DEC-098) |
| No memory | C1.2: window + Chroma before every call | One window per run in the LangGraph run context (DEC-099, DEC-104) |
| Failed artifact, loop goes on; exception → error dict, `"done"` | lab | Same: failed task does not stop the run (DEC-097); fatal error ends it (DEC-102) |
| Fixture `/health` + `/items` in `src/app.py` | Graded demo `/health` + `/echo` + validation | The `llm` AC uses the graded demo split into two tasks |

## Acceptance criteria

`Origin`: `C<x>.<y>` (rubric), `lab` or `ours`.
`Verify`: `unit` (fake model), `integration`, `llm` (real key, `--run-llm`)
or `manual`.

"Fake model" = `tests/fakes.py::ScriptedChatModel`. "Scripted successful
task" = replies for one task: a `Plan`, a `write_file` of a script, an
`exec_python` of it, and a `Finish` naming it as main file.
"Isolated" = workspace and Chroma in `tmp_path`, as in `tests/test_smoke.py`.
"Two-task state" = a `ProjectState` with a spec and two pending tasks
`task_1`, `task_2` (priorities 1, 2), each with its own description,
Given/When/Then criteria and planned files.

### Shared state

#### AC-2.2-1 — A task carries its result and round-trips through JSON

- **Origin:** C2.2, C2.3, DEC-107
- **Verify:** unit — `tests/test_state.py::test_ac_2_2_1_task_result_round_trip`
- **Given** a `ProjectState` whose first task has a `CoderResult` (status,
  plan, code, explanation, result, steps) and whose second task has none
- **When** it is dumped with `model_dump_json()` and loaded back
- **Then** the loaded state equals the original; the second task's
  `result is None`

### Coder node

All node ACs run isolated, with `make_coder_node(fake_model)` and a run
context holding a new window.

#### AC-2.2-2 — The node runs the first pending task and records it

- **Origin:** C2.2, C1.5, DEC-101, DEC-106, DEC-107
- **Verify:** unit — `tests/test_coder_node.py::test_ac_2_2_2_runs_first_pending_task`
- **Given** the two-task state and a scripted successful task that writes
  `app.py`
- **When** the node runs and its update is applied to the state
- **Then** `task_1` has `status == "done"`, `result.status == "success"`,
  a non-empty `result.plan` and `result.result`, and `result.code` equal
  to `app.py` on disk; `code == {"app.py": <content on disk>}`; `task_2`
  is still `pending` with `result is None`; `error == ""`

#### AC-2.2-3 — The node picks the first pending task, not the first task

- **Origin:** lab, DEC-103
- **Verify:** unit — `tests/test_coder_node.py::test_ac_2_2_3_skips_finished_tasks`
- **Given** the two-task state with `task_1` already `done`, and a
  scripted successful task
- **When** the node runs
- **Then** `task_2` becomes `done`, `task_1` is unchanged, and the task
  message of the model calls contains `task_2`'s description and not
  `task_1`'s

#### AC-2.2-4 — The task prompt carries the project context

- **Origin:** ours (DEC-098, DEC-105)
- **Verify:** unit — `tests/test_coder_node.py::test_ac_2_2_4_task_prompt_context`
- **Given** the two-task state with `task_1` `done` and `code ==
  {"app.py": "..."}`, and a scripted successful task
- **When** the node runs `task_2`
- **Then** the first model call's messages contain the spec name and
  description, `task_2`'s description, each of its criteria's given/when/
  then texts, its planned files, and `app.py` as an existing file

#### AC-2.2-5 — A task that does not succeed is failed and recorded

- **Origin:** lab, DEC-097, DEC-101
- **Verify:** unit — `tests/test_coder_node.py::test_ac_2_2_5_unsuccessful_task_failed`
- **Given** the two-task state and a fake model that, after the plan,
  answers with text only until the iteration limit
- **When** the node runs
- **Then** `task_1` has `status == "failed"` and `result.status ==
  "max_iterations"`; `task_2` is still `pending`; `error == ""`

#### AC-2.2-6 — `code` holds the files actually written, as on disk

- **Origin:** ours (DEC-106)
- **Verify:** unit — `tests/test_coder_node.py::test_ac_2_2_6_code_from_written_files`
- **Given** the two-task state where `task_1` plans only `app.py`, the
  state's `code` already has `old.py` and `app.py` from earlier work, and
  a scripted task that writes `app.py` and an unplanned `helpers.py`
  (plus a rejected `write_file` to `../outside.py`)
- **When** the node runs
- **Then** `code` has `old.py` unchanged, and `app.py` and `helpers.py`
  with their content on disk; it has no entry for `outside.py`

#### AC-2.2-7 — A fatal error ends in state without raising

- **Origin:** lab, DEC-102
- **Verify:** unit — `tests/test_coder_node.py::test_ac_2_2_7_fatal_error_in_state`
- **Given** the two-task state and a fake model that raises
  `RuntimeError("API down")` on its first call
- **When** the node runs
- **Then** it does not raise; `task_1` is `failed` with `result is None`;
  `task_2` is `pending`; `error` contains `API down`; a progress note and
  an ERROR log record contain `API down`

#### AC-2.2-8 — Two progress notes per task

- **Origin:** lab
- **Verify:** unit — `tests/test_coder_node.py::test_ac_2_2_8_progress_notes`
- **Given** the two-task state and a scripted successful task
- **When** the node runs
- **Then** `progress` in the update has two strings: the first with
  `task_1` and its title, the second with `task_1` and `done`

#### AC-2.2-9 — No pending task is an error, not a model call

- **Origin:** lab (index out of range)
- **Verify:** unit — `tests/test_coder_node.py::test_ac_2_2_9_no_pending_task`
- **Given** a state whose tasks are all `done` or `failed`, and a fake
  model with no replies
- **When** the node runs
- **Then** it does not raise, the model is never called, the tasks are
  unchanged and `error` says there is no pending task

### Router and window

#### AC-2.2-10 — The router loops while tasks are pending and there is no error

- **Origin:** lab, DEC-103
- **Verify:** unit — `tests/test_coder_node.py::test_ac_2_2_10_router`
- **Given** three states: a pending task and no error; no pending task;
  a pending task and a non-empty `error`
- **When** `route_after_coder` runs on each
- **Then** it returns the Coder node's name for the first and `END` for
  the other two

#### AC-2.2-11 — One window per run, shared by its tasks

- **Origin:** C1.2, DEC-099, DEC-104
- **Verify:** integration — `tests/test_integration_coder.py::test_ac_2_2_11_window_per_run`
- **Given** the Coder graph, the two-task state and two scripted
  successful tasks; then a second run of a new two-task state with its
  own scripted tasks
- **When** each run is invoked with a new run context
- **Then** in the first run, the model calls of `task_2` contain, outside
  the system message, a message with `task_1`'s description (the window),
  and the run's window ends with 2 turns; the first model call of the
  second run has no message outside the system message other than its own
  task (new window)

### Graph

#### AC-2.2-12 — The self-loop runs every task, one step each

- **Origin:** C2.2, C2.3, lab
- **Verify:** integration — `tests/test_integration_coder.py::test_ac_2_2_12_self_loop_runs_all_tasks`
- **Given** the Coder graph, the two-task state and two scripted
  successful tasks (`task_2` rewrites `app.py`)
- **When** the graph is invoked
- **Then** the final state validates as `ProjectState`; both tasks are
  `done` with a `result`; the Coder node ran twice; `progress` has four
  notes; `code["app.py"]` is `task_2`'s content; `requirement` and `spec`
  are unchanged; `error == ""`

#### AC-2.2-13 — A failed task does not stop the next one

- **Origin:** DEC-097
- **Verify:** integration — `tests/test_integration_coder.py::test_ac_2_2_13_failed_task_then_next`
- **Given** the Coder graph, the two-task state, `task_1` scripted to hit
  the iteration limit and `task_2` scripted to succeed
- **When** the graph is invoked
- **Then** `task_1` is `failed`, `task_2` is `done`, `error == ""`

#### AC-2.2-14 — A fatal error ends the loop

- **Origin:** DEC-102
- **Verify:** integration — `tests/test_integration_coder.py::test_ac_2_2_14_fatal_error_ends_loop`
- **Given** the Coder graph, the two-task state and a model that raises
  on its first call
- **When** the graph is invoked
- **Then** it returns without raising; `error` is non-empty; `task_1` is
  `failed`; `task_2` is still `pending`; the model was called once

#### AC-2.2-15 — The real Coder completes the graded demo in two tasks

- **Origin:** C2.2, C2.3, C1.5
- **Verify:** llm — `tests/test_integration_coder.py::test_ac_2_2_15_demo_tasks` (`--run-llm`)
- **Given** the real Coder model, isolated, and a two-task state for the
  graded demo: `task_1` creates the API with `GET /health`, `task_2` adds
  `POST /echo` with basic input validation to the same file
- **When** the Coder graph is invoked
- **Then** `error == ""`; both tasks are `done` with non-empty
  `result.plan` and `result.result`; `code` has one file containing
  `/health` and `/echo`, equal to its content on disk

### Independent review fixes (R1)

#### AC-2.2-16 — Only a `success` result makes a task `done`

- **Origin:** C2.2, DEC-101
- **Verify:** unit — `tests/test_coder_node.py::test_ac_2_2_16_only_success_is_done`
- **Given** the two-task state and, in turn, a scripted task that ends
  `failed_execution` (the script raises), `unverified` (written, never run)
  and `answered` (Finish without a main file)
- **When** the node runs
- **Then** `task_1` has that `result.status` and `status == "failed"`;
  `task_2` is still `pending`; `error == ""`

#### AC-2.2-17 — A file that cannot be read is skipped, the node does not raise

- **Origin:** DEC-102, DEC-106
- **Verify:** unit — `tests/test_coder_node.py::test_ac_2_2_17_unreadable_file_skipped`
- **Given** a scripted task that writes `data.txt` and `app.py`, and
  running `app.py` overwrites `data.txt` with non-UTF-8 bytes
- **When** the node runs
- **Then** `task_1` is `done`; `code` has `app.py` as on disk and no
  `data.txt`; a WARNING record names `data.txt`

#### AC-2.2-18 — A rejected write is not in `code`, even if the file exists

- **Origin:** DEC-106 (DEC-080)
- **Verify:** unit — `tests/test_coder_node.py::test_ac_2_2_18_rejected_write_not_in_code`
- **Given** `old_lib.py` already in the workspace and a scripted task whose
  first `write_file` of `old_lib.py` has no `content`, then a successful
  task writing `app.py`
- **When** the node runs
- **Then** that step has `rejected == True`; `code` has `app.py` and no
  `old_lib.py`

#### AC-2.2-19 — A missing run context is a clear error

- **Origin:** DEC-109
- **Verify:** unit — `tests/test_coder_node.py::test_ac_2_2_19_missing_run_context`
- **Given** the two-task state and a fake model with no replies
- **When** the node runs with a runtime without context
- **Then** the model is never called; the update has no `tasks`; `error`
  mentions the context

## Tasks

Task status: todo | map | in progress | review | done

Each task runs: map (approved) → tests for its ACs, failing (red) → code
until they pass (green) → guided review → commit. The whole suite (Module 1
and Lab 2.1 included) stays green at the end of every task.

### T1 — State: `CoderResult` moves, tasks carry their result · done

- **Covers:** AC-2.2-1
- **Map:**
  - Files: `orchestration/state.py`, `agents/coder_agent.py`,
    `tests/test_state.py` (modified)
  - `StepRecord`, `CoderResult` — moved unchanged to `state.py`; the Coder
    imports them, so `agents.coder_agent.CoderResult` still resolves
  - `TaskState.result: CoderResult | None = None` — the task's output
    (DEC-107)
  - Data flow: none new; the node writes `result` in T2
- **Run it yourself:** `.venv/bin/python -m pytest tests/test_state.py -v`

### T2 — Coder node: happy path, task prompt and code · done

- **Covers:** AC-2.2-2, AC-2.2-3, AC-2.2-4, AC-2.2-6, AC-2.2-8, AC-2.2-9
- **Map:**
  - Files: `agents/coder_agent.py` (modified), `tests/conftest.py`
    (modified: `isolated_run` fixture, in-memory Chroma with a hash
    embedding), `tests/test_coder_node.py` (new)
  - `run_agent(task, window, model=None) -> CoderResult` — optional model
    for the plan and the loop; without it, unchanged (DEC-105)
  - `CoderRunContext(window)` — the run's context, one window per run
    (DEC-099, DEC-104); lives with the Coder (the window is private and
    importing `memory` loads Chroma)
  - `_next_pending(tasks) -> TaskState | None` — first pending task (DEC-103)
  - `_task_prompt(task, spec, existing_files) -> str` — task text with the
    project context (DEC-098)
  - `_written_files(result) -> dict[str, str]` — `write_file` steps inside
    the workspace that exist, read from disk (DEC-106)
  - `make_coder_node(model) -> coder_node(state, runtime) -> dict`
  - Data flow: `_next_pending` → `_task_prompt` → `run_agent(prompt,
    runtime.context.window, model)` → `tasks[i].{status, result}`, `code`,
    `progress`, `error`
- **Run it yourself:** `.venv/bin/python -m pytest tests/test_coder_node.py -v`
- **Review notes:** AC-2.2-6 moved here from T3 (`code` is born in this
  task).

### T3 — Coder node: failures · done

- **Covers:** AC-2.2-5, AC-2.2-7
- **Map:**
  - Files: `agents/coder_agent.py`, `tests/test_coder_node.py` (modified)
  - `_with_task(tasks, task_id, **update) -> list[TaskState]` — the task list
    with one task updated; used by both paths
  - `coder_node` — `try/except` from the prompt to `run_agent`: a fatal error
    marks the task `failed` with `result=None`, logs at ERROR and returns
    `error` (DEC-102); `code` is left untouched
  - Data flow: exception → `tasks[i].status = "failed"`, `progress`, `error`
- **Run it yourself:** `.venv/bin/python -m pytest tests/test_coder_node.py -v`
- **Review notes:** AC-2.2-5 was green on arrival (the status mapping came
  with T2); a missing run context is caught as a fatal error too.

### T4 — Router and the Coder graph · done

- **Covers:** AC-2.2-10, AC-2.2-11, AC-2.2-12, AC-2.2-13, AC-2.2-14
- **Map:**
  - Files: `orchestration/graph.py` (modified), `tests/coder_helpers.py`
    (new: two-task state and scripted tasks, shared by both test files),
    `tests/test_coder_node.py` (modified: imports the helpers, router
    test), `tests/test_integration_coder.py` (new)
  - `CODER_NODE = "coder"`
  - `route_after_coder(state) -> str` — `CODER_NODE` while a task is pending
    and `error` is empty, else `END` (DEC-103)
  - `_add_coder(builder, model) -> None` — adds the node and its self-loop;
    reused by `build_graph` in Lab 2.3
  - `build_coder_graph(coder_model=None) -> CompiledStateGraph` —
    `StateGraph(ProjectState, context_schema=CoderRunContext)`,
    `START → coder ⟲ → END` (DEC-100, DEC-104)
  - Data flow: `invoke(state, context=CoderRunContext())` → coder step per
    task → `route_after_coder` → coder | END
- **Run it yourself:** `.venv/bin/python -m pytest tests/test_integration_coder.py -v`
- **Review notes:** `run()` and `main.py` stay PM-only until Lab 2.3.

### T5 — Real-model run and docs · done

- **Covers:** AC-2.2-15
- **Map:**
  - Files: `requirements.txt` (`flask`, DEC-108),
    `tests/test_integration_coder.py` (`test_ac_2_2_15_demo_tasks`, marked
    `llm`), `docs/decisions.md`, this spec, `CLAUDE.md`
  - The demo state splits the graded requirement into `task_1` (`GET
    /health`) and `task_2` (`POST /echo` with 400 on invalid JSON), both
    verified with `app.test_client()`; a subprocess then calls both
    endpoints on the generated app
- **Run it yourself:** `.venv/bin/python -m pytest tests/test_integration_coder.py::test_ac_2_2_15_demo_tasks --run-llm -v`
- **Review notes:** passed twice with `openai/gpt-4.1-mini` (task_1 in 3
  iterations, task_2 in 4, ~30–40 s). The server-start risk for PM-written
  tasks is left for Lab 2.3 (DEC-108).

### R1 — Independent review fixes · done

- **Covers:** AC-2.2-16, AC-2.2-17, AC-2.2-18, AC-2.2-19; F9 in AC-2.2-11
- **Map:**
  - Files: `orchestration/state.py`, `agents/coder_agent.py`,
    `tests/test_coder_node.py`, `tests/test_integration_coder.py`
  - `StepRecord.rejected: bool = False` — set in `result_from_messages`
    from the `ToolMessage` status (DEC-106)
  - `_written_files` — skips rejected steps; skips unreadable files with a
    WARNING (DEC-102, DEC-106)
  - `coder_node` — checks `runtime.context` before the task (DEC-109)
- **Run it yourself:** `.venv/bin/python -m pytest tests/test_coder_node.py -v`
- **Review notes:** done without guided review at the user's request.
  AC-2.2-16 was green on arrival (it guards the DEC-101 mapping against a
  regression); AC-2.2-17..19 were red before the fix.

## Independent review

- **Date:** 2026-11-10
- **Findings and triage:**

| ID | Severity | Finding | Triage |
|---|---|---|---|
| F1 | medium | Only `max_iterations` tested as `failed`; a regression to "failed only on max_iterations" stays green | Fixed in R1 (AC-2.2-16) |
| F2 | medium | `_written_files` outside the `try`: a binary or unreadable file raises out of the node | Fixed in R1 (AC-2.2-17) |
| F3 | low | A rejected `write_file` of an existing file entered `code` | Fixed in R1 (AC-2.2-18) |
| F4 | low | No run context gave a misleading `AttributeError` task failure | Fixed in R1 (AC-2.2-19, DEC-109) |
| F5 | low | DEC-103 said LangGraph's default limit is 25 (it is 10007) | Doc fixed in R1; explicit limit → IMP-010 |
| F6 | low | DEC-104 said `run()` creates the window (it is still PM-only) | Doc fixed in R1 |
| F7 | medium | AC-2.2-15 relies on the test's task text forbidding `app.run()` | Discarded here: already pending for Lab 2.3 (DEC-108) |
| F8 | low | `read_text` turns CRLF into LF in `code` | Discarded: `code` and `result.code` agree, as a text reader sees them |
| F9 | low | AC-2.2-11 counted the second run's messages but not their content | Fixed in R1 |
| F10 | low | `code` misses files after a late fatal error | Discarded: already IMP-009 |

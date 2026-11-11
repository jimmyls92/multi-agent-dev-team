# Spec: Lab 2.3 — PM + Coder pipeline

- **Status:** in progress
- **Sources:** lab handout `docs/labs/lab_2_3_pipeline.md`, project guide
  (Module 2, `docs/course_reference.txt` Part A2, instructions 9 and 14),
  rubric C2.3–C2.6
- **Decisions:** DEC-110..DEC-120 (the why lives there; do not repeat it here)

## Goal

One graph runs the PM and then the Coder over the PM's tasks
(`START → pm → coder ⟲ → END`), from `run()` and `python main.py`. Each run
starts with an empty workspace (earlier files archived), has an explicit
step limit, and ends with a verdict that never reports success while a task
failed. The graded API task goes through PM and Coder and passes the
request fixture, both in-process and against a real server.

## Lab vs project

| Lab says | Project requires | What we do |
|---|---|---|
| `route_after_pm` on `routing == "coder"`, `error`, non-empty `tasks` | C2.2: typed state, one source of truth | `error` empty and `tasks` non-empty, no `routing` field (DEC-110) |
| `route_after_coder` on `routing` | — | Existing router on task statuses (DEC-103) |
| Nodes `pm_node`, `coder_node` | — | Existing names `pm`, `coder` |
| Module-level `graph = build_graph()` | One memory window per run (DEC-104) | `run()` builds the graph and passes a new `CoderRunContext` |
| `main.py` prints the log, tasks and artifacts | C2.4 progress; honest outcome | Per-task status and result, `RESULT:` line, exit 0/1/2 (DEC-111) |
| Generated code in the working directory | C2.2/C2.5: code of this run | Earlier files archived before each run (DEC-114) |
| Default recursion limit | — | Explicit limit, state kept when hit (DEC-115) |
| `/health` + `/items` on port 8080 | Graded demo `/health` + `/echo` + validation | `llm` AC with the graded demo through PM and Coder |
| Coder told nothing about servers | C2.5: executable Flask code | Rule in the Coder prompt; `python app.py` serves (DEC-112) |

## Acceptance criteria

`Origin`: `C<x>.<y>` (rubric), `lab` or `ours`.
`Verify`: `unit` (fake model), `integration`, `llm` (real key, `--run-llm`)
or `manual`.

"Fake PM" = `ScriptedChatModel` with a spec reply and a task-list reply
(helpers of `tests/test_pm_agent.py`). "Fake Coder" = `ScriptedChatModel`
with the replies of `tests/coder_helpers.py` (`successful_task`,
`unsuccessful_task`). "Isolated" = the `isolated_run` fixture (workspace
and Chroma in `tmp_path`). Every test that calls `run()` or `main()` is
isolated, so the real `workspace/` is never archived by a test.

### Workspace archive

#### AC-2.3-1 — Earlier files are archived before the run

- **Origin:** ours, DEC-114
- **Verify:** unit — `tests/test_workspace.py::test_ac_2_3_1_archives_previous_files`
- **Given** a workspace with a file at its root and a file in a subfolder
- **When** `archive_workspace(workspace, protected)` runs
- **Then** the workspace exists and is empty; both files are under the
  returned folder `<workspace>_history/<timestamp>/` with the same relative
  paths and content

#### AC-2.3-2 — An empty workspace archives nothing

- **Origin:** ours, DEC-114
- **Verify:** unit — `tests/test_workspace.py::test_ac_2_3_2_empty_workspace`
- **Given** an empty workspace, and separately a workspace that does not
  exist yet
- **When** `archive_workspace` runs
- **Then** it returns None, no history folder is created and the workspace
  exists afterwards

#### AC-2.3-3 — Two archives never overwrite each other

- **Origin:** ours, DEC-114
- **Verify:** unit — `tests/test_workspace.py::test_ac_2_3_3_archives_do_not_collide`
- **Given** a workspace with a file
- **When** it is archived, a new file is written and it is archived again
  within the same second
- **Then** the two archive folders are different and each holds its own file

#### AC-2.3-4 — A workspace that is or contains the protected root is refused

- **Origin:** ours, DEC-114
- **Verify:** unit — `tests/test_workspace.py::test_ac_2_3_4_refuses_protected_root`
- **Given** a protected folder `tmp/repo` with a file in it
- **When** `archive_workspace` runs with the workspace equal to `tmp/repo`,
  and again with the workspace equal to `tmp`
- **Then** it raises `ValueError` both times and every file is still in
  place

### Graph and run

#### AC-2.3-5 — The router after the PM

- **Origin:** C2.3, lab, DEC-110
- **Verify:** unit — `tests/test_pipeline.py::test_ac_2_3_5_route_after_pm`
- **Given** a state with tasks and no error; one with tasks and an error;
  one with no tasks and no error
- **When** `route_after_pm` is called on each
- **Then** it returns `CODER_NODE` for the first and `END` for the others

#### AC-2.3-6 — The PM's tasks are run by the Coder in the same graph

- **Origin:** C2.3, C2.4, lab
- **Verify:** integration — `tests/test_integration_pipeline.py::test_ac_2_3_6_pm_to_coder_handoff`
- **Given** a fake PM that plans two tasks and a fake Coder with two
  successful tasks writing `app.py` and `utils.py`; isolated
- **When** `run(requirement, pm_model=..., coder_model=...)` is called
- **Then** `error == ""`; `task_1` and `task_2` are `done`, each with a
  `CoderResult`; the first Coder task message contains `task_1`'s
  description and acceptance criteria and the second contains `task_2`'s;
  `code` has both files as on disk; `progress` holds the PM notes, then
  `starting task_1`, `task_1 done`, `starting task_2`, `task_2 done`, in
  that order

#### AC-2.3-7 — A PM failure never reaches the Coder

- **Origin:** C2.3, lab, DEC-110
- **Verify:** integration — `tests/test_integration_pipeline.py::test_ac_2_3_7_pm_failure_skips_coder`
- **Given** a fake PM that raises and a fake Coder with no replies; isolated
- **When** `run()` is called
- **Then** it returns without raising; `error` is set; `tasks == []`; the
  fake Coder received no call

#### AC-2.3-8 — `run()` archives the workspace and records it in the state

- **Origin:** ours, DEC-114
- **Verify:** integration — `tests/test_integration_pipeline.py::test_ac_2_3_8_run_archives_workspace`
- **Given** an isolated workspace holding `old.py`, a fake PM with two
  tasks, and a fake Coder whose two successful tasks write `app.py`
- **When** `run()` is called
- **Then** the workspace holds `app.py` and not `old.py`; `old.py` is in
  the archive folder; the first `progress` note names that folder;
  `code` does not contain `old.py`

#### AC-2.3-9 — A refused archive is an error before any model call

- **Origin:** ours, DEC-114
- **Verify:** integration — `tests/test_integration_pipeline.py::test_ac_2_3_9_refused_archive_is_error`
- **Given** an isolated workspace whose protected root is set to the
  workspace itself, and fake PM and Coder with no replies
- **When** `run()` is called
- **Then** it returns without raising; `error` says the workspace cannot
  be archived; no model received a call; the workspace files are untouched

#### AC-2.3-10 — The step limit ends a runaway loop with the state kept

- **Origin:** ours, DEC-115
- **Verify:** integration — `tests/test_integration_pipeline.py::test_ac_2_3_10_step_limit_keeps_state`
- **Given** `route_after_coder` replaced by a router that always returns
  `CODER_NODE`, a fake PM with two tasks and a fake Coder with enough
  successful tasks; isolated
- **When** `run()` is called
- **Then** it returns without raising; `error` mentions the step limit;
  `progress` keeps the PM notes and the notes of both tasks; the number of
  Coder steps is at most `MAX_TASKS + 2`

#### AC-2.3-11 — A full plan of eight tasks runs within the limit

- **Origin:** C2.4, DEC-115
- **Verify:** integration — `tests/test_integration_pipeline.py::test_ac_2_3_11_eight_tasks_within_limit`
- **Given** a fake PM that plans eight tasks and a fake Coder with eight
  successful tasks; isolated
- **When** `run()` is called
- **Then** `error == ""` and all eight tasks are `done`, in priority order

### Command line

#### AC-2.3-12 — A successful run prints each task and exits 0

- **Origin:** C2.4, DEC-111
- **Verify:** integration — `tests/test_main.py::test_ac_2_3_12_main_success`
- **Given** fake PM (two tasks) and fake Coder (two successful tasks) used
  by `main`; isolated
- **When** `main(["Build an echo API"])` runs
- **Then** it returns 0; the output shows for each task its status
  (`done`), main file, iterations and the first line of its result; the
  workspace folder; and ends with `RESULT: success`

#### AC-2.3-13 — A run with a failed task is incomplete and exits 1

- **Origin:** C2.4, DEC-097, DEC-111
- **Verify:** integration — `tests/test_main.py::test_ac_2_3_13_main_incomplete`
- **Given** fake PM (two tasks) and a fake Coder whose first task succeeds
  and second ends at the iteration limit; isolated
- **When** `main` runs
- **Then** it returns 1; `task_1` shows `done`, `task_2` shows `failed`;
  the last line is `RESULT: incomplete — task_2 failed`; the output never
  contains `RESULT: success`

#### AC-2.3-14 — A run with an error exits 1 with the error verdict

- **Origin:** DEC-111
- **Verify:** integration — `tests/test_main.py::test_ac_2_3_14_main_error`
- **Given** a fake PM that raises `RuntimeError("API down")`; isolated
- **When** `main` runs
- **Then** it returns 1 and the last line starts with `RESULT: error` and
  contains `API down`

### Real models

#### AC-2.3-15 — The Coder verifies an API without starting it

- **Origin:** C2.5, DEC-112 (replaces the `verify` sentence of AC-2.2-15)
- **Verify:** llm — `tests/test_integration_coder.py::test_ac_2_2_15_demo_tasks` (`--run-llm`)
- **Given** the Lab 2.2 demo state whose task descriptions no longer say
  how to verify the app or that it must not be started
- **When** the Coder graph runs it with the real model
- **Then** both tasks are `done`; no `exec_python` observation reports a
  timeout; the in-process fixture passes; and running the API file with
  `python` starts a server that answers the fixture over HTTP

#### AC-2.3-16 — The graded API task goes through PM and Coder and passes the fixture

- **Origin:** C2.5, C2.1, C2.3, DEC-112
- **Verify:** llm — `tests/test_integration_pipeline.py::test_ac_2_3_16_graded_demo` (`--run-llm`)
- **Given** the graded demo requirement (`main.DEMO_REQUIREMENT`) and the
  real PM and Coder; isolated
- **When** `run(DEMO_REQUIREMENT)` is called
- **Then** `error == ""`; there are at least two tasks, all `done`; exactly
  one file in `code` defines both `/health` and `/echo` and it matches the
  disk; the in-process fixture passes (`GET /health` → 200
  `{"status": "ok"}`; `POST /echo` with JSON → 200 and the same body;
  `POST /echo` with a non-JSON body → 400); and running that file with
  `python` starts a server that answers the same three requests over HTTP
  (the URL read from its output), then is stopped

#### AC-2.3-17 — `exec_python` never runs a file that starts a web server

- **Origin:** ours, DEC-116 (added in T4 after AC-2.3-15 failed 4 of 5 runs)
- **Verify:** unit — `tests/test_server_guard.py::test_ac_2_3_17_server_file_not_run`,
  `tests/test_server_guard.py::test_ac_2_3_17_check_script_runs`
- **Given** a workspace with a Flask app that calls `app.run()`, a FastAPI
  app started with `uvicorn.run(`, a stdlib server with `.serve_forever(`,
  and a check script that imports the Flask app and calls `subprocess.run(`;
  each writes a marker file when it runs
- **When** `dispatch_tool("exec_python", ...)` is called on each
- **Then** the three servers are not run (no marker, no execution) and the
  observation is an error that asks for a check script; the check script
  runs and its output is returned

### Independent review fixes (R1)

#### AC-2.3-18 — A task without a Python file is retried

- **Origin:** ours, DEC-117 (review F1)
- **Verify:** unit — `tests/test_pm_agent.py::test_ac_2_3_18_task_needs_python_file`
- **Given** a fake PM whose first task list has a task whose only file is
  `requirements.txt`, and whose corrective retry is valid
- **When** the PM node runs
- **Then** there are three model calls, the last one names the `.py` rule,
  and every task in the state has at least one `.py` file

#### AC-2.3-19 — The request fixture rejects an API that answers 415 to non-JSON

- **Origin:** C2.5, DEC-118 (review F2)
- **Verify:** unit — `tests/test_api_fixture.py::test_ac_2_3_19_fixture_tells_apart`
- **Given** a reference Flask API that reads the body with
  `get_json(silent=True)` and answers 400 when it is None, and a variant
  that uses `get_json()`
- **When** `check_in_process` and `check_real_server` run on each
- **Then** both checks pass for the reference API; for the variant the
  in-process check fails and the real-server check raises, on a body sent
  as `text/plain`, an empty body or a body with no content type (each
  must get 400)

#### AC-2.3-20 — The Coder runs the pending task with the lowest priority

- **Origin:** C2.3, C2.4, DEC-119 (review F5)
- **Verify:** unit — `tests/test_coder_node.py::test_ac_2_3_20_lowest_priority_first`;
  AC-2.3-6 also checks that each task's ID reaches the Coder
- **Given** a state whose tasks are listed as `task_2` (priority 2) then
  `task_1` (priority 1), both pending
- **When** the Coder node runs once
- **Then** `task_1` is done, its ID is in the Coder's prompt, and `task_2`
  is still pending

#### AC-2.3-21 — Each progress note is logged when its step ends

- **Origin:** C2.4, DEC-120 (review F6)
- **Verify:** integration — `tests/test_integration_pipeline.py::test_ac_2_3_21_progress_logged_live`
- **Given** a run with the fake two-task PM and Coder
- **When** the Coder starts `task_2`
- **Then** an INFO record with "task_1 done" has already been logged

#### AC-2.3-22 — The graded demo succeeds on repeated real runs

- **Origin:** C2.5 (review F1, F2)
- **Verify:** llm — `python main.py` 5 times with a temporary
  `WORKSPACE_DIR`, then the extended fixture on each API; AC-2.3-16 with
  the extended fixture
- **Given** the graded demo requirement and the real models
- **When** `python main.py` runs 5 times
- **Then** each run ends `RESULT: success` with exit 0, and each API
  passes the extended fixture in-process and as a real server; any
  failure is recorded with its cause

### Regressions adapted

`run()` and `main()` now run the Coder after the PM, so these Lab 2.1 tests
change without changing what they check:

- AC-2.1-16 (`test_ac_2_1_16_graph_writes_task_list`): reads the state
  right after the `pm` step (`stream_mode="updates"`), so it still checks
  the PM's handoff before the Coder changes the statuses (C2.5 asks for
  exactly this test).
- AC-2.1-17, AC-2.1-19: isolated.
- AC-2.1-18, AC-2.1-23: isolated, with a fake Coder that completes every
  task; the exit code stays 0 and the printed checks stay. Done in T2,
  since `main()` runs the Coder as soon as `run()` does.

## Tasks

Each task covers at least one AC, is reviewable in ~15 minutes and ends in one commit.
Task status: todo | map | in progress | review | done

### T1 — Workspace archive · done

- **Covers:** AC-2.3-1, AC-2.3-2, AC-2.3-3, AC-2.3-4
- **Map:**
  - Files: `orchestration/workspace.py` (new), `tests/test_workspace.py` (new)
  - `REPO_ROOT: Path` — the protected folder `run()` passes in T2
  - `archive_workspace(workspace: Path, protected: Path) -> Path | None` —
    moves every item of the workspace to `<workspace>_history/<timestamp>/`
    and returns that folder; None when empty; `ValueError` when the
    workspace is or contains `protected` (DEC-114)
  - `_free_folder(parent: Path, name: str) -> Path` — `name`, or
    `name-2`, `name-3`... when taken
  - Data flow (T2): `run()` → `archive_workspace(WORKSPACE_DIR, REPO_ROOT)`
    → progress note
- **Run it yourself:** `.venv/bin/python -m pytest tests/test_workspace.py -v`
- **Review notes:**

### T2 — Full graph and `run()` · done

- **Covers:** AC-2.3-5..AC-2.3-11; adapted AC-2.1-16..AC-2.1-19, AC-2.1-23
- **Map:**
  - Files: `orchestration/graph.py` (modified), `tests/test_pipeline.py`
    (new), `tests/test_integration_pipeline.py` (new), `tests/conftest.py`
    (safety nets), `tests/test_integration_pm.py` and `tests/test_main.py`
    (adapted)
  - `PM_NODE = "pm"`, `STEP_LIMIT = 1 + MAX_TASKS + 2` (DEC-115)
  - `route_after_pm(state) -> str` — `CODER_NODE` with no error and at
    least one task, else `END` (DEC-110)
  - `build_graph(pm_model=None, coder_model=None) -> CompiledStateGraph` —
    `START → pm → coder ⟲ → END`, `context_schema=CoderRunContext`
  - `run(requirement, pm_model=None, coder_model=None) -> ProjectState` —
    archives the workspace (DEC-114), streams the graph with a new
    `CoderRunContext` and the step limit, keeps the last state; an archive
    failure or the limit end with `error` set
  - `tests/conftest.py`: autouse `_temporary_workspace`,
    `_fresh_coder_agent`, `_refuse_real_models`
- **Run it yourself:** `.venv/bin/python -m pytest tests/test_pipeline.py tests/test_integration_pipeline.py -v`
- **Review notes:** the Coder's default agent is cached per process
  (`_default_agent`); a test that reached it through `main()` reused the
  exhausted fake of an earlier test, so `_fresh_coder_agent` clears the
  cache around every test. In AC-2.3-6 the Coder's task message is looked
  for in every message of the call, since the run's window (DEC-099) puts
  the earlier task first.

### T3 — Command line verdict · done

- **Covers:** AC-2.3-12, AC-2.3-13, AC-2.3-14
- **Map:**
  - Files: `main.py` (modified), `tests/test_main.py` (modified)
  - `_verdict(state) -> tuple[int, str]` — exit code and `RESULT:` line:
    error, then no tasks, then unfinished tasks, else success (DEC-111)
  - `_result_line(task) -> str` — main file, iterations and the first
    non-empty output line, cut to `RESULT_EXCERPT_CHARS`
  - `_print_state(state)` — prints the spec and tasks whenever the PM
    produced them (also after a later error), each task's result line, the
    workspace and its files, then the error
  - `main()` — prints the verdict last; `--json` prints only the state; the
    exit code follows `_verdict` in both modes
- **Run it yourself:** `.venv/bin/python -m pytest tests/test_main.py -v`
- **Review notes:** closed without answering the review questions, at the
  user's request.

### T4 — Coder server rule and real-model runs · done

- **Covers:** AC-2.3-15, AC-2.3-16, AC-2.3-17
- **Map:**
  - Files: `agents/coder_agent.py` (prompts), `tools/handlers.py` (server
    guard), `tests/api_fixture.py` (new), `tests/test_server_guard.py`
    (new), `tests/test_integration_coder.py`, `tests/test_integration_pipeline.py`
  - `CODER_SYSTEM_PROMPT`, `PLAN_SYSTEM_PROMPT` — never run a server file;
    keep its `__main__` block; verify with a check script (DEC-112)
  - `_server_start(path) -> str | None`, `_server_refusal(path, call) -> str`
    — `dispatch_tool` refuses `exec_python` on a file that creates a Flask
    app and calls its `.run(`, or calls `uvicorn.run(` / `.serve_forever(`
    (DEC-116)
  - `find_api(code) -> str` — the one file that creates `Flask(` and names
    both routes; `check_in_process(api_file)` — the three requests through
    the test client in a subprocess; `check_real_server(api_file)` — `python
    <file>` in its own process group, the same requests over HTTP
- **Run it yourself:** `.venv/bin/python -m pytest --run-llm -v tests/test_integration_coder.py::test_ac_2_2_15_demo_tasks tests/test_integration_pipeline.py::test_ac_2_3_16_graded_demo`
- **Review notes:** the first real runs showed that a prompt rule is not
  enough for `gpt-4.1-mini`: its plan said "run app.py" and it then hit
  the timeout or removed the `__main__` block (4 of 5 runs of AC-2.3-15).
  Agreed fix: the code guard of DEC-116 (AC-2.3-17) plus firmer prompts.
  `find_api` looks for `Flask(` because the check scripts mention the
  routes too. AC-2.3-15 also checks the real server. After the fix:
  AC-2.3-15 passed 3 times in a row, AC-2.3-16 twice, and the whole suite
  with `--run-llm` passed (93 tests).

### T5 — Module 2 README · done

- **Covers:** C2.6 (diagram of PM, Coder, shared state and data flow;
  instructions that match the system) — `manual`
- **Map:** `README.md`: current state (Module 2), framework unchanged plus
  `PM_MODEL`, "Running the team" (`main.py`, output, `RESULT:` verdict and
  exit codes, workspace archive, trying the generated API), "How the team
  works" (Mermaid diagram of the graph and the state's reads and writes,
  steps, `ProjectState` field table), tests by area and the `llm` tests,
  layout, design decisions by C2.1–C2.6.
- **Run it yourself:** `python main.py; echo $?` and compare the output with
  "Running the team"; `python main.py ""; echo $?` → 2.
- **Review notes:** the diagram's edges match
  `build_graph().get_graph().draw_mermaid()` (START→pm, pm→coder, pm→END,
  coder→coder, coder→END); every DEC cited exists; each README command was
  run. A real `python main.py` run (2026-11-11) matched the documented
  output: the API passed the request fixture in-process and as a real
  server, but the PM planned a third task, "Add requirements.txt", that
  cannot be executed, so it ended `failed` and the verdict was
  `RESULT: incomplete — task_3 failed` (exit 1). Raised for the
  independent review.

### R1a — Robust graded demo · done

- **Covers:** AC-2.3-18, AC-2.3-19 (and AC-2.3-22 at the end of R1)
- **Map:** `TASKS_SYSTEM_PROMPT` rule and a `TaskDraft.files` validator
  (at least one `.py`); the request fixture adds three non-JSON bodies
  that must get 400; the Coder's API rule asks for
  `get_json(silent=True)` and a 400 when it is None.
- **Run it yourself:** `pytest tests/test_api_fixture.py tests/test_pm_agent.py -k "2_3"`
- **Review notes:** the fixture's HTTP requests moved from `urllib` to
  `http.client`, because `urllib` adds a form Content-Type to every POST
  and could not send a body without one. The validator lives on
  `TaskDraft` (the LLM's output), not on `TaskSpec`, so state built in
  code is not constrained.

### R1b — Priority and live progress · todo

- **Covers:** AC-2.3-20, AC-2.3-21; AC-2.3-6 checks the task ID
- **Map:** `_next_pending` returns the pending task with the lowest
  priority; `run()` logs each new progress note at INFO as the step that
  wrote it ends.

## Independent review

- **Date:** 2026-11-11
- **Findings and triage:**

| ID | Severity | Finding | Triage |
|---|---|---|---|
| F1 | high | The PM may plan a task with no Python code (e.g. "Add requirements.txt"); it can never end `success`, so the demo ends `incomplete` with a working API (seen in the T5 real run) | Fix in R1 |
| F2 | medium | The request fixture's only invalid input is malformed JSON with a JSON content type; a body with another or no content type gets 415 from Flask's `get_json()`, so an assessor fixture may fail | Fix in R1 |
| F3 | medium | With the API file never run, `success` can rest on any script run after the last write, even one that never touches the API | IMP-012; limit noted in DEC-116 |
| F4 | low | The server guard misses some patterns (annotated assignment, `waitress.serve`, `create_app().run()`) and refuses a check script that names `app.run(` | IMP-013 |
| F5 | low | AC-2.3-6 does not check that the Coder receives the task ID; the Coder takes tasks by list position, not by `priority` | Fix in R1 |
| F6 | low | Progress notes are printed only at the end of the run; nothing shows each task as it completes | Fix in R1 |
| F7 | low | `agents/coder_agent.py` went from CRLF to LF in T4 (1724 changed lines for 16) | Separate `chore` commit (`.gitattributes`) |
| F8 | plausible | Chroma memories outlive the archived workspace; the Coder may recall a file that no longer exists | IMP-014 |
| F9 | plausible | A misconfigured `WORKSPACE_DIR` outside the repo has its contents archived | Discarded: user configuration, moved not deleted, documented in the README |

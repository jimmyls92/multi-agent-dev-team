# Spec: Lab 3.2 — QA agent

- **Status:** done
- **Sources:** lab handout `docs/labs/lab_3_2_qa_agent.md`, project guide
  (Module 3, `docs/course_reference.txt`, instructions 15 and 20), rubric
  C3.1, C3.3, C1.3, C4.5, C4.6
- **Decisions:** DEC-137..DEC-161; also DEC-122, DEC-124, DEC-125, DEC-039,
  DEC-040, DEC-044, DEC-088, DEC-091 (the why lives there; do not repeat it
  here)

## Goal

A QA agent, `agents/qa_agent.py`, takes one task of the PM's handoff, reads
the Coder's files through the Lab 3.1 MCP server, writes pytest tests for
the task's acceptance criteria into its own folder, runs them in a
sandboxed subprocess with a timeout, and returns a typed `QAReport`: issues
with severity, location, description, fix instruction, source and
criterion, and an `approved` flag that only executed tests can grant. An
LLM review adds advisory issues. The QA is standalone: the graph node and
the Coder↔QA loop come in Lab 3.3 (DEC-143).

## Lab vs project

| Lab says | Project requires | What we do |
|---|---|---|
| QA = LLM review of the file, returns `IssueList` | C3.1: real pytest tests, run in a subprocess with a timeout; LLM-only review is Not Yet | QA writes and runs pytest; the LLM review is a second, advisory source (DEC-137) |
| Reviews `word_counter.py` | Tests against acceptance criteria (C3.1) | Input is a `TaskSpec`; tests cover its Given/When/Then criteria (DEC-138) |
| `approved=False` when any High issue | Loop exits when all tests pass (C3.2) | Failing test = High; review only Medium/Low; `QA_BLOCKING_SEVERITY` threshold, default `High`; never approved without a test run (DEC-139) |
| `Issue(severity, location, description)` | C3.1: structured issues and fix instructions | Adds `fix`, `source`, `criterion`; `QAReport` computes `approved` (DEC-149) |
| `_read_file_via_mcp` reads one file | QA reads only, never writes the Coder's code (DEC-122) | Reads the task's files through MCP; tests run in place from `workspace_qa/` (DEC-140, DEC-145) |
| `openai` client with `beta.chat.completions.parse`, `gpt-4.1-mini` | C1.3: validated LLM output; C4.5: small model for QA | `structured_call` with a per-task schema (DEC-148); `QA_MODEL`, default `openai/gpt-4.1-mini` (DEC-150) |
| `run_qa_agent` async | Lab 3.3 calls it from an asyncio broker | `run_qa` async (DEC-150) |
| One LLM call, no retries | C4.6: no crash; C3.3: never claim success | `QA_MAX_ATTEMPTS` budget for its own broken output (DEC-141); any failure returns an unapproved report (DEC-142) |
| `python main.py` prints the issue list | `main.py` is the pipeline | Demo `python -m agents.qa_agent` |
| `workspace/` (implicit) | Separate folders per agent | `workspace_coder/` and `workspace_qa/`, `CODER_WORKSPACE_DIR`, `QA_WORKSPACE_DIR` (DEC-140, DEC-151) |

## Acceptance criteria

`Origin`: `C<x>.<y>` (rubric), `lab` or `ours`.
`Verify`: `unit` (fake model), `integration`, `llm` (real key, `--run-llm`)
or `manual`.

"Fake model" = `tests/fakes.py::ScriptedChatModel` replaying fixed replies.
"Real server" = the Lab 3.1 MCP server started over stdio by the QA,
serving a temporary `CODER_WORKSPACE_DIR`. "Linked-list task" = a
`TaskSpec` `task_1` with files `["linked_list.py"]` and two criteria:
(0) Given an empty list, When `insert(5)`, Then `search(5)` is `True`;
(1) Given a list built with `insert(1)` then `insert(2)`, When `insert(3)`,
Then `to_list()` is `[3, 2, 1]`.

### Folders and settings

#### AC-3.2-1 — The Coder works in `CODER_WORKSPACE_DIR`

- **Origin:** ours, DEC-140, DEC-151
- **Verify:** unit — `tests/test_workspace_settings.py::test_ac_3_2_1_coder_workspace_dir`
- **Given** `CODER_WORKSPACE_DIR` unset, and separately set to `other`
- **When** `tools.handlers` is loaded
- **Then** the Coder's folder is `<repo>/workspace_coder`, and `<repo>/other`
  respectively; the Coder's file tools and the MCP client's default use it

#### AC-3.2-2 — An old `WORKSPACE_DIR` is never ignored silently

- **Origin:** ours, DEC-151
- **Verify:** unit — `tests/test_workspace_settings.py::test_ac_3_2_2_old_variable_rejected`
- **Given** `WORKSPACE_DIR=workspace` set and `CODER_WORKSPACE_DIR` unset
- **When** `tools.handlers` is loaded
- **Then** it raises `ValueError` whose message names `CODER_WORKSPACE_DIR`

#### AC-3.2-3 — No regression of Modules 1-2 and Lab 3.1

- **Origin:** C1.1-C3.5 (regressions count)
- **Verify:** integration — `pytest` (whole suite)
- **Given** the rename of T1
- **When** the whole suite runs
- **Then** every test passes

#### AC-3.2-4 — QA settings are checked at startup

- **Origin:** ours, DEC-151, DEC-152, DEC-154
- **Verify:** unit — `tests/test_qa_report.py::test_ac_3_2_4_qa_settings`
- **Given** the QA settings unset; then `QA_MAX_ATTEMPTS` set to `0` and to
  `x`; then `QA_BLOCKING_SEVERITY` set to `Critical`; then
  `QA_TEST_TIMEOUT` set to `0` and to a value not lower than `EXEC_TIMEOUT`;
  then `QA_WORKSPACE_DIR` set to the Coder's folder, to a folder inside it
  and to the folder that contains it
- **When** the QA settings are loaded
- **Then** the defaults are `workspace_qa`, `openai/gpt-4.1-mini`, 2,
  `High` and a per-test timeout of 2 s; each invalid value raises
  `ValueError` naming its variable
- **Changed by DEC-174** (Lab 3.3): there is no `QA_BLOCKING_SEVERITY`; a leftover value only logs a WARNING (DEC-191, AC-3.3-11).

### Report

#### AC-3.2-5 — Issues are validated

- **Origin:** lab, C1.3, DEC-149
- **Verify:** unit — `tests/test_qa_report.py::test_ac_3_2_5_issue_validation`
- **Given** issue data with severity `Critical`, with source `opinion`,
  without `fix`, and a review issue with severity `High`
- **When** each is validated as an `Issue` inside a `QAReport`
- **Then** each raises a validation error; a `test` issue with severity
  `High` and a `review` issue with severity `Low` are accepted
- **Changed by DEC-174** (Lab 3.3): the `review` source no longer exists, so any `review` issue is rejected; `test` and `qa` issues must be High.

#### AC-3.2-6 — `approved` follows the rule, whatever value it is given

- **Origin:** lab, C3.3, DEC-139, DEC-149
- **Verify:** unit — `tests/test_qa_report.py::test_ac_3_2_6_approved_rule`
- **Given** reports built with `approved=True` for these cases:
  (a) 2 tests passed, a `review` Medium issue, threshold `High`;
  (b) same, threshold `Medium`; (c) 1 passed and 1 failed with its `test`
  High issue, threshold `High`; (d) no test ran, no issues, threshold `Low`;
  (e) a `qa` High issue, no test ran
- **When** each report is validated
- **Then** `approved` is True only in (a)
- **Changed by DEC-174** (Lab 3.3): no threshold: a report is approved only if some test passed, none failed and it has no issue; cases (a) with no issue, (c), (d) and (e).

### Running pytest

All in `tests/test_code_executor.py`, with a temporary Coder folder and QA
folder; no model.

#### AC-3.2-7 — A passing suite is reported as passed

- **Origin:** C3.1
- **Verify:** integration — `test_ac_3_2_7_pytest_passes`
- **Given** a Coder file `calc.py` with `add` and a QA test file with two
  correct tests that import it
- **When** `run_pytest` runs the test file
- **Then** the result is `passed` with 2 passed, 0 failed and no failures

#### AC-3.2-8 — A failing assertion is reported with its test and message

- **Origin:** C3.1, DEC-147
- **Verify:** integration — `test_ac_3_2_8_pytest_failure`
- **Given** `calc.py` whose `add` subtracts, and a test asserting
  `add(2, 3) == 5`
- **When** `run_pytest` runs it
- **Then** the result is `failed` with 1 failure naming the test and whose
  message contains `assert` and `-1`

#### AC-3.2-9 — Tests that cannot be collected are told apart

- **Origin:** DEC-141, DEC-147
- **Verify:** integration — `test_ac_3_2_9_pytest_collection_error`
- **Given** a test file that raises `NameError` at import, and separately
  one with no test functions
- **When** `run_pytest` runs each
- **Then** each result is `collection_error`, not `failed`, with the error
  text in the output

#### AC-3.2-10 — A hanging test fails alone; a hanging run is killed

- **Origin:** C3.1, C1.3, DEC-152
- **Verify:** integration — `test_ac_3_2_10_pytest_timeout`
- **Given** (a) two tests, one calling a Coder function that loops forever
  and one correct, with a per-test timeout of 1 s and a run timeout of
  5 s; (b) a Coder module that loops forever when imported, and a test
  importing it, with a run timeout of 2 s
- **When** `run_pytest` runs each
- **Then** (a) returns `failed`: the hanging test is a timeout failure
  whose traceback names the Coder file, the other test passed; (b)
  returns within 5 s with result `timed_out`, and no process of the run
  is left alive

#### AC-3.2-11 — pytest runs in the sandbox and leaves the Coder's folder clean

- **Origin:** C1.3, DEC-039, DEC-145
- **Verify:** integration — `test_ac_3_2_11_pytest_sandbox`
- **Given** `OPENROUTER_API_KEY=secret` in the agent's environment, a Coder
  folder with `data.txt` and `reader.py`, and tests asserting that the key
  is absent and that `reader.read()` returns the content of `data.txt`
  (opened with a relative path)
- **When** `run_pytest` runs them
- **Then** both pass; the Coder folder holds exactly `data.txt` and
  `reader.py` afterwards (no `__pycache__`, no `.pytest_cache`); the JUnit
  report is in the QA folder

### Writing tests

All in `tests/test_qa_agent.py`, with the fake model and the linked-list
task; `QA_MAX_ATTEMPTS=2` unless stated.

#### AC-3.2-12 — A valid draft becomes the task's test file

- **Origin:** C3.1, DEC-148
- **Verify:** unit — `test_ac_3_2_12_writes_test_file`
- **Given** a draft with a preamble and one test per criterion
- **When** the QA writes the tests
- **Then** `workspace_qa/task_1/test_task_1.py` holds the preamble and both
  tests, and each test name is mapped to its criterion index

#### AC-3.2-13 — An invalid draft is never written or run, and the model is told why

- **Origin:** C1.3, DEC-148, DEC-159
- **Verify:** integration — `test_ac_3_2_13_invalid_draft_rejected`
- **Given** a first draft that is invalid in one way (parametrized: a
  syntax error; two tests with the same name; a name that does not start
  with `test_`; a name that the code does not define; criterion 1 without a
  test; a preamble with a statement other than an import, a function or a
  class, such as `ll = LinkedList()`; a test whose code has another
  top-level statement besides its function; a name used but never imported
  or defined, such as `LinkedList` without its import) and a valid second
  draft
- **When** `run_qa` runs the task
- **Then** only the valid draft is written; the second model call contains
  the validation error of the first

#### AC-3.2-14 — The QA stops after `QA_MAX_ATTEMPTS` broken attempts

- **Origin:** DEC-141, C3.3
- **Verify:** unit — `test_ac_3_2_14_attempt_budget`
- **Given** a model whose drafts are always invalid, and separately one
  whose drafts always fail to collect
- **When** `run_qa` runs the task
- **Then** the model is called exactly 2 times for tests; the report is not
  approved and holds one `qa` High issue saying no runnable tests could be
  produced; no `test` issue is reported

#### AC-3.2-15 — A test file that breaks at collection is regenerated

- **Origin:** DEC-141, DEC-152
- **Verify:** unit — `test_ac_3_2_15_test_collection_error_regenerates`
- **Given** a correct `linked_list.py`, a first draft that passes the
  checks of AC-3.2-13 but whose test has a `pytest.mark.parametrize` with
  an argument name its function does not take, and a valid second draft
- **When** `run_qa` runs the task
- **Then** the second test call contains the collection error; the report
  comes from the second draft's run

#### AC-3.2-16 — Imports are checked before running, and each bad import is blamed on its owner

- **Origin:** ours, DEC-152
- **Verify:** unit — `test_ac_3_2_16_import_check`
- **Given** a draft importing (parametrized):
  (a) `from linkedlist import LinkedList`, a module that is neither a task
  file nor installed;
  (b) `from linked_list import LinkedList` with no `linked_list.py` in the
  Coder folder;
  (c) the same with a `linked_list.py` that does not define `LinkedList`
  (the task names `LinkedList`);
  (d) `from linked_list import Node` with a `linked_list.py` that does not
  define `Node` (the task never names `Node`);
  in (a) and (d) followed by a valid second draft
- **When** `run_qa` runs the task
- **Then** pytest never runs the bad draft; in (a) and (d) the second test
  call contains the import problem and the report comes from the second
  draft; in (b) and (c) no new draft is requested and the report is not
  approved, with a `test` High issue naming the missing file or name

#### AC-3.2-17 — A Coder module that breaks at collection is the Coder's issue

- **Origin:** ours, DEC-152
- **Verify:** unit — `test_ac_3_2_17_coder_collection_error`
- **Given** a `linked_list.py` that defines `LinkedList` and then raises
  `RuntimeError` at import, and a valid draft
- **When** `run_qa` runs the task
- **Then** no new test draft is requested; the report is not approved and
  holds a `test` High issue whose description contains the `RuntimeError`
  and names `linked_list.py`

### Running the QA

All in `tests/test_qa_agent.py`, with the fake model, the real server and
the linked-list task.

#### AC-3.2-18 — The QA reads the task's files through MCP

- **Origin:** lab, DEC-140, DEC-158
- **Verify:** integration — `test_ac_3_2_18_reads_through_mcp`
- **Given** a Coder folder with `linked_list.py` whose `LinkedList` has a
  typed, decorated method and a typed class field
- **When** `run_qa` runs the task
- **Then** the server's stderr log has a `read_file` line for
  `linked_list.py`; the first test-writing model call contains both
  criteria and the file's interface (class, method signatures with types
  and defaults, decorators, the typed field, docstrings) but not the
  bodies of its methods

#### AC-3.2-19 — Correct code is approved

- **Origin:** C3.1, C3.2
- **Verify:** integration — `test_ac_3_2_19_correct_code_approved`
- **Given** a correct `linked_list.py`, a valid draft and a review with one
  Low issue
- **When** `run_qa` runs the task
- **Then** the report is approved with 2 passed tests and holds the Low
  `review` issue
- **Changed by DEC-174** (Lab 3.3): no review runs on correct code, so the report holds no issue (AC-3.3-8).

#### AC-3.2-20 — A failing test becomes a High issue linked to its criterion

- **Origin:** C3.1
- **Verify:** integration — `test_ac_3_2_20_failure_becomes_issue`
- **Given** a `linked_list.py` whose `insert` appends at the tail, a valid
  draft, and a review that gives a fix for the failing test
- **When** `run_qa` runs the task
- **Then** the report is not approved and holds a `test` High issue whose
  `criterion` is criterion 1's text, whose description contains the
  assertion message, and whose `fix` is the review's fix

#### AC-3.2-21 — Without a review, tests still decide under the default threshold

- **Origin:** DEC-142, DEC-149
- **Verify:** integration — `test_ac_3_2_21_review_unavailable`
- **Given** a review call that never returns valid output; (a) correct code
  with threshold `High`; (b) the tail-append code with threshold `High`;
  (c) correct code with threshold `Medium`
- **When** `run_qa` runs the task
- **Then** (a) is approved with the note "review unavailable"; (b) is not
  approved and its `test` issue has the fix "Make <test> pass; it failed
  with: ..."; (c) is not approved
- **Changed by DEC-174** (Lab 3.3): only case (b) remains: the failing test keeps its default fix and the note "review unavailable"; no `qa` issue is added.

#### AC-3.2-22 — A hang is blamed on the file where it hangs

- **Origin:** C3.1, C3.3, DEC-152
- **Verify:** integration — `test_ac_3_2_22_timeouts`
- **Given** `QA_TEST_TIMEOUT=1` and `EXEC_TIMEOUT=5`; (a) a `linked_list.py`
  whose `search` loops forever and a valid draft; (b) a correct
  `linked_list.py`, a first draft whose criterion-1 test loops forever in
  its own code and a valid second draft; (c) a `linked_list.py` that loops
  forever when imported
- **When** `run_qa` runs the task
- **Then** each returns within 15 s. (a) is not approved: the criterion-0
  test is a `test` High issue saying it timed out in `linked_list.py`,
  and the criterion-1 test still ran; (b) the second test call contains
  the timeout of the first draft and the report comes from the second
  draft; (c) is not approved with a `test` High issue saying the whole
  run timed out

#### AC-3.2-23 — Failures outside the QA's control return an unapproved report

- **Origin:** C3.3, C4.6, DEC-142
- **Verify:** integration — `test_ac_3_2_23_failures_reported`
- **Given** (a) an MCP server that cannot start; (b) a model that raises on
  the test call
- **When** `run_qa` runs the task
- **Then** no exception escapes; each report is not approved and holds a
  `qa` High issue naming the cause

#### AC-3.2-24 — The Coder's folder is never changed

- **Origin:** DEC-122, DEC-140, DEC-145
- **Verify:** integration — `test_ac_3_2_24_coder_folder_untouched`
- **Given** a Coder folder and the names, sizes and contents of its files
- **When** `run_qa` runs the task, once with passing and once with failing
  tests
- **Then** the Coder folder is identical afterwards; every file the QA
  wrote is under `workspace_qa/task_1/`

#### AC-3.2-25 — Each QA step is logged

- **Origin:** C3.1 (evidence), ours
- **Verify:** integration — `test_ac_3_2_25_steps_logged`
- **Given** the run of AC-3.2-20
- **When** `caplog` captures the QA's logger
- **Then** there are INFO records for the files read, the test file
  written, the pytest command with its timeout and counts, and the
  verdict with the number of blocking issues

#### AC-3.2-26 — Live: the QA catches a planted bug and approves correct code

- **Origin:** C3.1, lab
- **Verify:** llm — `test_ac_3_2_26_live_qa`
- **Given** the real model and server; the tail-append `linked_list.py`,
  then a correct one
- **When** `run_qa` runs the linked-list task on each
- **Then** the first report is not approved with at least one `test` High
  issue whose `criterion` is criterion 1; the second is approved

#### AC-3.2-27 — Demo

- **Origin:** lab
- **Verify:** manual — `python -m agents.qa_agent`; run on 2026-11-23:
  `docs/evidence/lab_3_2/ac_3_2_27_qa_agent.log`
- **Given** a key in `.env`
- **When** the demo runs
- **Then** it runs the QA on a bundled buggy linked list in a temporary
  Coder folder and prints the verdict, the tests run and each issue with
  severity, location, criterion and fix

### Review fixes (R1)

All in `tests/test_qa_agent.py`, with the fake model, the real server and
the linked-list task.

#### AC-3.2-28 — A skipped test never counts towards approval

- **Origin:** C3.3, DEC-141
- **Verify:** integration — `test_ac_3_2_28_skips_never_approve`
- **Given** the tail-append `linked_list.py` and a first draft whose
  criterion-1 test, in three variants, is decorated with
  `pytest.mark.xfail`, calls `pytest.skip`, or is decorated with
  `pytest.mark.skipif(True, ...)`, then a valid second draft
- **When** `run_qa` runs the task
- **Then** the second test call contains the rejection of the skip; the
  report comes from the second draft and is not approved

#### AC-3.2-29 — The run timeout grows with the number of tests

- **Origin:** C3.1, DEC-161
- **Verify:** integration — `test_ac_3_2_29_run_timeout_scales`
- **Given** `QA_TEST_TIMEOUT=1`, `EXEC_TIMEOUT=3`, a `linked_list.py` whose
  `insert` loops forever and a draft with 4 tests that all call `insert`
- **When** `run_qa` runs the task
- **Then** the run is not stopped as a whole: the report holds 4 `test`
  High issues, each saying its test timed out in `linked_list.py`

#### AC-3.2-30 — A failing parametrized test keeps its criterion

- **Origin:** C3.1, DEC-149
- **Verify:** integration — `test_ac_3_2_30_parametrized_failure_criterion`
- **Given** the tail-append `linked_list.py` and a draft whose criterion-1
  test is parametrized with one case
- **When** `run_qa` runs the task
- **Then** its `test` issue's `criterion` is criterion 1's text

#### AC-3.2-31 — A task file the server cannot read is reported with the reason

- **Origin:** C4.6, DEC-152
- **Verify:** integration — `test_ac_3_2_31_unreadable_task_file`
- **Given** a `linked_list.py` that is not valid UTF-8 and a valid draft
- **When** `run_qa` runs the task
- **Then** pytest does not run; the report is not approved and holds a
  `test` High issue saying `linked_list.py` could not be read, with the
  server's reason, not that it was not found

## Tasks

Task status: todo | map | in progress | review | done

### T1 — Rename the Coder's folder to `workspace_coder/` · done

- **Covers:** AC-3.2-1, AC-3.2-2, AC-3.2-3
- Commit type `refactor`; `.env.example`, `.gitignore`, README and
  `CLAUDE.md` references updated; the local `workspace/` is moved by hand.

### T2 — `Issue`, `QAReport` and QA settings · done

- **Covers:** AC-3.2-4, AC-3.2-5, AC-3.2-6

### T3 — `run_pytest` on the shared sandbox · done

- **Covers:** AC-3.2-7 .. AC-3.2-11

### T4 — Test writing with validation · done

- **Covers:** AC-3.2-12, AC-3.2-13, AC-3.2-14 (invalid drafts: exactly
  `QA_MAX_ATTEMPTS` test calls and no file written; the `qa` issue in the
  report is checked in T5, once `run_qa` exists)
- The call budget shared with collection errors (DEC-141) comes in T6.

### T5 — `run_qa`: MCP read, test run and report · done

- **Covers:** AC-3.2-18, AC-3.2-20 (fallback fix), AC-3.2-23, AC-3.2-24,
  AC-3.2-25, AC-3.2-14 (invalid drafts: the `qa` issue in the report)
- Until T6, a run whose status is `collection_error`, `timed_out` or
  `error` gives a `qa` High issue, a timed-out test is a plain `test`
  failure, and a task file the server cannot read is skipped with a
  warning; T6 replaces these with the blame of DEC-152.

### T6 — Blame and regeneration: imports, collection errors, hangs · done

- **Covers:** AC-3.2-14 (collection errors), AC-3.2-15, AC-3.2-16,
  AC-3.2-17, AC-3.2-22; AC-3.2-13 moves to `run_qa`, which now owns the
  retries (DEC-159)

### T7 — LLM review, live test and demo · done

- **Covers:** AC-3.2-19, AC-3.2-20 (review fix), AC-3.2-21, AC-3.2-26,
  AC-3.2-27

### R1 — Fixes from the independent review · done

- **Covers:** AC-3.2-28 .. AC-3.2-31; also review fixes matched by failure
  number, `run_qa`'s `errlog` resolved at call time, the pytest command in
  the log (AC-3.2-25), the cause checked in AC-3.2-23(a), DEC-140's code
  field

README: deferred to the Module 3 delivery, with Lab 3.1's T4.

## Independent review

- **Date:** 2026-11-18
- **Findings and triage:**
  1. High — skipped or xfail tests let a criterion pass unverified → fix
     (R1, AC-3.2-28).
  2. Medium — a whole-run timeout hides per-test results and is always
     worded as an import hang → fix (R1, AC-3.2-29, DEC-161; DEC-152
     corrected).
  3. Low-Medium — a parametrized test loses its criterion → fix (R1,
     AC-3.2-30).
  4. Low — review fixes keyed by location reach the wrong issue when two
     issues share it → fix (R1).
  5. Low — a task file the server rejects is reported as missing → fix
     (R1, AC-3.2-31).
  6. Low — `run_qa`'s `errlog` default bound at import → fix (R1).
  7. Low — weak assertions: AC-23(a) cause and AC-25 command → fix (R1);
     AC-24 checking only the QA folder → discard (the AC asks for the
     Coder folder intact, which the test checks).
  8. Low — stale docs: DEC-140's code field → fix (R1); `CLAUDE.md`
     status → discard (already up to date).

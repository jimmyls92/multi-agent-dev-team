# Spec: Lab 3.3 — A2A Coder↔QA review loop

- **Status:** approved
- **Sources:** lab handout `docs/labs/lab_3_3_a2a_loop.md`, project guide
  (Module 3, `docs/course_reference.txt`, instructions 16-20 and the
  linked-list demo task), rubric C3.2-C3.6; regressions of C1.2, C1.4,
  C1.5, C2.2, C2.3
- **Decisions:** DEC-162..DEC-187; also DEC-057, DEC-077, DEC-099, DEC-101,
  DEC-111, DEC-115, DEC-139, DEC-142, DEC-154, DEC-160 (the why lives
  there; do not repeat it here)

## Goal

The team graph runs `pm → coder → reflect → qa` for each task, in a
bounded loop: the Coder writes the task, evaluates its own version
against a rubric and improves it when it finds High or Medium bugs, and
sends the best version to the QA in an A2A `review_request`. The QA
answers `approved`, `fix_instruction` or `unresolved`. The loop repeats
until the QA approves the task or `QA_MAX_ITERATIONS` reviews are spent,
and the run ends `success` only if every task was approved; otherwise it
ends `unresolved` with a final report and a non-zero exit code.

## Lab vs project

| Lab says | Project requires | What we do |
|---|---|---|
| `Message` dataclass; `Broker` with one asyncio queue per agent; Coder and QA as concurrent tasks | C2.3: one orchestration graph; C3.5: the five fields, intent validation, logs of real use | Pydantic `A2AMessage` in `orchestration/a2a.py`; mailbox in `ProjectState.messages`, `send`/`inbox` only; every message logged (DEC-175) |
| Intents `review_request`, `fix_instruction`, `approved` | C3.3: at the limit the QA returns a final report | Adds `unresolved`, with the final report as payload (DEC-176) |
| `MAX_ITERATIONS` constant in the Coder | C3.3: env variable, default 5, per the QA loop | `QA_MAX_ITERATIONS`, default 5, per task, counted in QA reviews, read per run (DEC-163, DEC-180) |
| Coder fixes `word_counter.py` with one LLM call per iteration | C1.4/C1.5: the ReACT Coder, `result` from a real run | Every pass is a ReACT pass of the Coder (DEC-172, DEC-187) |
| No self-reflection | C3.4: self-critique before QA that drives a revision; guide: "must run at least once and produce a revised output" | `reflect` node: rubric evaluation, diagnosis, improvement on High/Medium bugs, best version sent (DEC-172, DEC-177, DEC-182, DEC-183). A clean version is sent unchanged; C3.4 evidence comes from runs where the critique finds a bug and from the planted-bug test AC-3.3-41 |
| QA = LLM review, `approved` when no High issue | C3.1: executed tests decide | Issues only from executed tests; the LLM only explains failures; `QA_BLOCKING_SEVERITY` removed (DEC-174) |
| Loop stops after `MAX_ITERATIONS` and returns the code | C3.3: never claim success; C2.2: task status in state | Task `failed` with the QA's final report; run `unresolved`, exit code 1 (DEC-164, DEC-165, DEC-181) |
| Mocked tests of `Message`, `Broker` and the loop | C3.6: tests of the QA issue schema (mocked code input), loop success and loop max-iterations; linked-list demo passes generated tests for all four methods | Schema: AC-3.2-5/6 (updated in T3); loop: AC-3.3-29, AC-3.3-30; demo: AC-3.3-40 |
| — | C3.2: a controlled failing case shows QA feedback drives a revision | AC-3.3-31 (fake Coder, real QA run) |
| No timeouts | Evaluator forces timeouts | `LLM_TIMEOUT` per call, `RUN_TIMEOUT` per run, step limit per run (DEC-166, DEC-168, DEC-180) |

## Acceptance criteria

`Origin`: `C<x>.<y>` (rubric), `lab` or `ours`.
`Verify`: `unit` (fake model), `integration`, `llm` (real key, `--run-llm`)
or `manual`.

"Fake model" = `tests/fakes.py::ScriptedChatModel` replaying fixed
replies. "Linked-list task" = the `task_1` of AC-3.2 (files
`["linked_list.py"]`, criteria (0) insert then search, (1) insert order).
"Fake Coder" = a Coder node whose ReACT pass is replaced by a function
that writes a given file and returns a given `CoderResult`. "Fake QA" = a
`run_qa` replaced by a function returning given `QAReport`s in order.
"Bug" in the evaluation means an item with verdict `bug`; "v0" is the
ReACT pass's version, "v1" the improved one.

### A2A messages (DEC-175, DEC-176, DEC-170)

All in `tests/test_a2a.py`; no model.

#### AC-3.3-1 — Messages are validated field by field

- **Origin:** C3.5, lab
- **Verify:** unit — `test_ac_3_3_1_message_validation`
- **Given** message data with (parametrized) an unknown sender, an
  unknown receiver, an unknown intent, `sender == receiver`, an intent
  the receiver does not accept (`approved` to the QA, `review_request`
  to the Coder), and a payload that does not match its intent's model
  (a `review_request` without `task_id`)
- **When** each is validated as an `A2AMessage`
- **Then** each raises a validation error naming the field; valid
  messages for the four intents are accepted, and a message without
  `correlation_id` gets a UUID4

#### AC-3.3-2 — A reply must answer its request

- **Origin:** C3.5, DEC-170, DEC-175
- **Verify:** unit — `test_ac_3_3_2_reply_correlation`
- **Given** a state whose last message is a `review_request` with
  correlation id `c-1`
- **When** the QA sends a reply with `c-2`, and separately a reply with
  `c-1`
- **Then** the reply with `c-2` is rejected with an error naming the
  correlation id and is not added to the state; the reply with `c-1` is
  added

#### AC-3.3-3 — `send` appends and logs; `inbox` returns in order

- **Origin:** C3.5 (log evidence), lab
- **Verify:** unit — `test_ac_3_3_3_send_and_inbox`
- **Given** an empty state
- **When** three valid messages are sent (two to the QA, one to the
  Coder) and `caplog` captures the A2A logger
- **Then** `inbox(state, "qa")` returns the two QA messages in send order
  and `inbox(state, "coder")` the other one; `send` returns the update
  for `ProjectState.messages` without changing any earlier message; each
  message has one INFO record with sender, receiver, intent, task,
  review number and correlation id

#### AC-3.3-4 — Messages survive the state's JSON round trip

- **Origin:** C2.2, C3.5
- **Verify:** unit — `test_ac_3_3_4_messages_serializable`
- **Given** a `ProjectState` with one message of each intent
- **When** it is dumped to JSON and validated back
- **Then** the result equals the original state

### Loop settings (DEC-166, DEC-180)

#### AC-3.3-5 — Loop settings have defaults and are checked when a run starts

- **Origin:** C3.3, DEC-163, DEC-166, DEC-168, DEC-172, DEC-180
- **Verify:** unit — `tests/test_loop_settings.py::test_ac_3_3_5_loop_settings`
- **Given** the loop settings unset; then each of `QA_MAX_ITERATIONS`,
  `RUN_TIMEOUT`, `LLM_TIMEOUT` and `REFLECTION_MAX_ROUNDS` set to `0` and
  to `x`
- **When** the settings are loaded from that environment
- **Then** the defaults are 5 reviews, 1800 s, 60 s and 1 round; each
  invalid value raises `ValueError` naming its variable

#### AC-3.3-6 — Settings are read per run, not at import

- **Origin:** C3.3, DEC-180
- **Verify:** unit — `tests/test_pipeline.py::test_ac_3_3_6_settings_per_run`
- **Given** a fake PM with one task, a fake Coder and a fake QA that
  never approves
- **When** `run()` runs with `QA_MAX_ITERATIONS=2`, then again in the same
  process with `QA_MAX_ITERATIONS=3`
- **Then** the first run makes 2 reviews and the second 3

#### AC-3.3-7 — Every chat model gets `LLM_TIMEOUT`

- **Origin:** DEC-166, DEC-180
- **Verify:** unit — `tests/test_llm_helpers.py::test_ac_3_3_7_llm_timeout`
- **Given** `LLM_TIMEOUT=12`
- **When** `get_chat_model` builds a model
- **Then** the model's timeout is 12 s

### QA (DEC-174, DEC-187)

All in `tests/test_qa_agent.py`, with the fake model, the real server and
the linked-list task.

#### AC-3.3-8 — An approved review makes no review call

- **Origin:** C3.1, DEC-174
- **Verify:** integration — `test_ac_3_3_8_no_review_when_green`
- **Given** a correct `linked_list.py` and a valid draft
- **When** `run_qa` runs the task
- **Then** the report is approved, the model is called only for the
  tests, and the report holds no issue

#### AC-3.3-9 — The review only writes fixes for failures

- **Origin:** C3.1, DEC-174
- **Verify:** integration — `test_ac_3_3_9_review_only_fixes`
- **Given** the tail-append `linked_list.py`, a valid draft, and a review
  reply that also tries to add an issue of its own
- **When** `run_qa` runs the task
- **Then** the report is not approved; it holds only `test` High issues,
  one per failing test, each with the review's fix; the extra issue is
  rejected by the review's schema (corrective retry, DEC-160)

#### AC-3.3-10 — A failing test's issue carries the test's source

- **Origin:** C3.2, DEC-187
- **Verify:** integration — `test_ac_3_3_10_issue_has_test_source`
- **Given** the run of AC-3.3-9
- **When** the failing test's issue is read
- **Then** it holds the source of that test function exactly as written
  in `workspace_qa/task_1/test_task_1.py`

#### AC-3.3-11 — `QA_BLOCKING_SEVERITY` and the `review` source are gone

- **Origin:** DEC-174
- **Verify:** unit — `tests/test_qa_report.py::test_ac_3_3_11_no_review_source`
- **Given** issue data with source `review`
- **When** it is validated as an `Issue`
- **Then** it raises a validation error; `QASettings` has no blocking
  threshold and `.env.example` does not mention `QA_BLOCKING_SEVERITY`

### Self-evaluation (DEC-173, DEC-182, DEC-183, DEC-171)

All in `tests/test_reflection.py`, with the fake model and the linked-list
task.

#### AC-3.3-12 — The evaluation covers every rubric item exactly once

- **Origin:** C3.4, DEC-182, DEC-183
- **Verify:** unit — `test_ac_3_3_12_evaluation_schema`
- **Given** evaluation replies that (parametrized) miss item E4, repeat
  C1, add an item C2 the task does not have, give `n/a` to C0, give a
  `bug` without evidence, give a `bug` with an unknown kind, give a `bug`
  without diagnosis, and give a diagnosis to an `ok` item; each followed
  by a valid reply
- **When** the version is evaluated
- **Then** the second model call contains the validation error of the
  first, and the evaluation comes from the valid reply
- **Changed by DEC-200:** the reply has one field per item, so a repeated
  item cannot be expressed and that case is dropped; a missing item fails
  as a required field and an unknown one as an extra field.

#### AC-3.3-13 — The code maps each defect kind to its severity

- **Origin:** DEC-182
- **Verify:** unit — `test_ac_3_3_13_kind_to_severity`
- **Given** one valid evaluation with one bug of each defect kind
- **When** its bugs are counted by severity
- **Then** `logic_error`, `crash` and `security` count as High;
  `missing_edge_case` and `unclear_error` as Medium;
  `missing_type_annotation`, `style`, `naming` and `docstring` as Low

#### AC-3.3-14 — Versions are ranked High, then Medium, then Low

- **Origin:** DEC-172, DEC-182
- **Verify:** unit — `test_ac_3_3_14_ranking`
- **Given** pairs (v0, v1) of bug counts (High, Medium, Low):
  (1,0,0) vs (0,9,9); (0,1,0) vs (0,0,9); (0,2,0) vs (0,1,5);
  (0,0,1) vs (0,0,1); (0,0,0) vs (0,0,1)
- **When** the best version is chosen
- **Then** v1, v1, v1, v1 (tie) and v0 are chosen

#### AC-3.3-15 — The evaluation sees only the files and the task, with no memory

- **Origin:** DEC-173, DEC-186
- **Verify:** unit — `test_ac_3_3_15_evaluation_context`
- **Given** a version whose `CoderResult` has a recognisable `plan`,
  `explanation` and `result`, a window with one turn and a Chroma store
  with one memory
- **When** the version is evaluated
- **Then** the model call contains the files' contents, the task and its
  criteria and none of the `plan`, `explanation`, `result`, window turn
  or memory; the window is unchanged and nothing is stored in or read
  from Chroma

#### AC-3.3-16 — An evaluation with no valid output lets the code go as it is

- **Origin:** DEC-171
- **Verify:** unit — `test_ac_3_3_16_evaluation_unavailable`
- **Given** an evaluation model whose replies are always invalid
- **When** the `reflect` node runs on v0
- **Then** the model is called twice; no improvement pass runs; v0 is
  sent unchanged and a WARNING record says "critique unavailable"

### Context of each Coder pass (DEC-184, DEC-187)

All in `tests/test_coder_node.py`, with the fake model and the linked-list
task.

#### AC-3.3-17 — The first pass gets the task and the files that already exist

- **Origin:** DEC-187
- **Verify:** unit — `test_ac_3_3_17_first_pass_prompt`
- **Given** a task with planned files `linked_list.py` and `utils.py`; on
  disk `linked_list.py` (written by an earlier task), a file `big.py`
  from another task, and no `utils.py`; separately a `linked_list.py`
  larger than the read tool's cap
- **When** the first pass of the task builds its prompt
- **Then** the prompt holds the project, the task, its criteria and the
  contents of `linked_list.py`; `big.py` appears by name only; there is
  no Background section; the oversized file is cut at the cap and marked
  as truncated

#### AC-3.3-18 — The improvement pass gets the bugs to fix before the pending ones

- **Origin:** C3.4, DEC-183, DEC-187
- **Verify:** unit — `test_ac_3_3_18_improvement_prompt`
- **Given** an evaluation of v0 with one High bug, one Medium bug and one
  Low bug, each with its diagnosis, and the regressions of a discarded
  attempt
- **When** the improvement pass builds its prompt
- **Then** the "to fix" section holds the High and the Medium bugs with
  location, evidence, cause and fix, and the regressions; the Low bug
  appears after it, in the pending section, marked "only if trivial and
  safe"; the current files' contents are included

#### AC-3.3-19 — The correction pass gets the failed tests, the history and the pending bugs

- **Origin:** C3.2, DEC-184, DEC-187
- **Verify:** unit — `test_ac_3_3_19_correction_prompt`
- **Given** a task at review 3 whose history holds reviews 1 and 2 (test
  `test_reverse_single` failed in both), a `fix_instruction` whose
  report has that test failing again with its fix and test source, and a
  last evaluation that left one Medium and one Low bug
- **When** the correction pass builds its prompt
- **Then** the "to fix" section holds the failed test's name, criterion,
  error, fix and source; the Background section lists reviews 1 and 2
  with what was sent, the self-evaluation result and the QA result, and
  marks `test_reverse_single` as failing for the 3rd time; the Medium and
  Low bugs appear after the "to fix" section

#### AC-3.3-20 — Coder passes keep using both memory layers

- **Origin:** C1.2, DEC-185, DEC-186
- **Verify:** unit — `test_ac_3_3_20_passes_use_memory`
- **Given** a task that takes one ReACT pass, one improvement pass and
  one correction pass
- **When** the passes run with a fake model that records its requests
- **Then** every Coder model call (plans included) contains the recalled
  memories and the window turns; the window gains one turn per pass;
  each pass's prompt is stored in Chroma

### Self-reflection node (DEC-172, DEC-177, DEC-182)

All in `tests/test_reflection.py`, with a fake Coder and the fake
evaluation model.

#### AC-3.3-21 — A version with only Low bugs goes straight to the QA

- **Origin:** C3.4, DEC-182
- **Verify:** unit — `test_ac_3_3_21_low_only_sent`
- **Given** an evaluation of v0 with two Low bugs and no High or Medium
- **When** the `reflect` node runs
- **Then** no improvement pass runs; v0 is the version sent; an INFO
  record lists the evaluation's bugs and says no improvement was needed

#### AC-3.3-22 — A High or Medium bug starts one improvement, and the better version is sent

- **Origin:** C3.4, DEC-172
- **Verify:** unit — `test_ac_3_3_22_improvement_sent`
- **Given** v0 with one High bug, and an improvement pass that writes v1
  evaluated with no bugs
- **When** the `reflect` node runs with `REFLECTION_MAX_ROUNDS=1`
- **Then** exactly one improvement pass runs; v1 is on disk and its
  `CoderResult` is the one sent; INFO records show the critique item
  (item, location, cause), v0 and v1 bug counts and the version chosen

#### AC-3.3-23 — A worse improvement is discarded and v0 restored on disk

- **Origin:** DEC-172
- **Verify:** unit — `test_ac_3_3_23_worse_improvement_restored`
- **Given** v0 with one Medium bug, and an improvement pass that edits
  `linked_list.py` and creates `helper.py`, evaluated with one High bug
- **When** the `reflect` node runs
- **Then** the Coder folder holds exactly v0's files with v0's contents
  (`helper.py` removed); v0's `CoderResult` is sent

#### AC-3.3-24 — A later improvement starts from the best version and gets the regressions

- **Origin:** DEC-172
- **Verify:** unit — `test_ac_3_3_24_regressions_passed_on`
- **Given** `REFLECTION_MAX_ROUNDS=2`; v0 with one Medium bug on E1 and
  `ok` on C0; v1 with C0 now a High bug
- **When** the `reflect` node runs
- **Then** the second improvement starts from v0's files and its prompt
  contains the regression of C0 and v1's `explanation`; no more than two
  improvement passes run

#### AC-3.3-25 — On a tie the improved version wins

- **Origin:** DEC-172, DEC-182
- **Verify:** unit — `test_ac_3_3_25_tie_goes_to_improved`
- **Given** v0 with one Medium bug, v1 with a different Medium bug
- **When** the `reflect` node runs
- **Then** v1 is sent

#### AC-3.3-26 — A pass that hit its call limit is still evaluated

- **Origin:** C1.4, C3.4, DEC-172
- **Verify:** unit — `test_ac_3_3_26_limit_pass_evaluated`
- **Given** a ReACT pass that ends with status `max_iterations` and a
  `linked_list.py` on disk
- **When** the `reflect` node runs
- **Then** the evaluation runs on the file on disk and the version chosen
  is sent to the QA

#### AC-3.3-27 — Each review adds one record to the task's history

- **Origin:** C3.2 (evidence), DEC-184
- **Verify:** unit — `tests/test_pipeline.py::test_ac_3_3_27_history_records`
- **Given** a fake Coder, the fake evaluation and a fake QA that fails
  once and then approves
- **When** the task runs
- **Then** `TaskState.history` holds two records, each with the sent
  version's `explanation`, its bug counts and version chosen, and the
  QA's passed and failed tests

### Coder↔QA loop (DEC-163..DEC-165, DEC-169, DEC-170, DEC-176, DEC-178, DEC-179)

All in `tests/test_integration_loop.py` unless stated, with a fake PM,
fake Coder, fake evaluation and fake QA.

#### AC-3.3-28 — The graph runs reflection before the QA

- **Origin:** C3.4, C2.3, DEC-177
- **Verify:** unit — `tests/test_pipeline.py::test_ac_3_3_28_graph_order`
- **Given** the team graph
- **When** a one-task run is streamed
- **Then** the nodes run in the order `pm`, `coder`, `reflect`, `qa`, and
  the task is `in_progress` until the QA answers

#### AC-3.3-29 — The loop ends when the QA approves

- **Origin:** C3.2, C3.3, C3.6
- **Verify:** integration — `test_ac_3_3_29_loop_success`
- **Given** a fake QA that answers `fix_instruction` once and then
  approves
- **When** `run()` runs one task
- **Then** the messages are, in order, `review_request` c-1,
  `fix_instruction` c-1, `review_request` c-2, `approved` c-2; the task is
  `done` with `reviews == 2`; the outcome is `success`

#### AC-3.3-30 — The loop stops at the limit and the QA reports what is unresolved

- **Origin:** C3.3, C3.6
- **Verify:** integration — `test_ac_3_3_30_loop_max_iterations`
- **Given** a fake QA that never approves; `QA_MAX_ITERATIONS` unset, and
  separately set to 3
- **When** `run()` runs one task
- **Then** exactly 5 (resp. 3) `review_request` messages are sent; the
  last QA message is `unresolved` with a final report listing the
  failing tests; no further review starts; the task is `failed`; the
  outcome is `unresolved`

#### AC-3.3-31 — Controlled failing case: QA feedback drives the revision

- **Origin:** C3.2
- **Verify:** integration — `test_ac_3_3_31_feedback_drives_revision`
- **Given** the real QA with the fake test-writing model and the real
  server; a fake Coder that writes the tail-append `linked_list.py`
  first, and a correct one only when its prompt contains the failing
  test's fix
- **When** `run()` runs the linked-list task
- **Then** review 1 fails with a `test` issue for criterion 1; the second
  Coder prompt contains that issue's fix; review 2 runs pytest on the
  corrected file and is approved; both reviews share the task id

#### AC-3.3-32 — A failure of the QA itself is retried once and never charged to the Coder

- **Origin:** DEC-169
- **Verify:** integration — `test_ac_3_3_32_qa_failure_retry`
- **Given** a fake QA whose first report holds only a `qa` issue and the
  second approves; separately, one whose two first reports hold only
  `qa` issues
- **When** `run()` runs one task
- **Then** in the first case the QA runs twice on the same code with no
  Coder pass between, the review number stays 1, and the task is `done`;
  in the second the QA answers `unresolved`, the task is `failed` with
  the reason "the QA could not review it", and the Coder ran once

#### AC-3.3-33 — An invalid A2A message fails only its task

- **Origin:** C3.5, DEC-170
- **Verify:** integration — `test_ac_3_3_33_protocol_error`
- **Given** two tasks, and a fault that makes the QA's reply to task 1
  carry a wrong correlation id
- **When** `run()` runs
- **Then** an ERROR record names the rejected message; task 1 is `failed`
  with a protocol-error issue; task 2 runs and is `done`; the outcome is
  `unresolved`

#### AC-3.3-34 — A failed task does not stop the run

- **Origin:** DEC-164
- **Verify:** integration — `test_ac_3_3_34_next_task_after_failure`
- **Given** two tasks, and a fake QA that never approves task 1 and
  approves task 2 at once
- **When** `run()` runs with `QA_MAX_ITERATIONS=2`
- **Then** task 1 is `failed` after 2 reviews; task 2 is `done` after 1;
  the outcome is `unresolved`

#### AC-3.3-35 — The Coder-only graph keeps its behaviour

- **Origin:** C2.3 (regression), DEC-101, DEC-178
- **Verify:** integration — `pytest` (whole suite)
- **Given** the changes of this spec
- **When** the whole suite runs
- **Then** every test passes, Lab 2.2's `build_coder_graph` tests
  included

### Time limits and outcome (DEC-168, DEC-180, DEC-181)

#### AC-3.3-36 — Out of time closes the remaining tasks

- **Origin:** DEC-168, DEC-180
- **Verify:** integration — `tests/test_integration_loop.py::test_ac_3_3_36_out_of_time`
- **Given** three tasks, `RUN_TIMEOUT=1`, and a fake Coder that sleeps
  2 s during task 1
- **When** `run()` runs
- **Then** task 1's step finishes; the run then goes to `out_of_time`;
  tasks 2 and 3 are `failed` with the reason "out of time"; the outcome
  is `unresolved`

#### AC-3.3-37 — The step limit follows the configured loop

- **Origin:** DEC-115, DEC-180
- **Verify:** unit — `tests/test_pipeline.py::test_ac_3_3_37_step_limit`
- **Given** `QA_MAX_ITERATIONS=2`, and a routing fault that sends the QA
  back to the Coder forever
- **When** `run()` runs
- **Then** the run stops after `1 + MAX_TASKS × 2 × 3 + 3` steps and
  returns the last state with `error` set

#### AC-3.3-38 — The outcome is computed and the final report names each open task

- **Origin:** C3.3, DEC-165, DEC-181
- **Verify:** unit — `tests/test_state.py::test_ac_3_3_38_outcome_and_report`
- **Given** states where (a) all tasks are `done`; (b) one task failed at
  the limit, one by a QA failure, one by a protocol error and one out of
  time
- **When** `outcome` and `final_report()` are read
- **Then** (a) is `success` with an empty report; (b) is `unresolved`, and
  the report lists each of the four tasks with its blocking issues, the
  review it stopped at and its reason; `outcome` is in the JSON dump

#### AC-3.3-39 — `main.py` prints the outcome and exits accordingly

- **Origin:** C3.3, DEC-165, DEC-181
- **Verify:** unit — `tests/test_main.py::test_ac_3_3_39_verdict`
- **Given** final states for (a) success, (b) unresolved, (c) a fatal
  error
- **When** `main()` prints them
- **Then** (a) prints `RESULT: success` and returns 0; (b) prints
  `RESULT: unresolved — …` with the final report and returns 1; (c)
  prints `RESULT: error — …` and returns 1

### Live evidence

#### AC-3.3-40 — The linked-list demo passes its generated tests

- **Origin:** C3.6, guide demo task
- **Verify:** llm — `tests/test_integration_loop.py::test_ac_3_3_40_linked_list_demo`;
  manual — `python main.py "Implement a Python module that contains a linked list class with insert, delete, search, and reverse methods. All methods must be covered by tests."`
- **Given** a key in `.env` and the guide's demo requirement
- **When** the whole team runs
- **Then** the outcome is `success`; the QA's generated tests call each of
  `insert`, `delete`, `search` and `reverse` and all pass; the log shows
  at least one `review_request` and one `approved` message with the same
  correlation id

#### AC-3.3-41 — Live: a planted bug is critiqued and fixed before the QA

- **Origin:** C3.4
- **Verify:** llm — `tests/test_reflection.py::test_ac_3_3_41_live_planted_bug`
- **Given** the real model and the linked-list task; v0 on disk is a
  `linked_list.py` whose `reverse` loses every node after the first
- **When** the `reflect` node runs on v0
- **Then** the evaluation has a High or Medium bug located in `reverse`;
  an improvement pass runs; the version sent fixes it (a `reverse` of
  `[1, 2, 3]` gives `[3, 2, 1]`)

## Tasks

Task status: todo | map | in progress | review | done

### T1 — A2A message and mailbox · done

- **Covers:** AC-3.3-1 .. AC-3.3-4
- `orchestration/a2a.py` (new), `ProjectState.messages` (DEC-175).
- **Review notes:** `Issue`, `QAReport` and `NonEmptyStr` moved to
  `orchestration/qa_report.py` to break the import cycle (DEC-188); the
  correlation check lives in `send` (DEC-189).

### T2 — Loop settings and `LLM_TIMEOUT` · done

- **Covers:** AC-3.3-5, AC-3.3-7
- `.env.example` gains the four settings; AC-3.3-6 is checked in T7, once
  the loop exists.

### T3 — QA explains failures only and returns the test source · done

- **Covers:** AC-3.3-8 .. AC-3.3-11
- Updates the Lab 3.2 ACs that used the threshold or `review` issues
  (AC-3.2-4, AC-3.2-5, AC-3.2-6, AC-3.2-19, AC-3.2-21) and marks them
  changed by DEC-174 in `lab_3_2_qa_agent.md`.

### T4 — Self-evaluation: rubric, diagnosis and ranking · done

- **Covers:** AC-3.3-12 .. AC-3.3-15; AC-3.3-16 for the evaluation (two
  calls, None and the WARNING); that v0 is then sent unchanged is checked
  in T6, once the `reflect` node exists
- **Review notes:** code in `agents/coder_reflection.py` (DEC-192); an item
  may hold several bugs (DEC-193). A live probe on a planted `reverse` bug
  found it as High, but the small model reported it under two items; the
  prompt asks to report each defect once, and the ranking is unaffected
  as long as both versions are judged the same way.

### T5 — Context of each Coder pass and task history · done

- **Covers:** AC-3.3-17 .. AC-3.3-20
- `TaskState.history` and its record model; prompt builders for the three
  kinds of pass.
- **Review notes:** the builders live in `agents/coder_agent.py`, in a
  "Pass prompts" section (DEC-194); prompts put the file contents last
  (DEC-195); planned files outside the workspace are never read (DEC-036).
  The Coder node already uses `first_pass_prompt`, so every task now gets
  its planned files' contents. Tests in `tests/test_coder_passes.py`.

### T6 — `reflect` node: improvement, best version and restore · done

- **Covers:** AC-3.3-21 .. AC-3.3-26, and AC-3.3-16's "v0 is sent
  unchanged"
- **Review notes:** `reflect_task` and `make_reflect_node` in
  `agents/coder_reflection.py`; `Bug` moved to the state and
  `TaskState.reflection` added (DEC-196). Extra tests for DEC-196: an
  unchanged improvement is not evaluated, an unevaluable improvement is
  sent, a failed improvement pass restores the best version, and the node
  needs exactly one task in progress. The node is wired into the graph in
  T7, where the Coder leaves its task `in_progress`.

### T7 — The loop in the graph · done

- **Covers:** AC-3.3-6, AC-3.3-27 .. AC-3.3-35
- `qa` node with `asyncio.run` and the DEC-169 retry; routers;
  `TaskState.reviews`, `qa_report`; DEC-178 node parameter.
- **Review notes (DEC-197):** `reflect` sends the `review_request`; the
  `qa` node writes the task's status with its verdict; settings live in
  `CoderRunContext.settings`, read once by `run()`; `run()`/`build_graph()`
  take `qa_review`; the per-run step limit and `ProjectState.outcome`
  moved here from T8. The Lab 2.3 tests through `run()` and `main()` use a
  clean evaluation and a QA that approves (AC-2.3-13 fails task_2 at the
  QA with `QA_MAX_ITERATIONS=1`; AC-2.3-10 forces the step limit with a
  smaller limit). The evaluation prompt now carries the environment rule
  (DEC-121), so AC-2.3-23 holds for every Coder call. The PM plans at
  least two tasks, so the one-task loop tests have a second task the fake
  QA approves at once.

### T8 — Time limit, step limit and outcome · done

- **Covers:** AC-3.3-36 .. AC-3.3-39
- The step-limit formula and the computed `outcome` already exist (T7,
  DEC-197); T8 adds `deadline` and `out_of_time`, `final_report()`,
  `main.py`'s verdict and the tests of AC-3.3-36 .. AC-3.3-39.
- **Review notes (DEC-198):** `TaskState.closed_reason` is written by the
  `qa` node and `out_of_time`; the deadline is monotonic, with
  `deadline_at` as a readable copy; every router of the team graph checks
  it. AC-3.3-36 also checks that the work done is kept. AC-2.3-13 now
  expects `RESULT: unresolved — task_2 not approved` and the final report
  (DEC-181 supersedes DEC-111's `incomplete`).

### T9 — Live evidence · done

- **Covers:** AC-3.3-40, AC-3.3-41
- The `--run-llm` runs and the manual demo, with their logs kept for the
  README.
- **Review notes:** logs in `docs/evidence/lab_3_3/` (DEC-199). The live
  runs found the evaluation unreliable with the small model; fixed by
  DEC-200 (one field per item, `EVALUATION_MODEL`), measured
  with AC-3.3-41 after each step. AC-3.3-41 compares the last line of its
  check's output, since the Coder may leave debug prints (IMP-022).

README (three-agent diagram, A2A justification, how to tell success from
unresolved, the memory exception of DEC-173): at the Module 3 delivery,
with Lab 3.1's T4.

## Independent review

- **Date:**
- **Findings and triage:**

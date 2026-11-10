# Lab 2.2 — Coder Agent as a self-looping node

**Course:** Build Autonomous Multi-Agent Systems
**Module:** 2 · Lab 2.2 — prepares **C2.2** (per-task status, accumulated
code) and **C2.3** (Coder consumes the handoff inside the same graph);
Instruction 9 of the Module 2 guide (Coder executes tasks in order and
reports progress to shared state after each one).
**Use when:** wrapping the Coder (`agents/coder_agent.py`) as a LangGraph
node, changing how it iterates over tasks or writes to the shared state in
`orchestration/`, or when Lab 2.2 is mentioned.

Gaps between the lab and the project (the project wins; see
`docs/course_reference.txt` Part A2 and C1.3–C1.5, C2.1–C2.6):
- **ReACT loop:** the lab hand-writes the loop with the raw OpenAI client;
  the project already has the Coder as a LangChain `create_agent` graph
  with native tool calling and middleware (DEC-068, DEC-069). It is reused,
  not rewritten.
- **Iteration limit (C1.4):** the lab uses 8; the project uses 10 (DEC-070).
- **Done signal (C1.3):** the lab parses `{"done": true, ...}` from free
  text with `json.loads()` and strips fences by hand; the project ends a
  task only through the validated `Finish` tool (DEC-073).
- **Output (C1.5):** `CodeArtifact` has `code`, `explanation`,
  `tests_suggested`, `status`; the project's `CoderResult` needs `code`,
  `explanation`, `plan` and `result` from a real execution (DEC-065). In
  the lab `code` comes from the LLM's JSON (and is usually empty); in the
  project it must match the file on disk (DEC-052).
- **Shared state (C2.2):** the lab's `CoderState` is a TypedDict with a free
  markdown `tech_spec` and `CodingTask` without priority; the project state
  is Pydantic (`ProjectState`, `ProjectSpec`, `TaskSpec` with `priority`,
  `covers`, `files`) from Lab 2.1 (DEC-089..DEC-094).
- **Per-task status (C2.2):** the lab never updates `tasks[i].status` (the
  task list is "never written"); C2.2 asks for the status of each task in
  shared state.
- **Files per task:** `CodingTask` has one `file_path`; our `TaskSpec` has
  `files` (several, possibly shared between tasks).
- **Errors:** the lab's node never raises (error dict, `routing="done"`); the
  project's PM follows the same rule (DEC-087). `run_agent` lets API and
  memory errors propagate (DEC-027), so the node must catch them.
- **Memory (C1.2):** the lab's loop has no memory; the project's Coder
  queries Chroma and the sliding window before every LLM call (DEC-077).
- **LLM client:** Helicone `get_llm_client`, `MODEL_CODER = "gpt-4.1-mini"`;
  the project uses `get_chat_model` via OpenRouter (DEC-002, DEC-068), with
  a small model for the Coder (C4.5).
- **Layout (C1.1):** the lab's `state.py`, `fixtures.py`, `main.py` sit in
  the repo root; in the project state and graph live in `orchestration/`.
- **Lab tests:** `Multi-agents-lab-2-2/tests/test_lab22.py` (37 mocked tests
  + 3 "not implemented yet" checks) inspires our ACs; it is not run against
  our code.
- **Fixture:** Flask `/health` + `/items` on port 8080; the graded demo is
  `/health` + `/echo` with input validation (Part A2).

---

## Original lab README


### What you are building

The Coder agent is the second node in the multi-agent software
development team. It receives coding tasks one at a time, implements
each using the ReACT loop and file tools from Week 1, and reports
results through shared state.

The new concept in this lab is the **self-looping LangGraph node**.
Instead of running once and exiting, the Coder node sets
`state["routing"] = "coder"` when more tasks remain, which causes the
graph router to send control back to the same node for the next task.
When all tasks are done it sets `routing = "done"` and the graph exits.

This matters because each loop iteration is a separate LangGraph step —
state is checkpointed after every task, and the QA agent added in Lab
2.3 slots in between iterations without requiring any changes here.

In this lab you work from a **pre-built task fixture** (in `fixtures.py`)
so you can test the Coder in isolation without a live PM agent. In Lab
2.3 the two agents are wired together.

---

### Repo structure

```
lab2.2/
├── .devcontainer/
│   └── devcontainer.json       # Codespaces config — do not modify
├── agents/
│   └── coder_agent.py          # ← YOUR WORK
├── orchestration/
│   └── graph.py                # Pre-provided graph wiring — do not modify
├── tools/
│   └── file_tools.py           # Carried forward from Week 1 — do not modify
├── tests/
│   └── test_lab22.py           # Test suite — do not modify
├── fixtures.py                 # Pre-built task list — do not modify
├── llm_client.py               # Shared Helicone client — do not modify
├── state.py                    # CoderState TypedDict — do not modify
├── main.py                     # Entry point — do not modify
└── requirements.txt
```

**You only edit `agents/coder_agent.py`.**

---

### Setup

Your Codespace is pre-configured. The `HELICONE_API_KEY` secret is
injected automatically.

Verify your environment:

```bash
python -c "from llm_client import get_llm_client; print('Client OK')"
python -c "from tools.file_tools import dispatch_tool; print('Tools OK')"
```

---

### Your tasks

Both functions are in `agents/coder_agent.py`. Read each docstring
fully before writing any code.

### Task 1 — `_run_react_loop(task)`

Implement the ReACT loop for a single `CodingTask`. The loop:

1. Builds an initial messages list (system prompt + user task)
2. Calls the LLM with `tools=TOOL_SCHEMAS, tool_choice="auto"`
3. If the response contains tool calls — dispatches each via
   `dispatch_tool()`, appends tool result messages, continues
4. If the response is plain text — tries to parse as JSON; if it
   contains `"done": true`, builds and returns a `CodeArtifact`
5. On loop exhaustion (8 iterations) or any exception — returns a
   failed `CodeArtifact`

The done signal the LLM must produce:
```json
{"done": true, "file_path": "...", "explanation": "...", "tests_suggested": [...]}
```

### Task 2 — `coder_node(state)`

The LangGraph node. For each call it:

1. Reads `state["tasks"][state["current_task_index"]]`
2. Logs start, calls `_run_react_loop`, logs completion
3. Returns `[artifact]` as a **list** (required by the `operator.add` reducer)
4. Increments `current_task_index`
5. Sets `routing="coder"` if more tasks remain, `"done"` if finished
6. Never raises — wraps everything in try/except

---

### Running the tests

```bash
python -m pytest tests/test_lab22.py -v
```

All 37 tests are mocked — no API calls are made. All should pass when
your implementation is correct.

---

### Running the full agent

```bash
python main.py
```

This runs the Coder against the two-task fixture in `fixtures.py` and
prints a progress log and artifact summary.

---

### Success criteria

- `pytest tests/test_lab22.py` passes all 37 tests
- `python main.py` loops twice (once per task), prints two artifact
  entries with `✓` status, and writes `src/app.py` to disk
- Introducing a deliberate failure (e.g. bad task index) causes the
  node to return an error dict — it never raises out of the graph

---

### Key concepts this lab teaches

**The self-loop pattern.** A conditional edge from `coder_node` back to
itself is how LangGraph expresses iteration over a variable-length task
list without a Python for-loop inside the node. Read `orchestration/graph.py`
to see how `route_after_coder` reads `state["routing"]` to decide whether
to loop or exit.

**The `operator.add` reducer on `artifacts`.** Every call to `coder_node`
must return `"artifacts": [artifact]` — a single-item list. LangGraph's
`operator.add` reducer appends this to the accumulated list. If you return
a bare dict, the reducer concatenates its characters and the test
`test_artifacts_operator_add_accumulates_across_iterations` will fail in
a confusing way.

**Tool result messages.** After dispatching a tool call, you must append
a message with `role="tool"`, `tool_call_id`, and `content=json.dumps(result)`
before the next LLM call. Without this, the API raises an error because
it sees a tool call without a corresponding result.

**Nodes must not raise.** Wrap `coder_node`'s entire body in try/except.
A raised exception crashes the graph and loses all accumulated state.
Errors belong in `state["error"]`, not in the call stack.

---

### Common errors

| Symptom | Likely cause |
|---------|-------------|
| Characters instead of dicts in `artifacts` | Returned `artifact` (bare dict) instead of `[artifact]` (list) — the reducer concatenates them |
| Loop never exits even with a done signal | Missing `if parsed.get("done"): return ...` after parsing |
| `BadRequestError` from OpenAI on second iteration | Tool result not appended — the API requires a `role="tool"` message after every tool call |
| Loop makes 9+ calls | No iteration counter — use `for _ in range(MAX_REACT_ITERATIONS)` |
| Second task never runs | `routing` always set to `"done"` — check `next_index < len(state["tasks"])` |

---

## Function specification (from the lab's `coder_agent.py` docstring)

### `_run_react_loop(task: CodingTask) -> CodeArtifact`

1. Messages: system prompt + user message `"Complete the following
   task:\n\n" + description + "\n\nAcceptance criteria:\n" + one per line`.
2. Up to `MAX_REACT_ITERATIONS = 8` times: call
   `client.chat.completions.create(model=MODEL_CODER, messages=...,
   tools=TOOL_SCHEMAS, tool_choice="auto")`; append the assistant message.
   - With tool calls: `json.loads` the arguments, `dispatch_tool(name,
     args)`, append `{"role": "tool", "tool_call_id", "content":
     json.dumps(result)}` for each; continue.
   - Plain text: strip fences, `json.loads`; if `"done": true` return a
     `CodeArtifact` (`file_path` and `code` from the JSON with the task's
     path / `""` as defaults, `status="complete"`); otherwise treat it as
     reasoning and continue.
3. Loop exhausted: failed artifact, explanation `"ReACT loop reached the
   iteration limit without completing."`.
4. Any exception: failed artifact, explanation `f"Unexpected error: {exc}"`.

System prompt: role ("expert Python developer ... autonomous software
development team"), the three tools, workflow (think → `write_file` →
verify with `exec_python` → reply ONLY with the done JSON), constraints
(complete runnable files, follow the acceptance criteria exactly, the done
JSON is the entire response).

### `coder_node(state: CoderState) -> dict`

1. `idx = state["current_task_index"]`, `task = state["tasks"][idx]`.
2. Log `f"Coder Agent: starting {task_id} — {title}."`.
3. `artifact = _run_react_loop(task)`.
4. Log `f"Coder Agent: {task_id} {artifact['status']}. File: {file_path}."`.
5. `next_index = idx + 1`; `routing = "coder"` if `next_index <
   len(tasks)` else `"done"`.
6. Return `{"artifacts": [artifact], "work_in_progress": [log1, log2],
   "current_task_index": next_index, "routing": ..., "error": ""}`.

On index out of range or any exception: `{"artifacts": [],
"work_in_progress": [f"Coder Agent: fatal error — {exc}"],
"current_task_index": state.get("current_task_index", 0), "routing":
"done", "error": str(exc)}`. A failed artifact is still appended.

---

## Provided state, graph and fixture

`state.py` (TypedDict):
- `CodingTask`: `task_id`, `title`, `description`, `acceptance_criteria:
  list[str]`, `status` (`"pending"` → `"complete" | "failed"`), `file_path`.
- `CodeArtifact`: `task_id`, `file_path`, `code`, `explanation`,
  `tests_suggested: list[str]`, `status` (`"complete" | "failed"`).
- `CoderState`: `user_requirement`, `tech_spec: str`, `tasks`,
  `work_in_progress: Annotated[list[str], operator.add]`, `routing`
  (`"coder"` | `"done"`), `error`, `artifacts: Annotated[list[CodeArtifact],
  operator.add]`, `current_task_index: int`.

`orchestration/graph.py`: `START → coder_node`, conditional edge
`route_after_coder` → `"coder_node"` if `routing == "coder"`, else `END`.
The self-loop makes each task a separate LangGraph step (checkpointed
state; QA slots in between iterations in Lab 2.3).

`fixtures.py`: `SAMPLE_TASKS` = `task_1` (create `src/app.py`, Flask `GET
/health` → `{"status": "ok", "version": "1.0"}`, port 8080) and `task_2`
(edit `src/app.py`, add `ITEMS` with 5 dicts and `GET /items`; `/health`
unchanged), plus `SAMPLE_TECH_SPEC`.

`main.py`: builds the initial state from the fixture, invokes the graph,
prints the progress log, the error if any, and a summary per artifact.

---

## Lab test suite (`test_lab22.py`, mocked LLM)


**TestRunReactLoop**
- `test_returns_code_artifact_on_done_signal`
- `test_artifact_has_all_required_fields`
- `test_artifact_status_complete_on_done_signal`
- `test_artifact_task_id_matches_task`
- `test_artifact_tests_suggested_is_list`
- `test_strips_markdown_fences_from_done_json`
- `test_tool_call_is_dispatched`
- `test_multiple_tool_calls_all_dispatched`
- `test_tool_result_appended_to_messages`
- `test_loop_exhaustion_returns_failed_artifact`
- `test_loop_exhaustion_does_not_exceed_max_iterations`
- `test_loop_exhaustion_artifact_has_correct_task_id`
- `test_api_exception_returns_failed_artifact`
- `test_api_exception_explanation_contains_error_message`
- `test_exception_artifact_has_all_fields`
- `test_non_done_plain_text_continues_loop`

**TestCoderNode**
- `test_returns_dict`
- `test_artifacts_is_single_item_list`
- `test_work_in_progress_is_two_item_list`
- `test_work_in_progress_entries_are_strings`
- `test_current_task_index_incremented`
- `test_index_incremented_from_nonzero_start`
- `test_routing_coder_when_more_tasks_remain`
- `test_routing_done_after_last_task`
- `test_routing_done_when_on_last_task_of_two`
- `test_executes_task_at_current_index`
- `test_error_empty_on_success`
- `test_failed_artifact_still_appended`
- `test_index_out_of_range_returns_error_dict`
- `test_fatal_error_work_in_progress_is_list`

**TestGraphEndToEnd**
- `test_single_task_produces_one_artifact`
- `test_single_task_no_error`
- `test_two_tasks_produce_two_artifacts`
- `test_two_tasks_work_in_progress_has_four_entries`
- `test_final_current_task_index_equals_task_count`
- `test_user_requirement_unchanged_in_final_state`
- `test_artifacts_operator_add_accumulates_across_iterations`
- `test_tasks_list_unchanged_in_final_state`

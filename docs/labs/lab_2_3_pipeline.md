# Lab 2.3 — Combined PM + Coder pipeline

**Course:** Build Autonomous Multi-Agent Systems
**Module:** 2 · Lab 2.3 — the Week 2 deliverable: PM and Coder in one graph.
Closes **C2.3** (PM→Coder transition inside the same graph), **C2.4**
(ordered execution with progress after each task) and **C2.5** (the graded
API task runs through PM and Coder and passes the request fixture);
instruction 9 of the Module 2 guide.
**Use when:** wiring the PM and the Coder in `orchestration/graph.py`,
changing `run()` or `main.py`, or when Lab 2.3 is mentioned.

Gaps between the lab and the project (the project wins; see
`docs/course_reference.txt` Part A2 and C2.1–C2.6):
- **Routing fields (C2.2):** the lab routes on a shared `routing` string
  written by both nodes, plus `current_task_index`; the project routes on
  `error` and the task statuses (DEC-103). No `routing` field is added.
- **Node names:** the lab uses `pm_node` / `coder_node`; the project's
  graph already uses `pm` and `coder` (`CODER_NODE`).
- **Module-level `graph = build_graph()`:** the lab imports a compiled
  graph at import time; the project builds it in `run()` and each run gets
  its own Coder memory window through the run context (DEC-104).
- **Progress log:** the lab's `work_in_progress` (3 PM entries + 2 per
  task) and `artifacts` list; the project has `progress` (same pattern,
  plus a consolidation note) and `code` read from disk (DEC-106).
- **Demo requirement:** the lab's default is `/health` + `/items` on port
  8080; the graded demo is `/health` + `/echo` with input validation
  (Part A2), already the default of `main.py`.
- **Lab tests:** `Multi-agents-lab-2-3/tests/test_lab23.py` (30 mocked
  tests) inspires our ACs; it is not run against our code.

---

## Original lab README

**Module 2 · Lab 2.3**
Build Autonomous Multi-Agent Systems · Saras AI Institute

---

### What you are building

In Labs 2.1 and 2.2 you built the PM agent and the Coder agent in
isolation. In this lab you wire them together into the complete
multi-agent pipeline that is the Week 2 project deliverable.

The agents themselves are fully implemented and pre-provided — your
work is entirely in **`orchestration/graph.py`**. You will write the
two routing functions and the graph assembly function that connect the
PM's output to the Coder's input and control the Coder's self-loop.

The final graph looks like this:

```
[START]
   │
   ▼
[pm_node]           ← runs once; produces tech_spec + tasks
   │
   ▼  route_after_pm
[coder_node] ◄──────────────────┐
   │                            │
   ▼  route_after_coder         │
routing == "coder" ─────────────┘   (more tasks — loop)
routing == "done"  ──────────────► [END]
```

---

### Repo structure

```
lab2.3/
├── .devcontainer/
│   └── devcontainer.json       # Codespaces config — do not modify
├── agents/
│   ├── pm_agent.py             # Carried forward from Lab 2.1 — do not modify
│   └── coder_agent.py          # Carried forward from Lab 2.2 — do not modify
├── orchestration/
│   └── graph.py                # ← YOUR WORK (all four tasks)
├── tools/
│   └── file_tools.py           # Carried forward from Week 1 — do not modify
├── tests/
│   └── test_lab23.py           # Test suite — do not modify
├── llm_client.py               # Shared Helicone client — do not modify
├── state.py                    # ProjectState TypedDict — do not modify
├── main.py                     # Entry point — do not modify
└── requirements.txt
```

**You only edit `orchestration/graph.py`.**

---

### Setup

Your Codespace is pre-configured. The `HELICONE_API_KEY` secret is
injected automatically.

Verify your environment:

```bash
python -c "from agents.pm_agent import pm_node; print('PM OK')"
python -c "from agents.coder_agent import coder_node; print('Coder OK')"
```

---

### Your tasks

All four tasks are in `orchestration/graph.py`. Read the full docstring
before writing any code — the specification is complete.

#### Task 1 — `route_after_pm(state)`

Returns `"coder_node"` when the PM succeeded, `END` otherwise.
Three conditions must all hold for success:
- `state["routing"] == "coder"`
- `state["error"] == ""`
- `state["tasks"]` is non-empty

#### Task 2 — `route_after_coder(state)`

Returns `"coder_node"` when more tasks remain, `END` when done.
Two conditions must hold for the loop to continue:
- `state["routing"] == "coder"`
- `state["error"] == ""`

#### Task 3 — `build_graph()`

Assembles the graph using the LangGraph `StateGraph` API:
1. `StateGraph(ProjectState)`
2. `add_node` for both agents
3. `add_edge(START, "pm_node")`
4. `add_conditional_edges` for both routing functions
5. `return builder.compile()`

#### Task 4 — Module-level `graph` instance

Add `graph = build_graph()` at module level after `build_graph`.
The test suite and `main.py` both import `graph` directly from this
module — if it is missing, every import will fail.

---

### Running the tests

```bash
python -m pytest tests/test_lab23.py -v
```

All 30 tests are mocked — no API calls are made. All should pass when
your implementation is correct.

---

### Running the full pipeline

```bash
python main.py
```

Or supply your own requirement:

```bash
python main.py "Build a CLI tool that counts word frequency in a file"
```

You will see the PM's progress log, the tech spec preview, the task list,
and the Coder's artifact summary — the complete work-in-progress
narrative from both agents in chronological order.

---

### Success criteria

- `pytest tests/test_lab23.py` passes all 30 tests with no failures
- `python main.py` prints a 7-line progress log (3 from PM + 2 per task
  for a 2-task decomposition), a task list, and 2 artifact entries
- Introducing a deliberate PM failure (e.g. invalid key in `.env`) causes
  the graph to reach END cleanly with a non-empty `error` field and
  without calling the Coder at all

---

### Key concepts this lab teaches

**Graph composition.** Two independently-built, independently-tested
nodes become a pipeline through routing functions. Neither agent needed
to know about the other — they just read from and write to the shared
`ProjectState`. This is the core architectural pattern you will carry
forward to Lab 3 when the QA agent is added.

**State-mediated handoff.** The PM doesn't call the Coder directly. It
writes `tasks`, `tech_spec`, and `routing="coder"` to state, then exits.
The routing function reads that signal and moves control. This indirection
is what makes the system extensible — inserting a new agent between PM
and Coder in Lab 3 requires only a new node and updated routing, not
changes to either existing agent.

**Defensive routing.** `route_after_pm` checks three conditions, not one.
A router that only checks `routing == "coder"` will pass an empty task
list to the Coder if the PM misconfigures its output. Defensive routing
makes failures visible at the boundary rather than deeper inside the loop.

**The `operator.add` reducer across two nodes.** `work_in_progress` and
`artifacts` both use `operator.add`. The PM appends 3 strings; the Coder
appends 2 strings per task. LangGraph merges them all correctly because
both nodes return lists. If either returned a plain string, the reducer
would concatenate characters instead.

---

### Common errors

| Symptom | Likely cause |
|---------|-------------|
| `IndexError` on `tasks[0]` immediately after PM | `route_after_pm` missing the empty-tasks guard |
| `ImportError: cannot import name 'graph'` | Missing `graph = build_graph()` at module level |
| PM failure doesn't prevent Coder from running | `route_after_pm` not checking `state["error"]` |
| Graph loops after a Coder fatal error | `route_after_coder` not checking `state["error"]` |
| `test_graph_has_pm_node` fails | Node registered with wrong name — must be exactly `"pm_node"` |

## Lab test suite (`test_lab23.py`, mocked LLM)


**TestRouteAfterPM**
- `test_raises_not_implemented_before_student_code`
- `test_returns_coder_node_on_success`
- `test_returns_end_when_routing_is_done`
- `test_returns_end_when_error_is_set`
- `test_returns_end_when_tasks_list_is_empty`
- `test_returns_end_when_routing_field_missing`

**TestRouteAfterCoder**
- `test_raises_not_implemented_before_student_code`
- `test_returns_coder_node_when_routing_is_coder`
- `test_returns_end_when_routing_is_done`
- `test_returns_end_when_routing_is_empty`
- `test_returns_end_when_error_is_set`
- `test_single_task_routes_to_end_after_completion`

**TestBuildGraph**
- `test_raises_not_implemented_before_student_code`
- `test_returns_a_compiled_graph`
- `test_graph_module_exposes_graph_instance`
- `test_graph_has_pm_node`
- `test_graph_has_coder_node`

**TestEndToEnd**
- `test_pm_failure_short_circuits_to_end`
- `test_pm_failure_final_state_has_empty_tasks`
- `test_single_task_produces_one_artifact`
- `test_single_task_no_error`
- `test_two_tasks_produce_two_artifacts`
- `test_coder_called_twice_for_two_tasks`
- `test_work_in_progress_has_pm_entries`
- `test_work_in_progress_has_coder_entries`
- `test_two_task_work_in_progress_has_seven_entries`
- `test_user_requirement_never_modified`
- `test_tasks_list_not_modified_by_coder`
- `test_final_current_task_index_equals_task_count`
- `test_artifacts_are_dicts_not_characters`

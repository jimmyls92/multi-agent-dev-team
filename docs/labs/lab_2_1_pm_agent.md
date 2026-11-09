# Lab 2.1 — PM Agent

**Course:** Build Autonomous Multi-Agent Systems
**Module:** 2 · Lab 2.1 — covers rubric criterion **C2.1** (and prepares
C2.2, C2.3, C2.4)
**Use when:** working on the PM Agent (`agents/pm_agent.py`), the shared
state it writes, its graph wiring in `orchestration/`, or when Lab 2.1 is
mentioned.

Gaps between the lab and the project (the project wins; see
`docs/course_reference.txt` Part A2 and C2.1–C2.6):
- **Spec format (C2.1):** the lab's spec is free markdown; the project needs
  a structured spec with `name`, `description`, acceptance criteria and
  tasks.
- **Validation (C1.3, C4.6):** the lab parses JSON with `json.loads()` and
  no validation; every LLM output must go through a Pydantic schema first.
- **Handoff fields (C2.3):** `CodingTask` has no `priority`.
- **Task bound (C2.4):** the lab asks for 2–4 tasks and has no
  consolidation; the project allows up to 8 and must consolidate any excess
  without losing requirement coverage.
- **Shared state (C2.2):** `PMState` has no per-task status tracking beyond
  `"pending"` and no accumulated code output.
- **LLM client:** the lab uses a Helicone client (`get_llm_client`,
  `MODEL_PM = "gpt-4.1-mini"`); the project uses `get_chat_model` via
  OpenRouter (DEC-002, DEC-068), with the large model for the PM (C4.5).
- **Layout (C1.1):** the lab's `graph.py`/`state.py`/`main.py` sit in the
  repo root; in the project the graph goes in `orchestration/`.
- **Lab tests:** `lab-2-1/test_lab21.py` (45 behavioral tests + 4
  "not implemented yet" checks) inspires our ACs; it is not run against our
  code.
- **Demo task:** the lab's default requirement (Flask `/health` + `/items`)
  differs from the graded one (`/health` + `/echo` with input validation,
  Part A2).

---

## Original lab README

### What you are building

The Product Manager (PM) agent is the first node in the multi-agent
software development team you will complete over the next three labs.

The PM agent is a **pure reasoning node**. It never writes files or
executes code. It runs exactly once per pipeline invocation and produces
two things that every downstream agent depends on:

1. A **technical specification** — a structured markdown document derived
   from the raw user requirement.
2. A **task list** — the spec decomposed into 2–4 concrete `CodingTask`
   dicts, each targeting a specific file, with explicit acceptance criteria.

By the end of this lab the PM agent runs as a single-node LangGraph
graph. In Lab 2.2 you build the Coder agent in isolation, and in Lab 2.3
you wire them together into the full pipeline.

### Repo structure

```
lab2.1/
├── pm_agent.py                 # ← YOUR WORK
├── graph.py                    # Pre-provided graph wiring — do not modify
├── test_lab21.py               # Test suite — do not modify
├── llm_client.py               # Shared Helicone client — do not modify
├── state.py                    # PMState TypedDict — do not modify
├── main.py                     # Entry point — do not modify
└── requirements.txt
```

### Your tasks

**Task 1 — `_build_tech_spec(requirement)`.** Call the LLM once with a
system prompt that instructs it to produce a structured technical
specification. Ask for five sections: Overview, Functional Requirements,
Non-Functional Requirements, File Structure, and Constraints & Assumptions.
Return the response text as-is.

**Task 2 — `_decompose_into_tasks(tech_spec)`.** Call the LLM once with a
system prompt that instructs it to decompose the spec into a JSON task
list. Parse the response with `json.loads()` — strip markdown fences
first. Extract the list from `parsed["tasks"]` and return it.

**Task 3 — `pm_node(state)`.** Orchestrate Tasks 1 and 2. Write three
progress notes to `work_in_progress`. Return the partial state update
dict. Catch all exceptions and return them in `state["error"]` — never let
the node raise out of the graph.

### Success criteria

- `pytest test_lab21.py` passes all tests with no failures
- `python main.py` prints a tech spec preview and a task list with 2–4
  entries, each showing a `task_id`, `title`, and `file_path`
- Introducing a deliberate API failure (e.g. invalid key) causes the
  graph to reach END cleanly with a non-empty `error` field rather than
  crashing

### Key concepts this lab teaches

**TypedDict state and partial updates.** Every LangGraph node receives
the full state and returns only the keys it wants to update. LangGraph
merges them.

**The `operator.add` reducer.** `work_in_progress` uses
`Annotated[list[str], operator.add]`. Returning a list from a node
*appends* to the existing list rather than overwriting it. Returning a
string instead of a list makes the reducer concatenate characters.

**Two LLM calls, not one.** Going from a raw requirement directly to a
task list in a single prompt produces poor decompositions. The spec-first
step forces the model to reason about scope before breaking it down.

**Nodes must not raise.** A node that raises an unhandled exception
crashes the graph. Catch exceptions, write the error to state, and set
`routing="done"` so the graph reaches END gracefully. Downstream agents
check `state["error"]` before proceeding.

### Common errors

| Symptom | Likely cause |
|---------|-------------|
| `JSONDecodeError` in `_decompose_into_tasks` | Markdown fences not stripped |
| `KeyError: 'tasks'` | Returning `json.loads()` result directly instead of `parsed["tasks"]` |
| `work_in_progress` test fails despite correct log messages | Returned a `str` instead of `list[str]` |
| Error path test fails | Exception swallowed inside a helper — helpers must re-raise |

---

## Function specification (from the lab's `pm_agent.py` docstring)

### `_build_tech_spec(requirement: str) -> str`

1. Call the LLM (`MODEL_PM`) with a system prompt asking for these sections:
   `## Overview`, `## Functional Requirements`,
   `## Non-Functional Requirements`, `## File Structure`,
   `## Constraints & Assumptions`.
2. Return the response text as a plain string, without post-processing.
3. On any exception, re-raise so `pm_node` can catch it.

Prompting note: the spec is consumed by a Coder agent that acts on it
without asking follow-up questions. The LLM must be concrete and
unambiguous — no "TBD" sections, no open questions.

### `_decompose_into_tasks(tech_spec: str) -> list[CodingTask]`

1. Call the LLM (`MODEL_PM`) asking for ONLY valid JSON.
2. Strip markdown fences, then `json.loads()`.
3. Return `parsed["tasks"]` (no per-field validation in the lab).
4. On `json.JSONDecodeError` or any other exception, re-raise.

JSON schema the LLM must return:

```json
{
  "tasks": [
    {
      "task_id":             "task_1",
      "title":               "<short imperative title>",
      "description":         "<full self-contained spec — Coder sees ONLY this>",
      "acceptance_criteria": ["<check 1>", "<check 2>"],
      "status":              "pending",
      "file_path":           "<e.g. src/app.py>"
    }
  ]
}
```

Prompting rules:
- Between 2 and 4 tasks only.
- Order tasks so later tasks can safely import from earlier ones
  (foundation files first).
- Each description fully self-contained: the Coder reads only one task at a
  time and cannot ask questions.
- Every task has a unique `file_path`.
- `status` is exactly `"pending"` for every task.
- Return ONLY the JSON object.

### `pm_node(state: PMState) -> dict`

1. Log `"PM Agent: analysing requirement."`
2. `_build_tech_spec(state["user_requirement"])`
3. Log `"PM Agent: spec complete — decomposing into tasks."`
4. `_decompose_into_tasks(tech_spec)`
5. Log `f"PM Agent: {len(tasks)} tasks created — handoff ready."`

Success return: `tech_spec`, `tasks`, `work_in_progress` (the three notes as
a list), `routing="done"`, `error=""`.

Error return (any exception from either helper): `tech_spec=""`,
`tasks=[]`, `work_in_progress=[f"PM Agent: failed — {exc}"]`,
`routing="done"`, `error=str(exc)`.

---

## Provided state and graph

`state.py`:

```python
class CodingTask(TypedDict):
    task_id: str                       # "task_1", "task_2", …
    title: str
    description: str                   # Full self-contained spec for the Coder
    acceptance_criteria: list[str]
    status: str                        # "pending" (set by PM; Coder will update)
    file_path: str                     # Target file, e.g. "src/app.py"

class PMState(TypedDict):
    user_requirement: str              # written once at entry, never modified
    tech_spec: str
    tasks: list[CodingTask]            # replaced wholesale (no reducer)
    work_in_progress: Annotated[list[str], operator.add]
    routing: str                       # "done" only in Lab 2.1
    error: str                         # "" on success
```

`graph.py`: single-node `StateGraph(PMState)`: `START → pm_node → END`, no
conditional routing; failure is signalled through `error` and `routing`.

`main.py` default requirement: a Flask API with `GET /health` returning
`{"status": "ok", "version": "1.0"}` and `GET /items` returning five
hardcoded items (`id`, `name`), on port 8080.

---

## Lab test suite (`test_lab21.py`, mocked LLM)

- **`_build_tech_spec`:** returns a non-empty string; exactly one LLM call;
  the requirement reaches the LLM; returns the LLM text; API exceptions
  propagate.
- **`_decompose_into_tasks`:** returns a list of 2–4 tasks; each has all
  fields; `status == "pending"`; unique `task_id` and `file_path`;
  `acceptance_criteria` is a list; strips markdown fences; exactly one LLM
  call; JSON and API failures propagate.
- **`pm_node`:** returns a dict with a non-empty string spec and the task
  list; `routing == "done"`; `error == ""`, also clearing a stale error;
  `work_in_progress` is a list of three strings, the third mentioning the
  task count; exactly two LLM calls; on spec or JSON failure: `error` set,
  `routing == "done"`, empty tasks, `work_in_progress` still a list.
- **Graph end-to-end:** final state has spec and tasks and no error;
  `work_in_progress` accumulates; errors reach the final state;
  `user_requirement` unchanged.

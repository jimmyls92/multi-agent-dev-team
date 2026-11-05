# Lab 1.3 — ReACT Agent

**Course:** Build Autonomous Multi-Agent Systems
**Module:** 1 · Section 4 · Lab 1.3 — covers rubric criterion **C1.4**
(and builds on C1.2 memory and C1.3 tools)
**Use when:** working on the Coder Agent's ReACT loop (`agents/coder_agent.py`,
its prompt, response parsing and tests) or when Lab 1.3 is mentioned.

Adaptations in this project (see `docs/decisions.md`):
- Files live in the project scaffold (C1.1, DEC-001) and run as modules from
  the repo root (`python -m ...`), not as `python agent.py`.
- LLM access goes through OpenRouter (OpenAI-compatible) instead of Helicone;
  the client comes from `get_client()` in `llm_client.py` (DEC-002, DEC-034)
  and the key from `OPENROUTER_API_KEY` in `.env`.
- The lab's "pre-provided" modules already exist in the project:
  `memory.py` and `llm_client.py` at the root (DEC-034, DEC-035), and the
  lab's `tools.py` corresponds to the `tools/` package (`TOOL_HANDLERS` in
  `tools/handlers.py`, schemas in `tools/schemas.py`), with paths confined to
  `workspace/` (DEC-036, DEC-042).
- C1.4 requires a hard limit of **10 iterations** in the Coder's ReACT loop.
- To decide when the lab starts (Provisional decisions whose `Revisit when`
  points here): DEC-004 (window by turns once the loop adds tool/observation
  messages) and DEC-034 (the lab's `agent.py` vs `agents/tools_demo.py`).
  The framework (LangGraph / AutoGen / CrewAI) is also still pending.

---

Original lab README:

## What you will build

A working ReACT (Reasoning + Acting) agent that solves multi-step coding
tasks end-to-end.  The agent ties together the memory system from Lab 1.1
and the tools from Lab 1.2 into a continuous loop:

```
Sense → Think → Act → Remember → repeat
```

At the end of this lab you will have a Coder Agent that can accept a
natural-language coding task, plan and execute it across multiple tool
calls, and return structured output — the first building block of the
Week 1 capstone deliverable.

---

## Repo layout

```
lab-1.3-react-agent/
├── agent.py          ← YOUR WORK.  Three functions to implement.
├── llm_client.py     ← Pre-provided. Do not modify.
├── memory.py         ← Pre-provided. Do not modify.
├── tools.py          ← Pre-provided. Do not modify.
├── requirements.txt
├── tests/
│   └── test_agent.py ← Run with: pytest tests/
└── workspace/        ← Created at runtime. The agent's sandbox.
```

---

## Your task

Open `agent.py`.  You will implement exactly **three functions**:

### 1. `build_system_prompt(semantic_memory, task) → str`

Retrieves relevant memories from the vector store and appends them to
the base system prompt so the agent can recall facts from previous runs.

### 2. `parse_llm_response(response_text) → dict`

Parses the LLM's raw text output into a structured dict.  The LLM
responds in one of two formats:

**Format A — tool call:**
```
Thought: I need to write the function first.
Action: write_file
Action Input: {"path": "utils.py", "content": "def foo(): ..."}
```

**Format B — final answer:**
```
Thought: The task is complete.
FINAL ANSWER: workspace/utils.py contains the completed function.
```

### 3. `run_agent(task) → AgentResult`

The main loop.  Calls the LLM, parses its response, dispatches tool
calls, records observations, and repeats until the agent signals it is
done or the iteration limit is reached.

Read the docstrings in `agent.py` carefully — they contain step-by-step
hints for each function.

---

## Running the agent

```bash
python agent.py
```

The default `DEMO_TASK` at the bottom of `agent.py` asks the agent to
write and test a `word_frequency` function.  Replace it with any coding
task you like.

---

## Running the tests

```bash
# Fast (no LLM calls — mocked):
pytest tests/

# End-to-end (real LLM calls — slow and costs tokens):
pytest tests/ --run-llm
```

All 18 mocked tests should pass before you run the full end-to-end test.

---

## Success criteria

Your implementation passes when:

1. `pytest tests/` reports **all mocked tests passing** with no errors.
2. `python agent.py` produces a `FINAL ANSWER` for the default task
   within 10 iterations.
3. `workspace/word_frequency.py` exists after the run and contains a
   `def word_frequency` function definition.

---

## The ReACT format in detail

The agent communicates with the LLM using plain text, not native
function-calling.  Each LLM response must contain:

| Field          | Format A (tool call)    | Format B (final answer) |
|----------------|-------------------------|-------------------------|
| `Thought:`     | Required                | Required                |
| `Action:`      | Tool name               | —                       |
| `Action Input:`| JSON object             | —                       |
| `FINAL ANSWER:`| —                       | The deliverable         |

After each tool call, the agent appends the tool's result as:

```
OBSERVATION: <tool result>
```

This observation becomes part of the next LLM input, closing the loop.

---

## Common mistakes to avoid

| Mistake | Fix |
|---|---|
| `Action Input` is not valid JSON | `parse_llm_response` should return a `parse_error` key, not raise |
| Loop never terminates | Always check for `FINAL ANSWER` first; enforce `MAX_ITERATIONS` |
| Same action repeated | The loop guard catches this, but also check: is the observation being added to the buffer? |
| Memory block added even when empty | Check `semantic_memory.count() == 0` before calling `.retrieve()` |

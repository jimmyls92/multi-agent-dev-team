# Lab 1.2 — Custom Tools: File I/O and Sandboxed Code Execution

**Course:** Build Autonomous Multi-Agent Systems
**Module:** 1 · Section 3 · Lab 1.2 — covers rubric criterion **C1.3**
**Use when:** working on the file and execution tools (`tools/file_io.py`,
`tools/code_executor.py`, their tool schemas and tests) or when Lab 1.2 is
mentioned.

Adaptations in this project (see `docs/decisions.md`):
- Files live in the project scaffold (C1.1, DEC-001): tools in `tools/`, tests
  in `tests/`, the agent in `agents/coder_agent.py`, run as modules from the
  repo root (`python -m ...`).
- LLM access goes through OpenRouter (OpenAI-compatible) instead of Helicone;
  the key comes from `OPENROUTER_API_KEY` in `.env` (DEC-002).
- C1.3 requires the execution timeout to be configurable with a **10-second
  default**, and no direct `eval()`/`exec()`.
- The lab scaffold files (`schemas.py`, `agent.py`, `llm_client.py` and the
  tests `test_file_io.py`, `test_code_executor.py`) are not in the repo yet;
  where each one goes is decided when they are added.

---

Original lab README:

## Objective

Implement two reusable tools that the Coder Agent will use throughout the entire course:
a file I/O tool and a sandboxed code executor.

These tools are foundational. Every lab from 1.3 onwards depends on them working correctly.

## What you implement

You write code in exactly two files:

| File | Functions to implement |
|---|---|
| `tools/file_io.py` | `read_file(path)` and `write_file(path, content)` |
| `tools/code_executor.py` | `exec_python(path, timeout)` |

**Do not modify** `schemas.py`, `agent.py`, or `llm_client.py`.

## API access

All LLM calls are routed through Helicone. You do not need an OpenAI key.
In GitHub Codespaces the `HELICONE_API_KEY` is injected automatically.

If running locally outside Codespaces:
```bash
cp .env.example .env
# Ask your instructor for the key value, then add it to .env
```

## Step-by-step

### 1. Read the schemas first

Open `schemas.py` and read the three tool definitions.

The parameter names in the JSON schemas (`path`, `content`, `timeout`) are the exact
names the LLM will send in its tool calls. Your handler function signatures must
match them — a mismatch causes a silent failure that is difficult to debug.

### 2. Implement `tools/file_io.py`

Read the docstrings for `read_file` and `write_file` carefully.
The hints section in each docstring tells you which standard-library functions to use
and which edge cases to handle.

Both functions must:
- Accept the parameter names from `schemas.py` exactly
- Never raise — always return a descriptive string on failure
- Work as pure Python functions (no LLM involved)

### 3. Implement `tools/code_executor.py`

Read the docstring for `exec_python`.

The executor must use `subprocess.run` (not `exec()` or `eval()`) so that:
- Infinite loops are killed by the timeout
- Crashes in student scripts cannot crash the agent

### 4. Run the unit tests

```bash
pytest tests/test_file_io.py -v
pytest tests/test_code_executor.py -v
```

All tests must pass before you move on. If a test fails, read the failure message —
it tells you exactly which contract your implementation is breaking.

### 5. Run the integration demo

```bash
python agent.py
```

Watch the agent write a Python script, execute it, and report the result in one loop.
The tool call log is printed for every iteration — if something goes wrong,
the error string your tool returns is what the agent uses to self-correct.

## Success criterion

> The agent writes a Python file, executes it, reads or reports the output,
> and terminates with a DONE summary — all in one agentic loop with no
> unhandled exceptions.

## Common errors

| Symptom | Likely cause | Fix |
|---|---|---|
| Agent loops forever | Tool returns `""` on failure | Always return a non-empty error string |
| `KeyError` in dispatch | Parameter name mismatch | Check `schemas.py` — match exactly |
| `TimeoutExpired` propagates | Exception not caught | Catch `subprocess.TimeoutExpired` explicitly |
| Nested path write fails | Parent dirs not created | Use `os.makedirs(..., exist_ok=True)` |
| Agent calls wrong tool | Schema description unclear | Read schema descriptions in `schemas.py` |

## Academic integrity

Implement the functions yourself. The course notes, official Python docs,
and discussions with peers are all fair game.

The tests define the contract — reading and understanding them is part of the exercise.

## What's next

Once `agent.py` runs successfully, your tools are ready for **Lab 1.3**, where you
assemble them into a full ReACT loop. The same `tools/` package is imported unchanged.

# Lab 3.2 — QA Agent with Code Review and Structured Issue Output

**Module 3 · Section 4 · Lab 2**
Build Autonomous Multi-Agent Systems · Saras AI Institute

---

## Objective

Build the QA agent as a standalone component. It connects to the Lab 3.1
MCP server as a client, reads a Python file via `read_file`, sends it to
an LLM for structured review, and returns a typed `IssueList`.

This lab focuses on the QA agent's review logic and output schema. The
A2A peer messaging between Coder and QA comes in Lab 3.3.

---

## What You Will Build

```
qa_agent.py     ← QA agent (you implement this)
```

### Data models

| Model | Fields |
|-------|--------|
| `Issue` | `severity: Literal["High","Medium","Low"]`, `location: str`, `description: str` |
| `IssueList` | `issues: list[Issue]`, `approved: bool` |

`approved` must be `False` whenever any `High`-severity issue exists —
enforce this with a Pydantic `model_validator`, regardless of what the LLM returns.

### Functions to implement

| Function | What it does |
|----------|-------------|
| `_read_file_via_mcp(server_script_path, filename)` | Connects to Lab 3.1 MCP server, calls `read_file`, returns file contents |
| `_review_code(code)` | Sends code to LLM with structured review prompt, returns `IssueList` |
| `run_qa_agent(server_script_path, filename)` | Orchestrates the two steps above |

---

## The File Under Review

`project_files/word_counter.py` is pre-populated with deliberate bugs.
Your QA agent's job is to find them. The test suite will verify that
the agent correctly identifies the planted issues.

---

## Setup

```bash
pip install -r requirements.txt
```

Make sure Lab 3.1's `mcp_server.py` is at `../lab3.1/mcp_server.py`
(the default `LAB31_SERVER` path in `qa_agent.py`).

---

## Files

```
lab3.2/
├── qa_agent.py         ← Implement this
├── main.py             ← Entry point (do not modify)
├── requirements.txt
├── pytest.ini
└── project_files/
    └── word_counter.py ← Buggy file for the QA agent to review
```

---

## Implementation Guide

### 1 — Define Issue and IssueList

```python
from pydantic import BaseModel, model_validator
from typing import Literal

class Issue(BaseModel):
    severity:    Literal["High", "Medium", "Low"]
    location:    str
    description: str

class IssueList(BaseModel):
    issues:   list[Issue]
    approved: bool

    @model_validator(mode="after")
    def enforce_approved(self) -> "IssueList":
        if any(i.severity == "High" for i in self.issues):
            self.approved = False
        return self
```

### 2 — Read the file via MCP

Reuse the client pattern from Lab 3.1:

```python
params = StdioServerParameters(command=sys.executable, args=[server_script_path])
async with stdio_client(params) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool("read_file", {"path": filename})
        return result.content[0].text
```

### 3 — Review with structured output

```python
response = await _get_client().beta.chat.completions.parse(
    model=MODEL,
    messages=[{"role": "user", "content": REVIEW_PROMPT.format(code=code)}],
    response_format=IssueList,
)
return response.choices[0].message.parsed
```

Your `REVIEW_PROMPT` must instruct the LLM to:
- Identify every bug, style issue, and missing edge case
- Assign `High` / `Medium` / `Low` severity
- Specify the location (function name + brief description)
- Set `approved=True` only if there are zero `High`-severity issues

### 4 — Run it

```bash
python main.py
```

---

## Tests

```bash
# Mocked suite (no LLM calls, no MCP subprocess)
pytest

# Live test — spawns real MCP server, makes real LLM call
pytest --run-llm
```

---

## Success Criteria

- [ ] `pytest` exits with 0 failures (mocked suite).
- [ ] `IssueList.approved` is `False` when any `High` issue exists,
      even if the LLM returns `approved=True`.
- [ ] `_read_file_via_mcp` calls `session.call_tool("read_file", ...)`,
      not direct file I/O.
- [ ] `run_qa_agent` calls `_read_file_via_mcp` before `_review_code`.
- [ ] `python main.py` completes and prints a non-empty issue list.

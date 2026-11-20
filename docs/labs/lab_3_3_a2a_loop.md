# Lab 3.3 — A2A Protocol: Coder ↔ QA Iterative Review Loop

**Module 3 · Section 4 · Lab 3**
Build Autonomous Multi-Agent Systems · Saras AI Institute

---

## Objective

Wire the Coder and QA agents together using A2A protocol message exchange.
The Coder generates a fix for `word_counter.py`, sends it for review, and
iterates based on QA's feedback until approved or MAX_ITERATIONS is reached.

---

## What You Will Build

```
a2a.py          ← Message schema and Broker (you implement)
coder_agent.py  ← Coder agent A2A loop (you implement)
```

### Pre-built (do not modify)

```
qa_agent.py     ← QA agent from Lab 3.2 + A2A wrapper
mcp_server.py   ← MCP server from Lab 3.1
```

---

## A2A Message Flow

```
Coder                          QA
  |                             |
  |-- review_request ---------->|  payload: { "filename": "word_counter.py" }
  |                             |  (QA reads file via MCP, reviews with LLM)
  |<-- fix_instruction ---------|  payload: { "issues": [...], "approved": False }
  |                             |
  |  (Coder applies fixes)      |
  |                             |
  |-- review_request ---------->|
  |                             |
  |<-- approved ----------------|  payload: { "approved": True }
  |                             |
  STOP
```

Each `review_request` carries a `correlation_id`. QA echoes it back so the
Coder can match each response to the request that triggered it.

---

## Message Schema

| Field | Type | Description |
|-------|------|-------------|
| `sender` | `str` | `"coder"` or `"qa"` |
| `receiver` | `str` | `"coder"` or `"qa"` |
| `intent` | `str` | `"review_request"` \| `"fix_instruction"` \| `"approved"` |
| `payload` | `dict` | Intent-specific data |
| `correlation_id` | `str` | UUID4 auto-generated if not supplied |

`__post_init__` must validate all fields and raise `ValueError` for:
- Unknown sender or receiver
- Unknown intent
- `sender == receiver`

---

## What to Implement

### `a2a.py`

**`Message`** — dataclass with the five fields above and `__post_init__` validation.

**`Broker`** — one `asyncio.Queue` per agent:
```python
async def send(self, message: Message) -> None: ...
async def receive(self, agent_name: str) -> Message: ...
```

### `coder_agent.py`

**`write_file(filename, code)`** — writes to `PROJECT_DIR / filename`.

**`_generate_initial_code(original_code)`** — LLM call to fix all bugs,
returns code string.

**`_apply_fixes(code, issues)`** — LLM call to address specific issues,
returns updated code string.

**`run_coder_agent(broker, server_script_path)`** — the A2A loop:
```
for iteration in range(MAX_ITERATIONS):
    code = generate or fix
    write_file(FILENAME, code)
    send review_request → store correlation_id
    response = await broker.receive("coder")
    if approved: return code
    if fix_instruction: extract issues, loop
return code  # after MAX_ITERATIONS
```

---

## Setup

```bash
pip install -r requirements.txt
```

---

## Running

```bash
python main.py
```

Both agents run as concurrent asyncio tasks. You should see iteration
progress from both `[Coder]` and `[QA]`.

---

## Tests

```bash
# Mocked suite (no LLM calls, no MCP subprocess)
pytest

# Full live loop
pytest --run-llm
```

---

## Success Criteria

- [ ] `pytest` exits with 0 failures (mocked suite).
- [ ] `Message` raises `ValueError` for invalid sender, receiver, intent,
      or `sender == receiver`.
- [ ] `Broker` delivers messages to the correct agent queue in FIFO order.
- [ ] Coder calls `write_file` before sending each `review_request`.
- [ ] Coder stops immediately after receiving `"approved"`.
- [ ] Coder never sends more than `MAX_ITERATIONS` review requests.
- [ ] `python main.py` runs to completion without errors.

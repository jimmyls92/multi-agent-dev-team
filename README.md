# Multi-Agent Dev Team

Final project of the **Build Autonomous Multi-Agent Systems** course (Saras AI
Institute): an autonomous software team of LLM agents that takes a natural
language requirement and produces tested, working Python code, with no human
intervention after the first prompt.

The project is built one module at a time. **Current state: Module 1 — Coder
Agent v1.0** (two-tier memory, validated tools, ReACT loop, structured
output). The PM and QA agents (`agents/pm_agent.py`, `agents/qa_agent.py`),
the orchestration graph, Docker and observability arrive in Modules 2-4.

## Framework

**[LangGraph](https://langchain-ai.github.io/langgraph/)**, for every agent and
for the orchestration (DEC-068). The Coder's ReACT loop is LangChain's
`create_agent`, which builds a LangGraph graph, with native tool calling and
our own middleware (DEC-069).

Why LangGraph:
- **Explicit control flow.** Nodes and conditional edges decide what runs
  next, so the limits the assessor forces (10 ReACT iterations, the QA→Coder
  loop limit, task order) are conditions in the graph, not left to the LLM.
- **Typed shared state** is native, as the PM → Coder → QA handoff needs
  (Modules 2-3).
- **The standard agent loop with hooks.** `create_agent` brings the loop, a
  model-call limit and a validated final answer; middleware adds what a
  Coder needs on top: memory injected on every call, tool arguments
  validated before any tool runs, and no task ending without the `Finish`
  tool.
- **Tracing and tests.** LangSmith traces the graph (Module 4), and fake chat
  models make the mocked agent tests simple.
- Trade-off: more code than CrewAI to define roles, and no free-form agent
  conversation (AutoGen's strength); our flow PM → Coder → QA is a fixed
  sequence with bounded loops, so neither is needed.

**LLM:** any model with tool calling through [OpenRouter](https://openrouter.ai),
used with LangChain's `ChatOpenAI` because OpenRouter speaks the OpenAI API
for every model (DEC-075); an equivalent of the GPT-4o / Claude Sonnet options
in the course guide. The default is `openai/gpt-4.1-mini`, set with
`LLM_MODEL`.

## Setup

Python **3.11**, with [uv](https://docs.astral.sh/uv/) (DEC-032):

```bash
uv venv --python 3.11 .venv
UV_LINK_MODE=copy uv pip install -r requirements.txt   # UV_LINK_MODE only needed on /mnt/c (WSL)
source .venv/bin/activate
cp .env.example .env    # then set OPENROUTER_API_KEY
```

Credentials only come from environment variables (`.env`, never committed).
Every setting in `.env.example` is documented there: model, log level, window
size, memories per call, Chroma location, script timeout (10 s by default,
30 s maximum) and the agent's workspace directory.

## Running the Coder Agent

```bash
# Interactive session: each message is a task that runs the ReACT loop
python -m agents.coder_agent

# One task: prints the whole CoderResult as JSON
python -m agents.coder_agent "Write is_palindrome(s) in palindrome.py and test it"
```

The agent works inside `workspace/` (git-ignored): every path it uses is
confined there, and scripts run in a child process with a timeout and without
the agent's credentials. `LOG_LEVEL=INFO` logs the plan, one line per
iteration (tool called, or a text answer sent back) and one per LLM call
(window size and memories retrieved); `LOG_LEVEL=DEBUG` adds the full LLM
input.

### How it works

- **Plan** (`agents/coder_agent.py`): before the loop, one LLM call returns
  a Pydantic-validated `Plan`; it goes into the loop's prompt and into the
  output. It does not count as an iteration (DEC-070, DEC-071).
- **ReACT loop**: a `create_agent` graph with native tool calling, at most
  **10 model calls** per task (DEC-069, DEC-079). Each response calls exactly
  one tool (DEC-074), and every tool has a required `thought` argument, the
  Thought of that step (DEC-072). The task ends only through the `Finish`
  tool (`main_file` or null, `explanation`), validated with Pydantic; a
  response with text and no tool call goes back to the model as an error
  and counts as an iteration (DEC-073).
- **Tools** (`tools/`): `read_file`, `write_file`, `exec_python`. The model
  sees the lab schemas plus `thought` (`tools/agent_tools.py`); a middleware
  validates every call with strict Pydantic models before it runs, and
  `dispatch_tool` validates again and never raises, so invalid arguments
  never reach a tool (DEC-042, DEC-062, DEC-076).
- **Memory** (`memory.py`): a sliding window of the last N tasks of the
  session (each task with all its iterations is one turn), and a Chroma
  semantic store queried **before every LLM call** (the plan call and each
  call of the loop), whose results are injected into the system prompt. It
  stores each task and the outcome of each finished task (DEC-049, DEC-057,
  DEC-058, DEC-077).

### Output and statuses

Every task returns a `CoderResult` (Pydantic) with `status`, `plan` (from
the planning step), `code` (read from the main file on disk), `explanation`,
`result` (output of the last real execution), `main_file`, `iterations` and
`steps` (thought, action, input and observation of each step). It is computed
from the agent's messages after the run (DEC-078).

The status describes the evidence the task produced, not the kind of
request:

| Status | Meaning |
|---|---|
| `success` | `Finish` with a main file this task wrote or ran; the file exists and its last run (with no file written after it) ended without error. |
| `failed_execution` | `Finish` with a main file, but the last valid run failed. |
| `unverified` | `Finish` with a main file but no valid run: never ran, files changed after the run, or the declared file does not exist. |
| `answered` | `Finish` without code from this task (for example a question, even one about a file from an earlier task); nothing was executed (DEC-056, DEC-080). |
| `max_iterations` | 10 model calls without `Finish`. |

Only `success` means the code was checked by a real execution.

## Tests

```bash
pytest tests/                                      # tools tests, no LLM calls
pytest tests/test_smoke.py --run-llm               # smoke test with the real LLM (costs tokens)
CHROMA_PATH=.chroma-test python -m tests.test_memory   # Lab 1.1 recall test, real LLM
```

The smoke test gives the Coder a short coding task in a temporary workspace
and Chroma store, checks the `CoderResult` fields, that `code` matches the
written file and that the code was run, and then runs the generated code in a
subprocess to check its behavior. Without `--run-llm` it is skipped; with
`--run-llm` and no API key it fails.

## Repository layout

```
agents/          coder_agent.py (Module 1); pm_agent.py, qa_agent.py (Modules 2-3)
tools/           file_io.py, code_executor.py, handlers.py (validation, dispatch), schemas.py,
                 agent_tools.py (LangChain adapter)
orchestration/   orchestration graph (Module 2)
tests/           pytest tests and the smoke test
docs/            decisions.md, improvements.md, labs/, course_reference.txt
memory.py        two-tier memory
llm_client.py    shared chat model (ChatOpenAI → OpenRouter)
```

`Dockerfile` and `docker-compose.yml` are placeholders until Module 4.

## Design decisions (Module 1)

Key decisions by rubric criterion. The full record, with the alternatives
considered, is in [`docs/decisions.md`](docs/decisions.md); the code cites
each `DEC-NNN` it applies. Ideas beyond the requirements are in
[`docs/improvements.md`](docs/improvements.md).

**C1.1 Project setup**
- Labs live inside the required scaffold; shared modules (`memory.py`,
  `llm_client.py`) sit at the root, split by responsibility — DEC-001,
  DEC-033, DEC-035
- LangGraph as the framework; the Coder is a `create_agent` graph —
  DEC-068, DEC-069
- LLM through OpenRouter with LangChain's `ChatOpenAI`; model set by
  `LLM_MODEL` and passed per agent — DEC-002, DEC-075
- Python 3.11 locally via uv — DEC-032

**C1.2 Memory**
- The window keeps the last N turns; a turn is one task with all its
  iterations — DEC-004, DEC-048, DEC-057
- Chroma with local embeddings (no extra API key) and an on-disk store, so
  memories survive between runs — DEC-003
- Retrieval runs before every LLM call (a middleware rebuilds the input of
  each model call), queried by the task, and its results go into the system
  message; memories already in the window are skipped — DEC-015, DEC-016,
  DEC-050, DEC-058, DEC-077
- Stored: each task and the outcome of each finished task, not tool
  observations — DEC-049, DEC-059
- A failed LLM call raises and leaves the window untouched — DEC-027,
  DEC-028, DEC-031
- Every LLM call logs the window state and the memories retrieved — DEC-025

**C1.3 Tools**
- File tools work only inside `workspace/`; arguments are validated by strict
  Pydantic models — DEC-036, DEC-042
- Scripts run in a subprocess with a 10 s default timeout (env var, 30 s
  cap); on timeout the whole process group is killed — DEC-037, DEC-044,
  DEC-045
- Scripts get an allowlisted environment, so no credentials — DEC-039,
  DEC-043
- `exec_python` always returns a useful text (output, exit code or timeout)
  — DEC-038
- Every tool call is validated with strict Pydantic models before the tool
  runs, with short error messages; `dispatch_tool` validates again and never
  raises — DEC-062, DEC-067, DEC-076

**C1.4 ReACT loop**
- Native tool calling in a `create_agent` loop; at most 10 model calls,
  enforced by LangChain's call limit placed last in the middleware —
  DEC-069, DEC-070, DEC-079
- A validated `Plan` before the loop — DEC-071
- Every tool call carries a `thought`; one tool per call; the task ends only
  through `Finish`, and text answers go back as errors — DEC-072, DEC-073,
  DEC-074
- Every step is recorded in `steps` — DEC-078

**C1.5 Structured output**
- `CoderResult` (Pydantic) is the output of a whole task — DEC-065
- `code` is read from the main file the agent declares, so it matches the
  written artifact — DEC-052
- `result` comes from the last real execution with no file written after it;
  the status says how the task ended — DEC-055, DEC-056, DEC-063
- A declared main file only counts if this task wrote or ran it; an existing
  file from an earlier task makes the answer `answered`, a missing one
  `unverified` — DEC-080

**C1.6 Verification**
- The smoke test runs a real task with the real LLM (opt-in with
  `--run-llm`) and checks the generated code's behavior in a subprocess —
  DEC-054, DEC-066

**Known simplifications** (provisional, to revisit)
- Memory deduplication only catches exact repeats — DEC-011
- One run id per process, no session id — DEC-014
- Retrieval returns the top K without a relevance threshold — DEC-017
- LLM retries are `ChatOpenAI`'s defaults until Module 4 (C4.2) — DEC-075

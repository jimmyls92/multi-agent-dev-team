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

**Not chosen yet.** The Module 1 ReACT loop is plain Python, as in the course
lab (DEC-047): the criteria for this module need no framework, and the choice
between LangGraph, AutoGen and CrewAI is made before the Module 1 submission
and at the latest in Module 2, when the PM and the Coder must run in one
orchestration graph. This section will name the framework and the reason for
the choice.

**LLM:** any OpenAI-compatible model through [OpenRouter](https://openrouter.ai)
(an equivalent of the GPT-4o / Claude Sonnet options in the course guide). The
default is `openai/gpt-4.1-mini`, set with `LLM_MODEL`.

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
the agent's credentials. `LOG_LEVEL=INFO` logs one line per iteration (tool
called) and one per LLM call (window size and memories retrieved);
`LOG_LEVEL=DEBUG` adds the full LLM input.

### How it works

- **ReACT loop** (`agents/coder_agent.py`): up to **10 iterations** per task.
  Each LLM response is `Thought` + `Action` + `Action Input`, or `Thought` +
  `FINAL ANSWER`; it is parsed into a Pydantic model before anything acts on
  it, and format errors go back to the LLM as an observation (DEC-060).
- **Tools** (`tools/`): `read_file`, `write_file`, `exec_python`, called
  through `dispatch_tool`, which validates the arguments with Pydantic and
  never raises (DEC-042, DEC-062).
- **Memory** (`memory.py`): a sliding window of the last N tasks of the
  session (each task with all its iterations is one turn), and a Chroma
  semantic store queried **before every LLM call**, whose results are
  injected into the system prompt. It stores each task and the outcome of
  each finished task (DEC-049, DEC-057, DEC-058).

### Output and statuses

Every task returns a `CoderResult` (Pydantic) with `status`, `plan` (first
Thought), `code` (read from the main file on disk), `explanation`, `result`
(output of the last real execution), `main_file`, `iterations` and `steps`
(thought, action, input and observation of each iteration).

| Status | Meaning |
|---|---|
| `success` | Final answer, the main file exists and its last run (with no file written after it) ended without error. |
| `failed_execution` | Final answer, but the last valid run failed. |
| `unverified` | Final answer without a valid run: never ran, files changed after the run, or the declared file does not exist. |
| `answered` | Text answer with no code (for example a question); nothing was executed. |
| `max_iterations` | 10 iterations without a final answer. |

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
tools/           file_io.py, code_executor.py, handlers.py (validation, dispatch), schemas.py
orchestration/   orchestration graph (Module 2)
tests/           pytest tests and the smoke test
docs/            decisions.md, improvements.md, labs/, course_reference.txt
memory.py        two-tier memory
llm_client.py    shared OpenRouter client
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
- LLM through OpenRouter with the OpenAI SDK; model set by `LLM_MODEL` —
  DEC-002
- Python 3.11 locally via uv — DEC-032

**C1.2 Memory**
- The window keeps the last N turns; a turn is one task with all its
  iterations — DEC-004, DEC-048, DEC-057
- Chroma with local embeddings (no extra API key) and an on-disk store, so
  memories survive between runs — DEC-003
- Retrieval runs before every LLM call, queried by the task, and its results
  go into the system message; memories already in the window are skipped —
  DEC-015, DEC-016, DEC-050, DEC-058
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

**C1.4 ReACT loop**
- Text format (`Thought` / `Action` / `Action Input` / `FINAL ANSWER`) parsed
  into Pydantic steps; format errors go back to the LLM as observations; at
  most 10 iterations — DEC-060
- Tools are described in the prompt, generated from their schemas — DEC-061
- `dispatch_tool` never raises and returns the structured result of each
  execution — DEC-062, DEC-067
- The plan is the first Thought; every iteration is recorded in `steps` —
  DEC-053

**C1.5 Structured output**
- `CoderResult` (Pydantic) is the output of a whole task — DEC-065
- `code` is read from the main file the agent declares, so it matches the
  written artifact — DEC-052
- `result` comes from the last real execution with no file written after it;
  the status says how the task ended — DEC-055, DEC-056, DEC-063

**C1.6 Verification**
- The smoke test runs a real task with the real LLM (opt-in with
  `--run-llm`) and checks the generated code's behavior in a subprocess —
  DEC-054, DEC-066

**Known simplifications** (provisional, to revisit)
- No agent framework yet: the loop is plain Python — DEC-047
- Memory deduplication only catches exact repeats — DEC-011
- One run id per process, no session id — DEC-014
- Retrieval returns the top K without a relevance threshold — DEC-017

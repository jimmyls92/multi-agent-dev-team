# Design decisions

Why the system is built the way it is. One entry per decision with a stable ID
(`DEC-NNN`, never reused). Code that applies a decision carries a `DEC-NNN`
comment so the reasoning can be found from the code.

**Rules**
- Record decisions that had reasonable alternatives or that someone may want to
  change later; skip obvious details.
- Never delete an entry. When a decision changes, set its status to
  `superseded by DEC-NNN` and explain the change in the new entry.
- Future ideas live in `docs/improvements.md`; when one is implemented, its
  design decision is recorded here.

**Basis** — how firm a decision is, i.e. how freely it can be changed:
- `Required` — demanded by the rubric, the guide or a lab. Change only if the
  requirement allows it.
- `Preferred` — a reasoned choice among valid alternatives. Can change with a
  good reason.
- `Provisional` — a simplification for now. Expected to be revisited when the
  `Revisit when` condition is met.

A decision can mix bases; then each part states its own.

**Template**

```markdown
### DEC-NNN Title
- Date: YYYY-MM-DD · Area: <area> (<lab>) · Status: accepted
- Basis: Required (<criterion>) | Preferred | Provisional
- Context: <the problem or constraint>
- Decision: <what was chosen>
- Why: <the reasons>
- Alternatives: <what was considered and why not>
- Revisit when: <condition, for Provisional decisions>
- Code: <files / symbols that apply it>
```

---

### DEC-001 Labs are implemented inside the project scaffold
- Date: 2026-10-30 · Area: General · Status: accepted
- Basis: Required (C1.1 folder structure; the rubric is what gets graded)
- Context: lab handouts assume a flat repo (`agent.py`, `memory.py`,
  `test_memory.py` at the root), while C1.1 requires `agents/`, `tools/`,
  `tests/`, etc. from the first commit.
- Decision: lab files are mapped into the scaffold (`agents/coder_agent.py`,
  `tools/memory.py`, `tests/test_memory.py`); the agent runs as a module
  (`python -m agents.coder_agent`) and `pytest.ini` puts the repo root on the
  import path. When a lab and a rubric criterion disagree, the criterion wins.
- Why: the course is assessed by the rubric on a single repository; keeping
  labs inside it means every lab adds to the graded system instead of living
  apart.
- Alternatives: separate lab folders or repos — the work would not count
  towards the scaffold and would need porting later.
- Code: `docs/labs/`, `pytest.ini`

### DEC-002 LLM access through OpenRouter with the OpenAI SDK
- Date: 2026-10-30 · Area: LLM client (Lab 1.1) · Status: accepted
- Basis: Preferred (constrained by the available credentials)
- Context: the lab template routes OpenAI calls through Helicone
  (`helicone_client`, model `gpt-4.1-mini`); the available credentials are for
  OpenRouter. The guide lists GPT-4o, Claude Sonnet or Ollama; the rubric
  accepts an equivalent when a named model is unavailable.
- Decision: use the official OpenAI SDK with `base_url` pointing to OpenRouter;
  the client is named `llm_client`; model from `LLM_MODEL`
  (default `openai/gpt-4.1-mini`); key from `OPENROUTER_API_KEY` in `.env`.
- Why: OpenRouter is OpenAI-compatible, so the template code barely changes and
  any model can be chosen by configuration. The client was renamed because
  `helicone_client` would misdescribe it (C5.3 readable names).
- Alternatives: Helicone (no credentials); provider-specific SDKs (more code,
  harder to switch models — relevant for C4.5 role-based model allocation).
- Revisit when: Module 4 tracing/cost (C4.1, C4.4) or role allocation (C4.5)
  needs provider features OpenRouter lacks. Document the model choice in the
  README.
- Code: `tools/memory.py` — `llm_client`; `agents/coder_agent.py` — `client`, `MODEL`

### DEC-003 Chroma client and embeddings
- Date: 2026-10-30 · Area: Memory (Lab 1.1) · Status: accepted
- Basis: mixed
  - Chroma as vector store — Required (guide; C1.2)
  - Persistent storage — Required (C1.2: a follow-up must retrieve previously
    stored information, including across runs)
  - `HttpClient` when `CHROMA_HOST` is set — Preferred (prepares C4.8, where
    Chroma runs as its own Docker service)
  - Chroma's default local embedding model (all-MiniLM-L6-v2) — Provisional
- Context: long-term memory must survive between runs locally and in Docker.
- Decision: `get_collection()` builds the client lazily: `HttpClient` if
  `CHROMA_HOST` is set, else `PersistentClient(CHROMA_PATH)`; it uses
  `get_or_create_collection` so the first run creates the collection and later
  runs reuse it.
- Why: one code path for local and Docker; lazy creation avoids side effects at
  import time and lets tests inject an in-memory collection. Default embeddings
  need no extra API key or cost.
- Alternatives: in-memory client (loses memory between runs, fails C1.2);
  embeddings through an API (extra key and cost).
- Revisit when: retrieval quality is poor for code-heavy content, or when
  Module 4 adds cost accounting for embeddings.
- Code: `tools/memory.py` — `get_collection`

### DEC-004 Sliding window stores whole turns
- Date: 2026-10-30 · Area: Memory (Lab 1.1) · Status: accepted
- Basis: mixed
  - Keeping the last N turns, N configurable — Required (C1.2)
  - Turns grouped in a `deque(maxlen=N)`; a `"user"` message opens a turn —
    Provisional (simplest model for this lab)
- Context: C1.2 counts conversation *turns*, while `chat()` adds messages one at
  a time (`user`, then `assistant`).
- Decision: `_turns` is a `deque(maxlen=max_turns)`; each item is the list of
  messages of one turn. `add()` opens a new turn on `"user"` and appends any
  other role to the current turn. `get_messages()` flattens the turns.
- Why: evicting whole turns never leaves half a turn in the window, and
  `deque(maxlen=...)` drops the oldest turn by itself. "user opens a turn" is
  the simplest rule for this lab's user → assistant exchange; the ReACT loop was
  deliberately left out of the design.
- Alternatives: flat `deque` of 2N messages (breaks when a turn does not have
  exactly two messages); list with manual eviction (more code, same result).
- Revisit when: the ReACT loop (C1.4) adds `assistant`/`tool` messages inside a
  turn — check tool calls stay paired with their results. Also IMP-001 and
  IMP-002 in `docs/improvements.md` build on this structure.
- Code: `tools/memory.py` — `SlidingWindowBuffer`

### DEC-005 Fail fast on invalid window usage
- Date: 2026-10-30 · Area: Memory (Lab 1.1) · Status: accepted
- Basis: Preferred
- Context: with the current `chat()` a turn always starts with `"user"`, so a
  non-user first message cannot happen today; `max_turns` comes from `.env`, so
  a bad value is possible.
- Decision: `add()` raises `ValueError` if a non-user message arrives with an
  empty window; `__init__` raises `ValueError` if `max_turns < 1`.
- Why: both cases mean a bug or a misconfiguration; a clear error surfaces it at
  once, whereas accepting it would silently corrupt the window
  (`maxlen=0` would discard every message). In line with C4.6 input validation.
- Alternatives: open a turn with the non-user message (hides the misuse); let
  Python raise `IndexError` (cryptic).
- Code: `tools/memory.py` — `SlidingWindowBuffer.__init__`, `SlidingWindowBuffer.add`

### DEC-006 Own memory tests with fake LLM and in-memory Chroma
- Date: 2026-10-30 · Area: Tests (Lab 1.1) · Status: superseded by DEC-007
- Basis: Preferred (the lab's own `test_memory.py` was not provided)
- Context: the lab README points to a `test_memory.py` for verification, but
  only the README was available.
- Decision: `tests/test_memory.py` checks the 3 memory TODOs and `chat()`
  against C1.2, with a fresh `EphemeralClient` collection per test and a fake
  LLM client that records the messages it receives.
- Why: tests run without API keys, network or cost, are deterministic, and can
  inspect exactly what reaches the LLM — the evidence C1.2 asks for.
- Alternatives: tests against the real LLM (cost, flaky, needs a key in CI).
- Revisit when: the official lab test becomes available (align with it), and in
  C1.6 / C4.7, which additionally need a real agent run (smoke / E2E test).
- Code: `tests/test_memory.py`, `pytest.ini`

### DEC-007 Lab 1.1 is verified with the official lab test
- Date: 2026-10-30 · Area: Tests (Lab 1.1) · Status: accepted
- Basis: Required (Lab 1.1 verification); import paths Required (DEC-001)
- Context: the official lab `test_memory.py` became available. It is a single
  integration script with the real LLM and the real Chroma store: it plants a
  fact, pushes it out of the window with `SLIDING_WINDOW_SIZE + 1` filler turns
  and checks that the reply recalls it. The own tests of DEC-006 had fixed
  design choices (unique ids for duplicate text, memories inside the system
  message, `store_memory` returning an id) without agreement.
- Decision: `tests/test_memory.py` is the lab test, changed only in its import
  paths (`tools.memory`, `agents.coder_agent`) and run command
  (`python -m tests.test_memory`). The DEC-006 tests are dropped for now (kept
  in git history).
- Why: the lab test is what defines success for the lab; the dropped tests
  encoded decisions that are now taken explicitly (TODO 2 and TODO 3).
- Implications: needs a real `OPENROUTER_API_KEY` (8 LLM calls, not
  deterministic); writes to the real `.chroma/` store; `SLIDING_WINDOW_SIZE`
  must stay ≤ 6 (only 7 filler messages); it is a script, so `pytest` does not
  collect it.
- Revisit when: C1.6 / C4.7 require automated smoke and mocked unit tests.
- Code: `tests/test_memory.py`

### DEC-008 Long-term memory stores only user messages
- Date: 2026-10-30 · Area: Memory (Lab 1.1) · Status: accepted
- Basis: Required (Lab 1.1 template: `chat()` step 1 stores the user input)
- Context: long-term memory decides what the agent can recall in future
  sessions, and what can pollute its answers if it is noise.
- Decision: `store_memory` is called with user messages only; assistant replies
  are not stored.
- Why: user messages carry the task context C1.2 asks to embed (requests and
  facts such as "I use requests"); replies are long (code blocks), take more
  space and add noise to retrieval.
- Alternatives: also store assistant replies — lets the agent recall what it
  built ("add logging to the function you wrote yesterday"), at the cost of
  noise and size.
- Revisit when: the agent needs to recall its own past outputs (e.g. from the
  ReACT loop or multi-agent modules).
- Implementation: `store_memory` takes `role` as a parameter defaulting to
  `"user"` instead of hard-coding it. Why (user): it costs nothing and avoids
  having to remember this detail if other roles are ever stored.
- Code: `tools/memory.py` — `store_memory`; `agents/coder_agent.py` — `chat()`
  (pending, TODO 4)

### DEC-009 One global memory, tagged with metadata
- Date: 2026-10-30 · Area: Memory (Lab 1.1) · Status: accepted
- Basis: mixed
  - One memory shared across sessions — Required (C1.2: a follow-up must
    retrieve previously stored information)
  - Metadata on every memory — Preferred
- Context: a single collection means facts from one project can surface in
  another; splitting memory fully would break cross-session recall.
- Decision: keep one global collection, and store metadata with every memory
  from now on (at least role, timestamp and session id).
- Why: metadata costs almost nothing now and enables filtering or ranking later
  (by session, recency...) without redesign; adding it later would leave older
  memories without tags.
- Alternatives: separate collection per session/project (breaks C1.2 recall);
  no metadata (no way to filter later).
- Revisit when: retrieval needs filtering by session/project or recency.
- Code: `tools/memory.py` — `store_memory`

### DEC-010 Reject empty text in long-term memory
- Date: 2026-10-30 · Area: Memory (Lab 1.1) · Status: accepted
- Basis: Preferred
- Context: an empty or whitespace-only message carries no information and its
  embedding is meaningless.
- Decision: `store_memory` raises `ValueError` for empty or whitespace-only
  text. Filtering trivial messages ("ok", "thanks") is out of scope (IMP-003).
- Why: consistent with DEC-005 — invalid input means a bug in the caller and
  should surface at once instead of silently polluting memory (C4.6 input
  validation).
- Alternatives: silently skip (hides caller bugs); store it (noise).
- Code: `tools/memory.py` — `store_memory`

### DEC-011 Exact deduplication of long-term memories
- Date: 2026-10-30 · Area: Memory (Lab 1.1) · Status: accepted
- Basis: Provisional (simplest useful level for the lab)
- Context: the same message can be stored many times (e.g. running the lab test
  repeatedly stores "My name is Priya…" once per run); repeated copies fill the
  `MEMORY_TOP_K` retrieval slots and crowd out other memories.
- Decision: a memory's id is derived from its normalized text, so storing the
  exact same text again does not create a second memory. Paraphrases ("Mi
  nombre es Jaime" / "Me llamo Jaime") remain separate memories.
- Why: solves literal repetition at almost no cost and with no risk of merging
  different facts; retrieval stays more varied.
- Alternatives: no deduplication (repeats crowd retrieval); semantic
  deduplication by similarity threshold (catches paraphrases but needs tuning
  and can merge different facts such as "Me llamo Jaime" / "Mi hermano se llama
  Jaime") — see IMP-004.
- Revisit when: IMP-004 / IMP-005 are implemented.
- Code: `tools/memory.py` — `store_memory`

### DEC-012 Memory id = SHA-256 of the normalized text
- Date: 2026-10-30 · Area: Memory (Lab 1.1) · Status: accepted
- Basis: Preferred (implements DEC-011)
- Context: exact deduplication needs the same text to always map to the same id.
- Decision: id = SHA-256 hex digest of the text after trimming, collapsing
  inner whitespace and lowercasing. The original text, with surrounding
  whitespace stripped, is what gets stored.
- Why: deterministic, standard library (`hashlib`), and trivial variations
  ("Hola Jaime" / "hola  jaime") count as the same memory.
- Alternatives: hash of the raw text ("Hola " and "Hola" would be two
  memories); random ids (no deduplication).
- Code: `tools/memory.py` — `store_memory`

### DEC-013 Store memories with upsert and two timestamps
- Date: 2026-10-30 · Area: Memory (Lab 1.1) · Status: accepted
- Basis: Preferred
- Context: with DEC-012, storing an already known text hits an existing id.
  `add` would ignore it; `upsert` updates the existing entry.
- Decision: use `collection.upsert`; metadata keeps `created_at` (first time
  stored, preserved on update) and `last_seen_at` (last time stored), ISO 8601
  UTC.
- Why (user): it prepares future logic where a newer fact replaces an older one
  ("now I use Python 3.11" replacing "I use Python 3.10"). Note: with DEC-012
  those two texts have different ids, so upsert alone does not replace one with
  the other; it is the mechanism a future rule (IMP-005, memory curator IMP-004)
  can use by writing the new text under the old id.
- Why (Claude): `last_seen_at` reflects what was said most recently, enabling
  recency ranking (IMP-005); `created_at` keeps the original date.
- Alternatives: `add` (repeats keep the old date); only `last_seen_at` (simpler,
  loses the first date — `created_at` costs one read before writing).
- Code: `tools/memory.py` — `store_memory`

### DEC-014 One run id per process
- Date: 2026-10-30 · Area: Memory (Lab 1.1) · Status: accepted
- Basis: Provisional (keeps the lab template unchanged)
- Context: DEC-009 tags memories with the conversation they come from, but
  `chat()` calls `store_memory(user_input)` without any session information.
- Decision: a `run_id` is generated once per process (module constant) and
  stored in every memory's metadata. Today one run = one terminal = one
  conversation, so it identifies the conversation too.
- Why: no change to the lab template; matches how the agent is used now.
- Alternatives: id per window (`conversation_id`), passed by `chat()` to
  `store_memory` — correct with several conversations per process but changes
  the template; both ids (user's proposal) — `conversation_id` for
  multi-user plus `run_id` for traceability (e.g. find memories left by a test
  run, link to C4.1 traces).
- Revisit when: one process serves several conversations (e.g. a server in
  Modules 2–4) — then move to both ids.
- Code: `tools/memory.py` — `RUN_ID`, `store_memory`

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
- Date: 2026-10-30 · Area: General · Status: accepted (refined by DEC-033, DEC-035)
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
- Code: `memory.py` — `llm_client`; `agents/coder_agent.py` — `client`, `MODEL`

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
- Code: `memory.py` — `get_collection`

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
- Code: `memory.py` — `SlidingWindowBuffer`

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
- Code: `memory.py` — `SlidingWindowBuffer.__init__`, `SlidingWindowBuffer.add`

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
  ReACT loop or multi-agent modules). Storing replies also changes when
  memory is written in `chat()`: see DEC-019.
- Implementation: `store_memory` takes `role` as a parameter defaulting to
  `"user"` instead of hard-coding it. Why (user): it costs nothing and avoids
  having to remember this detail if other roles are ever stored.
- Code: `memory.py` — `store_memory`; `agents/coder_agent.py` — `chat()`

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
- Code: `memory.py` — `store_memory`

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
- Code: `memory.py` — `store_memory`

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
- Code: `memory.py` — `store_memory`

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
- Code: `memory.py` — `store_memory`

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
- Code: `memory.py` — `store_memory`

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
- Code: `memory.py` — `RUN_ID`, `store_memory`

### DEC-015 Retrieved memories go in the system message
- Date: 2026-10-31 · Area: Memory (Lab 1.1) · Status: accepted
- Basis: mixed
  - Retrieved context reaches the LLM — Required (C1.2)
  - Placed in the system message — Preferred
- Context: retrieved memories must be injected into the prompt; they can go in
  the system message or be attached to the current user message.
- Decision: memories are added to the system message, under a heading that
  marks them as past context that may not be relevant.
- Why: inside the user message the model may read them as something the user
  is saying or asking now; in the system message they act as background. The
  lab template already assumes this structure.
- Alternatives: append them to the user message (mixes past and present
  intent).
- Code: `memory.py` — `build_context`

### DEC-016 Retrieval skips memories already in the window
- Date: 2026-10-31 · Area: Memory (Lab 1.1) · Status: accepted
- Basis: Preferred
- Context: the current message (and the rest of the window) is also stored in
  Chroma, so the top results would repeat what the LLM already sees in the
  window, wasting `MEMORY_TOP_K` slots.
- Decision: memories whose text is already in the sliding window are excluded
  from the retrieved results, not only the current message.
- Why: long-term memory exists to bring back what the window no longer holds;
  this way every retrieved slot adds new information.
- Alternatives: no exclusion (top slot always repeats the current message);
  exclude only the current message (other window messages can still repeat).
- Code: `memory.py` — `build_context`

### DEC-017 Top-K retrieval without a relevance threshold
- Date: 2026-10-31 · Area: Memory (Lab 1.1) · Status: accepted
- Basis: Provisional
- Context: retrieval returns the K closest memories even when none is related
  to the question.
- Decision: inject up to `MEMORY_TOP_K` memories (default 3, from `.env`) with
  no similarity threshold; the system prompt tells the model it may ignore
  irrelevant context.
- Why: a threshold needs calibration, and a badly tuned one can drop exactly
  the paraphrased fact the lab checks (recall with different wording).
- Alternatives: distance threshold (less noise, needs tuning, risk of missing
  the fact).
- Revisit when: irrelevant memories noticeably degrade answers, or retrieval
  quality is tuned (see also DEC-003 embeddings).
- Code: `memory.py` — `MEMORY_TOP_K`, `_retrieve_memories`

### DEC-018 Lab test runs against a separate Chroma store
- Date: 2026-10-31 · Area: Tests (Lab 1.1) · Status: accepted
- Basis: Preferred
- Context: the lab test stores "My name is Priya…" in long-term memory; in the
  real `.chroma/` store it would surface in normal conversations.
- Decision: run the test with `CHROMA_PATH=.chroma-test python -m
  tests.test_memory`; the test file stays unchanged (DEC-007) and
  `.chroma-test/` is git-ignored.
- Why: keeps test data out of the real memory without modifying the official
  test; `load_dotenv` does not override a variable already set in the shell.
- Alternatives: run against `.chroma/` (pollutes real memory); edit the test to
  use a temporary store (breaks DEC-007).
- Code: `docs/labs/lab_1_1_memory.md`, `.gitignore`

### DEC-019 User input is stored before the LLM call
- Date: 2026-10-31 · Area: Memory (Lab 1.1) · Status: accepted
- Basis: Preferred (matches the lab template order)
- Context: the flow can store the message at any point; with DEC-016 the order
  no longer affects retrieval (the current message is in the window and is
  excluded either way). It only matters when the LLM call fails.
- Decision: `chat()` stores the user input in long-term memory first, before
  building the context and calling the LLM.
- Why: user facts are kept even if the LLM call fails; since only user
  messages are stored (DEC-008), nothing depends on the LLM reply.
- Alternatives: store at the end of the turn (only completed turns are kept,
  but a failed call loses the user's facts).
- Revisit when: assistant output starts being stored (DEC-008). Then the
  reply can only be stored after the call succeeds, so storing splits in two
  moments (user input first, reply after the call), and a failure mid-turn
  leaves the user message stored without its reply.
- Code: `agents/coder_agent.py` — `chat()`

### DEC-020 Log retrieved memories at INFO on every LLM call
- Date: 2026-10-31 · Area: Memory (Lab 1.1) · Status: superseded by DEC-025
- Basis: Required (C1.2 evidence: "observed Chroma retrieval; instrumented call
  showing retrieved context"); format Preferred
- Context: a run only shows the agent's reply; nothing shows that Chroma was
  queried before the call or what reached the LLM.
- Decision: `build_context` logs one INFO line per call with the number of
  retrieved memories and, for each, its short id, distance and the first ~80
  characters of its text. Zero results are logged too.
- Why: makes retrieval observable in a real run (the rubric accepts empty
  first-run retrieval, so logging "0 memories" proves the query happened) and
  helps debug odd answers; truncation keeps the log readable.
- Alternatives: DEBUG level (hidden by default, evidence lost); full texts
  (noisy); no log (C1.2 evidence depends on reading the code).
- Revisit when: Module 4 tracing (C4.1) records retrieval in spans.
- Code: `memory.py` — `build_context`

### DEC-021 Window exclusion by over-fetching and filtering ids
- Date: 2026-10-31 · Area: Memory (Lab 1.1) · Status: accepted
- Basis: Preferred (implements DEC-016)
- Context: local Chroma cannot exclude ids in `collection.query`: `where`
  filters metadata only, and the Search API with `K.ID.not_in` is Chroma
  Cloud only (local support "planned"). Every record needs an id, and the
  text hash must stay the id for deduplication (DEC-011..DEC-013).
- Decision: `build_context` computes `_memory_id()` of each user message in
  the window, asks Chroma for `MEMORY_TOP_K + <number of those distinct ids>`
  results (capped at `collection.count()`), drops the window ids and keeps the
  first `MEMORY_TOP_K`. With an empty collection it does not query.
- Why: exact (at most one result per window id is dropped, so K results are
  returned whenever they exist), no change to `store_memory`, no duplicated
  data; the extra results (≤ N) cost nothing. Capping `n_results` avoids the
  errors/warnings some versions raise when asking for more than stored.
- Alternatives: copy the id into metadata and filter with
  `where={"memory_id": {"$nin": ids}}` (filtered inside Chroma, but stores the
  hash twice and needs a guard for an empty list); random ids with the hash
  only in metadata (breaks upsert-based deduplication).
- Revisit when: the Search API (`K.ID.not_in`) is available in local Chroma.
- Note: since DEC-031 the current input is not in the window yet, so its id
  is added to the excluded ids as well.
- Code: `memory.py` — `build_context`

### DEC-022 System message layout with retrieved memories
- Date: 2026-10-31 · Area: Memory (Lab 1.1) · Status: accepted
- Basis: Preferred (implements DEC-015)
- Decision: when memories are retrieved, the system message is
  `SYSTEM_PROMPT`, a blank line, the heading "Relevant context from past
  conversations (may not be relevant):" and one "- <text>" line per memory.
  With no memories it is `SYSTEM_PROMPT` alone. Only the text is included, no
  dates.
- Why: an empty heading could confuse the model; dates would help with
  updated facts but belong to IMP-005.
- Code: `memory.py` — `build_context`

### DEC-023 Logging is configured by the entry point
- Date: 2026-10-31 · Area: General (Lab 1.1) · Status: accepted
- Basis: Preferred (needed for DEC-020 to be visible)
- Context: Python shows only WARNING and above by default, so the INFO
  retrieval log of DEC-020 would be invisible.
- Decision: `main()` in `agents/coder_agent.py` calls
  `logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))`; `LOG_LEVEL` is
  added to `.env.example`. Library modules (`tools/`) only create loggers.
- Why: configuring global logging is the job of whoever runs the program, not
  of a library; logs go to stderr, separate from the chat output on stdout.
- Code: `agents/coder_agent.py` — `main()`, `.env.example`

### DEC-024 Pin chromadb to the 1.x series
- Date: 2026-10-31 · Area: General (Lab 1.1) · Status: accepted
- Basis: Preferred
- Decision: `requirements.txt` requires `chromadb>=1.0,<2`.
- Why: guarantees the API the memory code relies on and prevents a future 2.x
  with breaking changes from breaking fresh installs or Docker builds (C4.8).
- Revisit when: dependencies are pinned for the Docker image (Module 4).
- Code: `requirements.txt`

### DEC-025 Log window state, retrieved memories and the LLM input
- Date: 2026-10-31 · Area: Memory (Lab 1.1) · Status: accepted
- Basis: Required (C1.2 evidence: "observed buffer contents and Chroma
  retrieval; LLM input or instrumented call showing retrieved context");
  format Preferred
- Context: DEC-020 logged only the Chroma retrieval; the C1.2 evidence also
  asks to observe the buffer contents and the LLM input. The rubric does not
  ask for evidence from the lab test, so the test is run without logging.
- Decision: on every call `build_context` logs:
  - INFO: one line with the window state (turns used / max, number of
    messages) and the retrieved memories (count; short id and distance of
    each), no texts. Zero results are logged too.
  - DEBUG: the full message list sent to the LLM, system message included,
    so the memory texts appear there.
- Why: INFO shows in any normal run that the window slides and that Chroma is
  queried before each call (empty first-run retrieval is valid evidence);
  DEBUG shows the memories really reach the LLM without flooding the default
  output. Enabled with `LOG_LEVEL=DEBUG` (DEC-023).
- Why (user): one line per call keeps INFO readable when many memories are
  retrieved or a ReACT loop calls the LLM several times per turn.
- Alternatives: retrieval only (DEC-020, misses buffer contents and LLM
  input); memory texts or full messages at INFO (floods the log: e.g. 7
  memories × 5 ReACT iterations).
- Revisit when: Module 4 tracing (C4.1) records retrieval in spans.
- Code: `memory.py` — `build_context`, `SlidingWindowBuffer.__len__`

### DEC-026 MEMORY_TOP_K below 1 disables retrieval with a warning
- Date: 2026-10-31 · Area: Memory (Lab 1.1) · Status: accepted
- Basis: Preferred
- Context: `MEMORY_TOP_K` comes from `.env`; a value of 0 (or negative)
  turns long-term retrieval off, which breaks C1.2.
- Decision: when `MEMORY_TOP_K < 1`, retrieval logs a WARNING on every call
  and returns no memories without querying Chroma; the agent keeps working
  with the sliding window only.
- Why (user): unlike `max_turns < 1` (DEC-005), it does not corrupt anything —
  the agent still works — so a warning is enough. Why (Claude): warning on
  every call keeps it next to the retrieval log (DEC-025); at import time
  logging is not configured yet (DEC-023).
- Alternatives: raise `ValueError` like DEC-005 (stops the agent for a value
  that may be intentional); warn once at import (easy to miss).
- Code: `memory.py` — `_retrieve_memories`

### DEC-027 A failed LLM call raises instead of returning a reply
- Date: 2026-10-31 · Area: Coder Agent (Lab 1.1) · Status: accepted
- Basis: Preferred (prepares C3.3 and C4.2)
- Context: the LLM call in `chat()` can fail (network, invalid key, rate
  limit). `chat()` can either raise or return some text.
- Decision: `chat()` lets the error propagate; it never returns an error
  message as if it were a reply. No retries yet.
- Why: a caller must be able to tell a failed turn from a real answer. An
  error disguised as a reply would clash with C3.3 (never report success
  with failures) and hide the exception that C4.2 retries need to see.
- Alternatives: return "Error: …" as the reply (looks like a valid answer).
- Revisit when: Module 4 adds retries and the circuit breaker (C4.2, C4.3).
- Code: `agents/coder_agent.py` — `chat()`

### DEC-028 A failed turn is undone in the sliding window
- Date: 2026-10-31 · Area: Memory (Lab 1.1) · Status: accepted
- Basis: Preferred
- Context: the user turn is added to the window before the LLM call (the
  context is built from the window). If the call fails, the turn would stay
  without a reply.
- Decision: when the turn fails, the user turn is removed from the window.
  Long-term memory keeps the message (DEC-019).
- Why: the window only holds conversation that really happened; an orphan
  turn would take one of the N slots and duplicate the message in the
  context when the user retypes it.
- Alternatives: leave the orphan turn in the window.
- Code: implemented by DEC-031 — `agents/coder_agent.py` — `chat()`

### DEC-029 An empty LLM reply counts as a failed turn
- Date: 2026-10-31 · Area: Coder Agent (Lab 1.1) · Status: accepted
- Basis: Preferred
- Context: the API can return `None` or blank content.
- Decision: an empty or `None` reply is treated as a failure: same path as
  DEC-027 and DEC-028.
- Why: an empty assistant turn adds nothing to the window and would look
  like a successful answer.
- Alternatives: return "" and store it in the window.
- Code: `agents/coder_agent.py` — `chat()`

### DEC-030 The interactive loop survives a failed turn
- Date: 2026-10-31 · Area: Coder Agent (Lab 1.1) · Status: accepted
- Basis: Preferred
- Context: with DEC-027, an error in `chat()` would end the program.
- Decision: `main()` catches the error, shows a short message to the user,
  logs it at ERROR and keeps the conversation going.
- Why: a transient network error should not lose the session. Callers that
  use `chat()` directly (e.g. the lab test) still see the failure.
- Alternatives: let the program exit.
- Code: `agents/coder_agent.py` — `main()`

### DEC-031 The window is updated only after a successful turn
- Date: 2026-10-31 · Area: Memory (Lab 1.1) · Status: accepted
- Basis: Preferred (implements DEC-028)
- Context: the lab template adds the user turn to the window before
  `build_context`, so a failed LLM call leaves it there. With a full window,
  `deque(maxlen=N)` has already evicted the oldest turn by then.
- Decision: `build_context` receives the current input separately and appends
  it after the window; `chat()` adds the user and assistant messages to the
  window together, only after a valid reply. Retrieval excludes the current
  input by id (`_memory_id(user_input)`), on top of the window ids (DEC-016,
  DEC-021).
- Why: a failed turn never touches the window, so there is nothing to undo
  and no extra buffer API. The current input is already in Chroma (DEC-019)
  and would come back as a "past" memory with distance ~0, taking a top-K
  slot; excluding it inside `build_context` holds regardless of call order.
- Alternatives: snapshot/restore the buffer around the turn (exact, but adds
  API and copies); `pop_last_turn()` (loses the turn evicted when the window
  is full); build the context before storing the input (misses repeated
  messages already in Chroma, stops protecting from the second ReACT
  iteration on (C1.4), and would change DEC-019).
- Code: `memory.py` — `build_context`, `_retrieve_memories`;
  `agents/coder_agent.py` — `chat()`

### DEC-032 Local environment uses Python 3.11 via uv
- Date: 2026-11-02 · Area: General (Lab 1.1) · Status: accepted
- Basis: Preferred (parity with the Docker image, C4.8)
- Context: WSL ships Python 3.14 without pip or venv support, installing them
  needs sudo, and the Docker image is pinned to Python 3.11 (C4.8).
- Decision: install `uv` in user space and create `.venv` with Python 3.11
  (`uv venv --python 3.11 .venv`, then `uv pip install -r requirements.txt`).
  On `/mnt/c` set `UV_LINK_MODE=copy` (hardlinks do not work across
  filesystems).
- Why: local runs behave like the container; no sudo needed; native
  dependencies of `chromadb` (e.g. `onnxruntime`) have wheels for 3.11.
- Alternatives: system Python 3.14 with `apt install python3-venv
  python3-pip` (simpler, but differs from Docker and risks missing wheels).
- Code: `.venv/` (git-ignored); setup to be documented in `README.md`

### DEC-033 The required structure is a minimum, not a closed list
- Date: 2026-11-03 · Area: General (Lab 1.2) · Status: accepted
- Basis: Required (C1.1 structure, C5.3 separation by responsibility);
  Preferred (where extra files go)
- Context: DEC-001 maps lab files into the scaffold, which was read as "only
  the files of section 1.5 may exist". The guide says the structure must be
  there from day one and "you will expand it each module"; C1.1 only checks
  that the listed folders and files exist; C5.3 asks for code separated by
  responsibility, with shared behavior factored.
- Decision: files beyond the section 1.5 structure can be added, at the root
  or inside the folders, as long as each one has a clear responsibility and
  does not duplicate another. The required folders and files are never
  removed or renamed.
- Why: matches what the rubric actually checks; the real risk for C5.3 is
  confusing or duplicated responsibilities, not extra files.
- Alternatives: forcing every file into the five folders (no rubric basis;
  e.g. shared infrastructure like the LLM client would end up inside an
  unrelated module).
- Code: `llm_client.py`, `pytest.ini`

### DEC-034 Placement of the Lab 1.2 scaffold files
- Date: 2026-11-03 · Area: Tools (Lab 1.2) · Status: accepted
- Basis: Preferred (C5.3); OpenRouter Required by DEC-002
- Context: the lab ships `schemas.py`, `agent.py` and `llm_client.py` for a
  flat repo, and `llm_client.py` requires `HELICONE_API_KEY`. The OpenRouter
  client currently lives in `tools/memory.py`, and `agents/coder_agent.py`
  imports it from there.
- Decision:
  - `llm_client.py` stays at the root as the single shared LLM client,
    adapted to OpenRouter (DEC-002); the agents get the client from it and
    the memory module no longer defines one.
  - `schemas.py` moves to `tools/schemas.py`, next to `TOOL_HANDLERS`.
  - `agent.py` moves to `agents/tools_demo.py` (`python -m
    agents.tools_demo`), adapted to the shared client and `LLM_MODEL`.
- Why: the memory module should not own the LLM client (C5.3 shared behavior
  factored); tool schemas belong with their handlers; a root `agent.py` next
  to `agents/coder_agent.py` would make it unclear which agent is the system.
- Alternatives: keep the files at the root unchanged (Helicone client fails
  with the available credentials; two "agents"); drop `llm_client.py` and keep
  the client in `memory.py` (memory keeps owning infrastructure).
- Revisit when: Lab 1.3 moves the demo loop into `agents/coder_agent.py`
  (the demo may then be removed).
- Code: `llm_client.py`, `tools/schemas.py`, `agents/tools_demo.py`,
  `agents/coder_agent.py` — `chat()`

### DEC-035 Memory lives at the repo root, outside `tools/`
- Date: 2026-11-03 · Area: Memory (Lab 1.2) · Status: accepted
- Basis: Preferred (C5.3 separation by responsibility; allowed by DEC-033)
- Context: DEC-001 mapped the lab's `memory.py` to `tools/memory.py`. With
  Lab 1.2, `tools/` becomes the package of tools the LLM calls
  (`TOOL_HANDLERS`, `tools/schemas.py`); memory is not one of them, it runs
  around every LLM call.
- Decision: move `tools/memory.py` to `memory.py` at the root, next to
  `llm_client.py`; imports become `import memory` / `from memory import ...`.
  The `Code:` lines of earlier entries were updated to the new path; their
  decision texts keep the path they had when they were taken.
- Why: `tools/` holds only what the agent can invoke, so its contents match
  the tool schemas; shared infrastructure (LLM client, memory) sits together
  at the root.
- Alternatives: keep it in `tools/` (mixes infrastructure with LLM tools);
  a new package such as `core/` (more structure than two modules need today).
- Code: `memory.py`, `agents/coder_agent.py`, `tests/test_memory.py`

### DEC-036 The agent's file tools work only inside a workspace directory
- Date: 2026-11-03 · Area: Tools (Lab 1.2) · Status: accepted
- Basis: Preferred (CLAUDE.md: validate tool arguments; C4.6 no leaked secrets)
- Context: `read_file`, `write_file` and `exec_python` accept any path, so the
  agent could overwrite its own code (`agents/`, `tools/`), read `.env` or
  touch the Chroma data. The lab does not mention it and C1.3 does not
  require it.
- Decision: when the agent calls the tools, paths are confined to a dedicated
  working directory (`workspace/`, ignored by git); a path outside it gets an
  error string and the tool does not run. This covers the tool arguments only:
  the code run by `exec_python` is not confined (no OS-level sandbox).
- Why: the agent cannot break the system it runs on or read its secrets
  through the tools, and its outputs stay in one place.
- Alternatives: no confinement (the lab's default; the agent can edit its own
  code); a full sandbox for executed code (needs container isolation,
  Docker arrives in Module 4).
- Revisit when: Module 4 adds Docker (executed code could then be isolated
  too).
- Code: `tools/handlers.py` — `WORKSPACE_DIR`, `_resolve_in_workspace`; `.gitignore`

### DEC-037 Execution timeout: operator default by env var, LLM capped at 30 s
- Date: 2026-11-03 · Area: Tools (Lab 1.2) · Status: accepted
- Basis: Required (C1.3: configurable timeout, 10 s default; lab: 30 s cap);
  Preferred (environment variable as the configuration mechanism)
- Context: C1.3 asks for a configurable timeout and the assessor probes it.
  The lab's `exec_python` only takes it as an argument from the LLM.
- Decision: the default comes from `EXEC_TIMEOUT` (10 if unset); the LLM may
  ask for another value per call, always clamped to 30 s.
- Why: the operator or assessor can change the timeout without touching code,
  and the LLM still gets more time for slow scripts within a hard limit.
- Alternatives: argument only (the lab's version; configurable only by the
  LLM); env var only, ignoring the argument (drops a parameter the schema
  exposes).
- Code: `tools/code_executor.py` — `EXEC_TIMEOUT`, `exec_python`

### DEC-038 What `exec_python` returns to the agent
- Date: 2026-11-03 · Area: Tools (Lab 1.2) · Status: accepted
- Basis: Preferred
- Context: the agent only sees the string the tool returns; the lab returns
  stdout on success (possibly `""`) and cuts long output from the end.
- Decision:
  - A failed run returns the exit code, stderr and any stdout printed before
    the failure.
  - A successful run returns stdout, plus stderr (labeled) when it is not
    empty, e.g. warnings.
  - A successful run with no output returns an explicit message saying it ran
    successfully with no output, never an empty string.
  - Truncation keeps the beginning of a successful output and the end of an
    error output.
  - The script's stdin is closed, so `input()` fails at once with `EOFError`
    instead of waiting for the timeout.
- Why: the agent debugs from this string alone, so partial output and
  warnings save it extra reads; an empty result is the lab's documented cause
  of agents looping; in a traceback the actual error is in the last lines;
  nobody can type into the script (no human after the initial prompt), and
  closing stdin is the usual practice for unattended execution.
- Alternatives: stdout only on success and stderr only on failure (the lab's
  version; loses warnings and partial output); return `""` (the agent may
  retry forever); always keep the beginning (loses the error line of long
  tracebacks); inherit stdin (a script calling `input()` hangs until the
  timeout). Human-in-the-loop, if ever needed, belongs in the orchestrator,
  not in the script's stdin.
- Code: `tools/code_executor.py` — `exec_python`, `_keep_start`, `_keep_end`

### DEC-039 Executed scripts run without the agent's credentials
- Date: 2026-11-03 · Area: Tools (Lab 1.2) · Status: accepted
- Basis: Preferred (C4.6 no leaked secrets)
- Context: the agent loads `.env` into its environment and a subprocess
  inherits a copy of it, so generated code could read `OPENROUTER_API_KEY`
  and print it (it would then reach the LLM context, logs, traces and memory)
  or send it out.
- Decision: `exec_python` starts the script with a copy of the environment
  without the credential variables.
- Why: generated code cannot read the key from its environment. None of the
  project's target programs needs an API key.
- Alternatives: inherit the full environment (the lab's default; exposes the
  key). Reading `.env` from disk is still possible for the script; only
  container isolation closes that (see DEC-036).
- Revisit when: Module 4 adds Docker (the executor container may not hold the
  credentials at all).
- Code: `tools/code_executor.py` — `_script_env`

### DEC-040 Scripts run with their own directory as working directory
- Date: 2026-11-03 · Area: Tools (Lab 1.2) · Status: accepted
- Basis: Preferred
- Context: relative paths inside a script resolve against the process working
  directory, not the script's location. Launched from the repo root, a script
  writing `result.txt` would create it at the root.
- Decision: `exec_python` runs each script with the script's directory as its
  working directory.
- Why: files the script creates land next to it, inside `workspace/`
  (DEC-036), instead of polluting the repo.
- Alternatives: inherit the agent's working directory (the lab's default);
  always use the `workspace/` root (breaks relative paths of scripts in
  subfolders).
- Code: `tools/code_executor.py` — `exec_python`

### DEC-041 `read_file` returns at most 20,000 characters
- Date: 2026-11-03 · Area: Tools (Lab 1.2) · Status: accepted
- Basis: Preferred
- Context: the lab's `read_file` returns the whole file; a large file fills
  the LLM context and raises the cost of every following call.
- Decision: the content is cut at a limit configurable by environment
  variable, 20,000 characters by default, with a mark saying it was truncated.
- Why: protects context and cost; characters keep the limit simple,
  deterministic and model-independent, consistent with `exec_python`'s
  2,000-character output limit.
- Alternatives: no limit (the lab's default); a limit in tokens (exact only
  with each model's tokenizer, extra dependency, approximate for non-OpenAI
  models behind OpenRouter).
- Code: `tools/file_io.py` — `READ_MAX_CHARS`, `read_file`

### DEC-042 Tool arguments are validated by Pydantic wrappers in `TOOL_HANDLERS`
- Date: 2026-11-03 · Area: Tools (Lab 1.2) · Status: accepted
- Basis: Required (C1.3, C4.6: validate LLM output and tool arguments with
  Pydantic); Preferred (wrapper layer)
- Context: the workspace confinement (DEC-036) must apply to the LLM's tool
  calls, but the lab's tests call `read_file`, `write_file` and `exec_python`
  directly with temporary paths outside any workspace.
- Decision: one Pydantic model per tool validates the arguments (types,
  timeout >= 1) and resolves the path: relative paths go under the workspace,
  and any path that ends up outside it (`../`, absolute path, symlink) is
  rejected. `TOOL_HANDLERS` maps each tool name to a wrapper that validates
  first and returns an error string on invalid arguments, without calling the
  tool. The lab functions stay unconfined.
  - The models and wrappers live in their own module, `tools/handlers.py`;
    `tools/__init__.py` only exports `TOOL_HANDLERS`.
  - Validation is strict: no type coercion (`"10"`, `10.0` or `true` are not
    a valid `timeout`) and extra arguments are rejected.
- Why: the lab's tests and contract stay unchanged, and every caller of
  `TOOL_HANDLERS` (`agents/tools_demo.py`, later the Coder Agent) gets
  validation and confinement without code of its own. A separate module
  keeps the lab's files and the tool list readable and the validation
  testable on its own. Strict mode accepts exactly what the schema tells the
  LLM, so a wrong type is an invalid output that never reaches the tool
  (C1.3, C4.6) instead of a silent conversion (`true` would become a 1 s
  timeout).
- Alternatives: confine inside the tool functions (breaks the lab's tests);
  validate in each agent's dispatch (duplicated, easy to forget); wrappers
  inside `tools/__init__.py` (where the lab defines `TOOL_HANDLERS`; mixes
  the tool list with validation logic); lax validation (saves the LLM a
  retry when it sends `"10"`, but converts values silently).
- Code: `tools/handlers.py` — `TOOL_HANDLERS`, `_validated`; `tools/__init__.py`

### DEC-043 The script's environment is an allowlist
- Date: 2026-11-03 · Area: Tools (Lab 1.2) · Status: accepted
- Basis: Preferred (implements DEC-039)
- Context: DEC-039 removes credentials from the executed script's
  environment.
- Decision: the script receives only the variables it needs to run (`PATH`,
  `HOME`, `LANG`/`LC_*`, `TMPDIR`) plus `PYTHONIOENCODING=utf-8`.
- Why: deny by default; credentials added later (e.g. tracing keys in
  Module 4) are excluded without anyone remembering to list them.
- Alternatives: a denylist of names containing KEY/TOKEN/SECRET (misses
  secrets with other names, e.g. a `DATABASE_URL` with a password).
- Code: `tools/code_executor.py` — `_ENV_ALLOWLIST`, `_script_env`

### DEC-044 The timeout kills the script's whole process group
- Date: 2026-11-03 · Area: Tools (Lab 1.2) · Status: accepted
- Basis: Required (C1.3: a non-terminating execution is stopped by the
  timeout); Preferred (mechanism)
- Context: `subprocess.run` kills only the direct child on timeout; processes
  the script started survive and keep the output pipes open, so the call can
  hang past the timeout.
- Decision: `exec_python` starts the script with `Popen` in a new session and
  waits for the script itself to exit, not for its output pipes to close
  (they are read in threads meanwhile). When the script exits or the timeout
  expires, the whole process group is killed (`os.killpg`), so nothing it
  started survives. POSIX only: Linux, WSL and Docker are the project's
  environments.
- Why: the assessor's timeout probe must stop every process the script
  created, not just the first one. A background process holds the pipes
  open, so waiting for them would make a script that finished correctly
  wait until the timeout and be reported as killed, a false diagnosis the
  agent would try to "fix".
- Alternatives: `subprocess.run` as the lab hints (can hang with child
  processes); `communicate()` with a timeout (kills the whole group, but a
  successful script that leaves a background process is reported as a
  timeout); output to temporary files instead of threads (no pipes, but an
  endless print loop fills the disk).
- Code: `tools/code_executor.py` — `exec_python`

### DEC-045 Tool configuration through environment variables, checked at startup
- Date: 2026-11-03 · Area: Tools (Lab 1.2) · Status: accepted
- Basis: Required (C1.3: configurable timeout, 10 s default; lab: 30 s cap);
  Preferred (mechanism and startup check)
- Context: DEC-036, DEC-037 and DEC-041 introduce settings the operator or the
  assessor must be able to change without touching code.
- Decision:
  - `EXEC_TIMEOUT` (default 10), `READ_MAX_CHARS` (default 20000) and
    `WORKSPACE_DIR` (default `workspace`, resolved against the repo root) are
    read at module level with `os.getenv`, like the memory settings.
  - A value that is not a number, or an `EXEC_TIMEOUT` outside 1–30, stops the
    program at startup with a clear error.
  - `exec_python(path, timeout=None)` uses `EXEC_TIMEOUT` when no timeout is
    given; a value from the LLM is clamped to 30.
- Why: an impossible setting is an operator error and must show at once
  instead of being silently replaced (same approach as `LOG_LEVEL`, DEC-023);
  resolving the workspace against the repo root keeps it in one place
  whatever directory the agent is started from.
- Alternatives: silently clamp `EXEC_TIMEOUT` to 30 (the configured value is
  not the applied one); let `EXEC_TIMEOUT` raise the cap (drops the lab's
  fixed limit).
- Code: `tools/code_executor.py` — `EXEC_TIMEOUT`; `tools/file_io.py` — `READ_MAX_CHARS`;
  `tools/handlers.py` — `WORKSPACE_DIR`; `.env.example`

### DEC-046 Docstrings follow the Google Python Style Guide
- Date: 2026-11-03 · Area: General · Status: accepted
- Basis: Preferred (user requirement)
- Context: the code mixed NumPy-style docstrings from the lab, one-line
  docstrings, comment headers and undocumented functions; the lab's
  docstrings also carried implementation hints that no longer match the code
  (e.g. use `subprocess.run`, replaced by `Popen` in DEC-044).
- Decision:
  - Every module, class and function, private and nested ones included, has
    a Google-style docstring: descriptive one-line summary and `Args:`,
    `Returns:`, `Raises:` and `Attributes:` sections when they apply.
  - In tests, modules, classes, fixtures and helpers have docstrings;
    descriptive `test_*` methods do not, as the guide allows.
  - The lab's `Hints` sections and stale instructions ("Implement one
    function", "Run this AFTER all tests pass") are removed; docstrings
    describe what the code does. Placeholder files that are still empty
    (`agents/pm_agent.py`, `agents/qa_agent.py`, `tests/__init__.py`) get
    theirs when they get code.
- Why: one consistent, widely known format that tools (IDEs, Sphinx
  napoleon) understand; documentation that matches the implementation
  (C5.3); test names already say what they check, so docstrings there would
  only repeat them.
- Alternatives: keep the lab's NumPy style (inconsistent with the project's
  own code); document every `test_*` method (about 30 docstrings repeating
  the test name); keep the hints as a `Note` (describes things the code does
  not do).
- Code: all `*.py` files; rule in `CLAUDE.md`

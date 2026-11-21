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
- Date: 2026-10-30 · Area: LLM client (Lab 1.1) · Status: accepted (refined by DEC-075)
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
- Date: 2026-10-30 · Area: Memory (Lab 1.1) · Status: accepted (refined by DEC-057)
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
- Date: 2026-10-30 · Area: Memory (Lab 1.1) · Status: superseded by DEC-049
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
- Date: 2026-10-31 · Area: Coder Agent (Lab 1.1) · Status: accepted (refined by DEC-060)
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
- Date: 2026-11-03 · Area: Tools (Lab 1.2) · Status: accepted (refined by DEC-051)
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

### DEC-047 Lab 1.3 ReACT loop in plain Python; framework chosen later
- Date: 2026-11-05 · Area: Coder Agent (Lab 1.3) · Status: superseded by DEC-068
- Basis: Provisional (C1.4 needs no framework; C1.1 needs one named in the
  README; C2.3 needs PM and Coder in one orchestration graph)
- Context: the Lab 1.3 handout builds the ReACT loop in plain Python with a
  text protocol (`Thought:` / `Action:` / `Action Input:` / `FINAL ANSWER:`).
  The course guide asks to choose LangGraph, AutoGen or CrewAI in Module 1
  ("you may switch in later modules"), and CLAUDE.md planned to choose it
  before the loop.
- Decision: implement the Lab 1.3 loop as the handout does, without a
  framework; choose the framework later.
- Why: least friction now, since the lab's code and tests are written for
  plain Python; C1.4 only requires a bounded action/observation loop.
- Alternatives: choose the framework now and build the loop with it (README
  truthful from Module 1 and Module 2 starts from the same graph, but the
  lab's code and tests would have to be adapted).
- Revisit when: before the Module 1 submission — C1.1 requires the README to
  name the chosen framework and it must not contradict the code — and at the
  latest in Module 2, when C2.3 puts PM and Coder in one graph (a change of
  framework is justified in the README, C2.6).
- Code: `agents/coder_agent.py` — `run_agent` (plain Python loop)

### DEC-048 The Coder works in sessions: one ReACT run per user message
- Date: 2026-11-05 · Area: Coder Agent (Lab 1.3) · Status: accepted
- Basis: mixed
  - Window of the last N conversation turns, observable — Required (C1.2)
  - One task per user message, its iterations grouped in one turn —
    Preferred
  - Window owned by the Coder, never shared with other agents — Preferred
- Context: the Lab 1.3 `run_agent(task)` solves one task with a fresh
  window, so the window would only ever hold one turn: the last-N-turns
  behavior C1.2 asks to observe would never happen, and the Lab 1.1 recall
  test (`tests/test_memory.py`) would lose its meaning. DEC-004 asked to
  revisit the window when the loop adds tool/observation messages.
- Decision:
  - The Coder keeps an interactive session (as `chat()` in Lab 1.1). Each
    user message is a task that runs the ReACT loop (up to 10 iterations,
    C1.4); the window persists between messages of the session.
  - A turn is one task plus all its iterations (Thought/Action and
    Observation messages); the window keeps the last N turns. Observations
    must not open a new turn.
  - Older turns and earlier sessions come back through long-term memory,
    which is still queried before every LLM call (C1.2).
  - A one-shot run (lab test, C1.6 smoke test) is a session with a single
    task.
  - The window belongs to the Coder; other agents (QA) never see it. What
    passes between agents is the shared state and the handoff (C2.2, C2.3).
- Why: the most literal reading of C1.2 ("conversation turns"); keeps what
  Lab 1.1 already meets; the task never leaves the window while the agent
  works on it.
- Alternatives: fresh window per task (window never slides, C1.2 evidence
  at risk); one iteration per turn with the task pinned (the agent forgets
  its first iterations and "turn" is stretched to mean "iteration").
- Revisit when: Module 2/3 design what the Coder keeps between PM tasks
  and QA feedback rounds.
- Code: `agents/coder_agent.py` — `run_agent`, `chat`, `main`; `memory.py` —
  `SlidingWindowBuffer.add_turn`

### DEC-049 Long-term memory also stores the outcome of each completed task
- Date: 2026-11-05 · Area: Memory (Lab 1.3) · Status: accepted
- Basis: Preferred (C1.2 is met by every option; this one makes the
  follow-up recall useful for a coding agent)
- Context: DEC-008 stores only user messages, which with DEC-048 are the
  tasks. Its `Revisit when` pointed to the ReACT loop: the agent may need to
  recall what it built (e.g. "add logging to yesterday's function"). The
  lab stores the final answer and every non-error observation.
- Decision:
  - The task is stored before the first LLM call, as today (DEC-019).
  - When the task ends with a FINAL ANSWER, one memory "task + final
    answer" is stored after the loop. A task that hits the iteration limit
    stores no answer.
  - Observations are not stored.
  - While a task is still in the window, its outcome memory is not
    retrieved (same principle as DEC-016).
- Why: the agent can recall what it delivered and where, in a later
  session; storing one outcome per task keeps the noise DEC-008 avoided
  low; an unfinished task is not remembered as a success.
- Alternatives: also store non-error observations as the lab does (file
  contents and script outputs crowd out the 3 retrieval slots); only the
  task (the agent cannot recall what it built or where).
- Revisit when: the stored answers turn out too long or noisy for
  retrieval (e.g. summarise them), or Module 2/3 change what the Coder
  needs to recall.
- Code: `memory.py` — `store_memory`, `store_outcome`; `agents/coder_agent.py` —
  `run_agent`

### DEC-050 Retrieval runs before every loop iteration, queried by the task
- Date: 2026-11-05 · Area: Memory (Lab 1.3) · Status: accepted
- Basis: Required (C1.2: retrieval before every LLM call); query by the
  task — Preferred
- Context: in the ReACT loop only the first LLM call follows a user
  message; iterations 2-10 follow observations. The lab retrieves once,
  when it builds the system prompt.
- Decision: long-term memory is queried before every LLM call of the loop,
  always with the current task as the query, and the result is injected
  in the system message as today (DEC-015).
- Why: meets C1.2 literally and stays visible in the per-call log
  (DEC-025); same behavior as `build_context()` in Lab 1.1; stable results
  and no cost, since embeddings are local (DEC-003).
- Alternatives: query by task plus latest observation (adapts to what
  happens, but long observations distort the query and results are harder
  to evidence; kept as IMP-006); retrieve once per task as the lab does
  (calls 2-10 run without retrieval: C1.2 at risk).
- Code: `agents/coder_agent.py` — `run_agent` (calls `build_context` before every
  LLM call)

### DEC-051 One Coder agent in `agents/coder_agent.py`
- Date: 2026-11-05 · Area: Coder Agent (Lab 1.3) · Status: accepted
- Basis: mixed
  - A single Coder whose loop is the orchestration code — Preferred
    (C1.4 evidence, C5.3 no duplicated responsibilities)
  - `chat()` kept as the entry point of one session message — Preferred
    (the official Lab 1.1 test, C1.2 evidence per DEC-007, keeps passing
    unchanged)
- Context: the project has `agents/coder_agent.py` (Lab 1.1 conversation)
  and `agents/tools_demo.py` (Lab 1.2 function-calling demo, DEC-034), and
  Lab 1.3 ships its own `agent.py` with the ReACT loop. DEC-034 asked to
  revisit the demo in this lab.
- Decision:
  - The project ends with a single agent file for the Coder:
    `agents/coder_agent.py` holds the ReACT loop (DEC-048). The lab's
    `agent.py` is not added as a separate file.
  - `chat(user_input, window)` stays as the entry point for one message of
    the session: it runs the loop and returns the final answer text.
    `python -m agents.coder_agent` stays interactive.
  - `agents/tools_demo.py` is removed once the Coder uses the tools.
- Why: one Coder, where the assessor looks for the loop; the Lab 1.1 recall
  test keeps testing the same entry point, so C1.2 has no regression; the
  Coder invoking the tools is what C1.3 checks, so the demo becomes a
  duplicated loop with another style (native function calling).
- Alternatives: a new `agents/react_agent.py` next to `coder_agent.py` (two
  "Coders", unclear which is the system); drop `chat()` and adapt the
  official test (touches the C1.2 evidence); keep the demo (two agent
  loops).
- Revisit when: how the lab's pieces are organised inside `coder_agent.py`
  is decided in the technical phase.
- Code: `agents/coder_agent.py` — `run_agent`, `chat`; `agents/tools_demo.py`
  removed

### DEC-052 The LLM declares the deliverable; the system reads its code from disk
- Date: 2026-11-05 · Area: Coder Agent (Lab 1.3) · Status: accepted
- Basis: Required (C1.5: code matches the artifact written by the tools;
  C4.6: LLM outputs validated before use); how — Preferred
- Context: C1.5 requires an output with `code`, `explanation`, `plan` and
  `result`; the lab's `AgentResult` has none of them and returns the
  LLM's free-text final answer.
- Decision: the final answer states the main file of the deliverable and
  an explanation; it is validated with Pydantic before use. `code` is the
  content of that file read from disk after the loop; `explanation` comes
  from the final answer. A declared file that does not exist is never a
  success.
- Why: `code` matches the written artifact by construction; the LLM's
  claim is checked, not trusted.
- Alternatives: every file written in the task (mixes the deliverable with
  test scripts; `code` stops being a text); the code the LLM writes in its
  final answer (may differ from the file: C1.5 at risk).
- Code: `agents/coder_agent.py` — `Finish`, `_read_main_file`, `result_from_messages`

### DEC-053 The plan is the agent's first Thought, kept apart from the action record
- Date: 2026-11-05 · Area: Coder Agent (Lab 1.3) · Status: superseded by DEC-071
- Basis: Required (C1.4 evidence: "concise plan and action/observation
  record"; C1.5 `plan` field); how — Preferred
- Context: the output needs a `plan`; ReACT decides each step from the
  last observation, so the plan must not turn the loop into
  Plan-and-Execute.
- Decision: the agent's first response states a short step plan, which is
  kept as `plan`. The record of actions and observations (tool, arguments,
  result) is kept separately. The plan guides; it does not bind: later
  steps are chosen from the observations (C1.4).
- Why: gives both pieces of C1.4 evidence and a plan that describes the
  task (C1.5) while staying ReACT.
- Alternatives: rebuild the plan from the actions taken (a record, not a
  plan; duplicates the action record); ask for the plan in the final
  answer (written after acting, weaker C1.4 evidence).
- Revisit when: the initial plan often differs from what the agent ends up
  doing (e.g. keep the last stated plan instead).
- Code: `agents/coder_agent.py` — `REACT_SYSTEM_PROMPT`, `run_agent`

### DEC-054 The smoke test runs a real task and checks the generated code works
- Date: 2026-11-05 · Area: Tests (Lab 1.3) · Status: accepted
- Basis: Required (C1.6: smoke test asserting the structured-output fields;
  an observed run produces working code)
- Context: the lab's end-to-end test only checks that a file exists and
  contains `def word_frequency`, not the C1.5 fields; its `--run-llm` flag
  does not work.
- Decision: a smoke test with the real LLM gives the Coder a short coding
  task, asserts the four fields and a success status, and imports and runs
  the generated code to check its behavior. Its exact content is proposed
  and approved before writing it.
- Why: covers both halves of C1.6 and follows the project rule that tests
  check behavior, not fixed objects or text.
- Alternatives: only check that the fields exist and are not empty (the
  "working code" half rests on a manual run).
- Code: `tests/test_smoke.py` — `test_coder_writes_and_runs_working_code`

### DEC-055 `result` comes from a real execution; the output always has a status
- Date: 2026-11-05 · Area: Coder Agent (Lab 1.3) · Status: accepted
- Basis: Required (C1.5: result reflects actual execution, no success
  claimed without it; C1.4: the iteration limit is probed); the statuses —
  Preferred
- Context: the agent can finish without running its code, change files
  after the last run, declare a missing file, finish with a failing run,
  or hit the 10-iteration limit. The lab only has `stopped_early`.
- Decision:
  - `result` is the output of the last `exec_python` call, valid only if
    no file was written after it.
  - The output is always the same Pydantic model, with whatever fields are
    known, and a status:
    - `success`: FINAL ANSWER, the main file exists, and the last valid
      execution ended without error.
    - `failed_execution`: FINAL ANSWER, but the last valid execution ended
      with an error.
    - `unverified`: FINAL ANSWER without a valid execution (never ran,
      files changed afterwards, or the declared file does not exist).
    - `max_iterations`: 10 iterations without FINAL ANSWER.
  - Reaching the limit or failing never raises; it returns the model.
- Why: success is only reported when the system has checked it; the
  assessor's limit probe ends cleanly; later agents (QA, C3.3) can tell
  success from failure without reading text.
- Alternatives: the system runs the main file itself after the loop (a
  file that only defines functions prints nothing, and it runs something
  the agent did not ask for); trust the LLM's report of the result (C1.5
  Not Yet); raise on the limit (the assessor probe ends in a crash).
- Code: `agents/coder_agent.py` — `_final_status`, `result_from_messages`

### DEC-056 A final answer without code has its own status, `answered`
- Date: 2026-11-05 · Area: Coder Agent (Lab 1.3) · Status: accepted (refined by DEC-080)
- Basis: Required (C1.2: the official Lab 1.1 recall test sends
  conversational messages through `chat()` and must keep passing; C1.5: no
  success without a real execution); the status name — Preferred
- Context: with DEC-048 every message runs the ReACT loop, but some
  messages are questions, not coding tasks ("What is my name and what am I
  building?"). Under DEC-052/DEC-055 a final answer with no main file
  would be `unverified`, as if a coding task had failed.
- Decision: the final answer may omit the main file. Then the status is
  `answered`, `code` and `result` are empty and `chat()` returns the
  explanation text. The status describes the evidence behind the answer,
  not its quality: `success` always means a written file whose last run
  succeeded; `answered` means text only, checked by nothing. Whether an
  answer meets the request is QA's job (Module 3, C3.1).
- Why: the agent decides inside the ReACT loop whether code is needed; the
  recall test passes unchanged; a coding task "solved" in text without a
  file never shows as `success`, so the orchestrator (Module 2) and QA
  (C3.3) can detect it from the status alone.
- Alternatives: every message is a coding task and questions end as
  `unverified` (misleading status); a single `success` with an empty
  `main_file` meaning "no code" (a success without execution, C1.5 at
  risk; consumers that read only the status are misled); classify the
  message before the loop and answer questions without it (part of the
  messages skip ReACT, C1.4 at risk; an extra LLM call, C4.4).
- Code: `agents/coder_agent.py` — `Finish`, `result_from_messages`, `chat`

### DEC-057 The ReACT loop adds each task to the window as one whole turn
- Date: 2026-11-05 · Area: Memory / Coder Agent (Lab 1.3) · Status: accepted (refined by DEC-077)
- Basis: Required (C1.2: last N turns; DEC-048: a turn is one task plus all
  its iterations); how — Preferred
- Context: DEC-004 opens a turn on every "user" message and asked to be
  revisited when the loop adds messages inside a turn. Observations are sent
  as "user" messages: with chat APIs the only roles are system, user and
  assistant ("tool" needs native function calling), and "assistant" would
  tell the model it wrote the observation itself. With `add()`, every
  observation would open a turn and push earlier tasks out of the window.
- Decision: during a task the loop collects the turn's messages (task,
  Thought/Action responses, observations) in a local list. When the loop
  ends, `window.add_turn(messages)` appends them as one turn. `add()` stays
  as it is.
- Why: N turns are N tasks; a failure in the middle of a task (e.g. an API
  error) leaves the window untouched (DEC-028); observations keep the
  "user" role, so the model reads them as external.
- Alternatives: observations as "assistant" messages (the model may take
  them as its own text and invent observations; a failure leaves half a
  turn); `add()` does not open a turn for text starting with
  "OBSERVATION:" (depends on message text, breaks silently if the prefix
  changes).
- Code: `memory.py` — `SlidingWindowBuffer.add_turn`; `agents/coder_agent.py` —
  `run_agent`

### DEC-058 `build_context()` is reused for every loop iteration
- Date: 2026-11-05 · Area: Memory / Coder Agent (Lab 1.3) · Status: accepted (refined by DEC-077)
- Basis: Required (C1.2: retrieval before every LLM call); how — Preferred
- Context: a task makes up to 10 LLM calls (C1.4), each needing retrieval
  queried by the task (DEC-050) and the messages of the turn in progress.
  The task's outcome memory must not come back while the task is in the
  window (DEC-049).
- Decision: `build_context()` gains two parameters, the system prompt (the
  ReACT prompt) and the messages of the current turn, and is called before
  every LLM call. Order: system (prompt + memories) -> window -> task ->
  current turn. Outcome memories are stored with an id derived from the
  task ("outcome-" + hash of the task), so the tasks in the window give the
  ids to exclude.
- Why: one place for retrieval, exclusion and the DEC-025 evidence log;
  repeating a task updates its outcome memory instead of duplicating it
  (as DEC-011 does for messages).
- Alternatives: build the context once per task and reuse it (C1.2 Not
  Yet: no retrieval before every call); a new function in the Coder
  (duplicates exclusion and logging, the copies drift).
- Code: `memory.py` — `build_context`, `outcome_memory_id`,
  `SlidingWindowBuffer.get_turn_starts`, `_retrieve_memories`

### DEC-059 The outcome memory holds task, status, main file and explanation
- Date: 2026-11-05 · Area: Memory (Lab 1.3) · Status: accepted
- Basis: Preferred (C1.2 is met either way)
- Context: DEC-049 stores one "task + final answer" memory per task that
  ends with FINAL ANSWER; its text must be chosen.
- Decision: the memory text is "Task / Status / Main file / Explanation",
  without the code.
- Why: a short text keeps the embedding focused on what the task asked;
  the status keeps a failed task from being recalled as done; the code is
  in the file and the agent can read it with `read_file`.
- Alternatives: include the code (all-MiniLM-L6-v2 only embeds about the
  first 256 tokens, so the code would dominate and retrieval by task
  would degrade).
- Code: `memory.py` — `store_outcome`

### DEC-060 Text ReACT format, parsed into Pydantic steps
- Date: 2026-11-05 · Area: Coder Agent (Lab 1.3) · Status: superseded by DEC-069
- Basis: Required (C1.4: plan and action/observation record; C4.6: LLM
  output validated before use); the format — Preferred
- Context: the loop needs the LLM to say, at each step, what it thinks and
  either which tool to call or that it has finished. The lab uses a text
  format and returns an ad-hoc dict.
- Decision:
  - Each response follows the lab's text format: `Thought:` then either
    `Action:` + `Action Input:` (a JSON object) or `FINAL ANSWER:` with a
    JSON `{"main_file": str | null, "explanation": str}` (DEC-052,
    DEC-056). The first Thought states the plan (DEC-053).
  - The parser returns a Pydantic model: `ToolStep` (thought, action
    restricted to the known tools, action_input as an object) or
    `FinalStep` (thought, main_file, non-empty explanation).
  - Parse errors: a response with both `Action` and `FINAL ANSWER`; any
    text after a self-written `OBSERVATION:` is cut off first; an empty
    response. Every parse error goes back to the LLM as
    `OBSERVATION: Error: ...` and counts as an iteration. API errors still
    propagate (DEC-027) until retries arrive (C4.2).
- Why: the Thought is always in the text, which is the C1.4 evidence; the
  model never acts on unvalidated output; an action plus a final answer is
  a result claimed before the action ran (C1.5); an empty reply inside the
  loop gives the LLM a chance to recover, and the 10-iteration limit still
  ends the task (refines DEC-029 for the loop).
- Alternatives: native function calling with a `finish` tool (sturdier
  parsing, but the Thought becomes optional: weaker C1.4 evidence; moves
  away from the lab); a JSON-only response with `response_format` (not
  supported by every OpenRouter model).
- Code: `agents/coder_agent.py` — `ToolStep`, `FinalStep`, `ParseFailure`,
  `parse_llm_response`

### DEC-061 Tools are described in the prompt, generated from the schemas
- Date: 2026-11-05 · Area: Coder Agent (Lab 1.3) · Status: superseded by DEC-069
- Basis: Preferred
- Context: with the text format (DEC-060) the tool schemas are not sent
  through the API, so the prompt must tell the LLM which tools exist and
  their arguments.
- Decision: the ReACT prompt includes a tool list generated from
  `ALL_TOOL_SCHEMAS` (name, description, arguments). The schemas are not
  passed as `tools=` to the API.
- Why: one source of truth: changing a schema changes the prompt.
- Alternatives: tools written by hand in the prompt (text and schemas can
  drift, so the LLM sends arguments the wrappers reject); the lab's
  `tools=` with `tool_choice="none"` (sends unusable schemas on every call,
  extra tokens for C4.4; some OpenRouter models ignore or reject it).
- Code: `agents/coder_agent.py` — `_describe_tools`, `REACT_SYSTEM_PROMPT`

### DEC-062 `dispatch_tool` returns errors instead of raising
- Date: 2026-11-05 · Area: Tools (Lab 1.3) · Status: accepted (refined by DEC-076)
- Basis: Required (C4.6: invalid LLM output never reaches the tools)
- Context: the lab's `dispatch_tool` and the one in `agents/tools_demo.py`
  both raise `TypeError` when the arguments are not a JSON object (and the
  lab's also on missing or extra arguments). An exception in the middle of
  the loop ends the task instead of letting the LLM correct itself.
- Decision: `dispatch_tool(name, args)` lives in `tools/handlers.py`. It
  receives the already parsed arguments and returns an `Error: ...` string
  for an unknown tool or arguments that are not an object; missing or extra
  arguments are rejected by the Pydantic wrappers (DEC-042). It never
  raises.
- Why: the error goes back to the LLM as an observation and the loop goes
  on; the dispatcher belongs to the tool layer, so it survives the removal
  of `tools_demo.py` and other agents can reuse it.
- Alternatives: keep the lab's version (a `[1, 2]` argument crashes the
  agent).
- Code: `tools/handlers.py` — `dispatch_tool`

### DEC-063 Execution has a structured result underneath `exec_python`
- Date: 2026-11-05 · Area: Tools / Coder Agent (Lab 1.3) · Status: accepted
- Basis: Required (C1.5: result from real execution; C1.3: no regression
  of `exec_python`); how — Preferred
- Context: DEC-055 needs to know whether the last execution ended without
  error, but `exec_python` returns a text for the LLM.
- Decision: an internal function runs the script and returns a structured
  result (output text, exit code, timed out). `exec_python` calls it and
  returns the same text as before. The loop uses the structured result
  for the status and its text as `result`. Any `write_file` call after the
  last execution invalidates it, even a failed write.
- Why: the status comes from data, not from reading a message;
  `exec_python` and its Lab 1.2 tests do not change; invalidating on any
  write can only turn a success into `unverified`, never the opposite.
- Alternatives: infer the outcome from the text (a script printing
  "Error: ..." looks like a failure; breaks silently if the message
  changes); make `exec_python` return an object (breaks its contract and
  the Lab 1.2 tests; the LLM would get an object instead of text).
- Code: `tools/code_executor.py` — `ExecutionResult`, `run_python`,
  `exec_python`; `agents/coder_agent.py` — `run_agent`

### DEC-064 The whole Coder lives in `agents/coder_agent.py`
- Date: 2026-11-05 · Area: Coder Agent (Lab 1.3) · Status: accepted
- Basis: Preferred (C1.1 names `agents/coder_agent.py`)
- Context: DEC-051 left the internal organisation of the Coder to the
  technical phase.
- Decision:
  - `agents/coder_agent.py` holds `MODEL`, `MAX_ITERATIONS = 10`, the
    ReACT prompt and the tool description (DEC-061), the step and output
    models, `parse_llm_response()`, `run_agent(task, window)`, `chat()`
    and `main()`.
  - `chat(user_input, window)` wraps `run_agent()` and returns the
    explanation; with `max_iterations` it returns a fixed "stopped after
    10 iterations" message.
  - `main()` without arguments is the interactive session and shows
    status, explanation, main file and result; with one argument
    (`python -m agents.coder_agent "task"`) it runs that task and prints
    the whole output model as JSON.
- Why: one agent in the file the guide names; the one-task mode shows the
  C1.5 output in a real run. Splitting now is premature: the loop may
  change when the framework is chosen (DEC-047).
- Alternatives: a package `agents/coder/` with prompt, parsing and models
  modules (the guide names a single file; premature split).
- Revisit when: another agent needs the parser or the models (Module 2/3).
- Code: `agents/coder_agent.py` — `chat`, `main`

### DEC-065 `CoderResult` is the Pydantic output of a whole task
- Date: 2026-11-05 · Area: Coder Agent (Lab 1.3) · Status: accepted (refined by DEC-078)
- Basis: Required (C1.5: `code`, `explanation`, `plan`, `result`; C1.4:
  plan and action/observation record); the extra fields — Preferred
- Context: the lab's `AgentResult` (answer, iterations, tool_calls,
  stopped_early) has none of the C1.5 fields. The per-execution result of
  DEC-063 is internal and is not the task output.
- Decision: `run_agent()` returns a `CoderResult` with `status` (DEC-055,
  DEC-056), `plan` (DEC-053), `code` (read from disk, DEC-052),
  `explanation`, `result` (text of the last valid execution, DEC-063),
  `main_file`, `iterations` and `steps` (thought, action, action input and
  observation of each iteration). It lives in `agents/coder_agent.py`.
- Why: one model holds the C1.5 fields and the C1.4 record, and the status
  lets later agents tell success from failure without reading text.
- Alternatives: a separate module only for the Coder's models (premature
  until a second agent uses them, DEC-064).
- Revisit when: Module 2 defines the shared state (C2.2); the model moves
  there.
- Code: `orchestration/state.py` — `StepRecord`, `CoderResult` (moved from
  `agents/coder_agent.py` in Lab 2.2, DEC-107)

### DEC-066 The smoke test is a pytest test that runs only with `--run-llm`
- Date: 2026-11-05 · Area: Tests (Lab 1.3) · Status: accepted
- Basis: Required (C1.6: automated smoke test); the opt-in flag —
  Preferred
- Context: the smoke test (DEC-054) calls the real LLM: it costs tokens and
  needs the key. The lab's `--run-llm` flag is defined inside the test
  file, where pytest does not register it. For Module 1 the smoke test is
  the only new test (the mocked Coder tests are deferred, at the latest to
  C4.7).
- Decision: `tests/test_smoke.py` is a pytest test marked as an LLM test.
  `tests/conftest.py` registers `--run-llm`; without it, LLM tests are
  skipped. Run with `pytest tests/test_smoke.py --run-llm`.
- Why: `pytest tests/` stays free and fast; the smoke test gives a clear
  PASS/FAIL as C1.6 evidence.
- Alternatives: skip only when there is no key (with the key in `.env` it
  would run, and cost, on every `pytest`); a script like
  `tests/test_memory.py` (weaker evidence of an "automated smoke test").
- Code: `tests/conftest.py`; `tests/test_smoke.py`

### DEC-067 `dispatch_tool` returns a `ToolOutcome`, not a bare string
- Date: 2026-11-05 · Area: Tools (Lab 1.3) · Status: accepted
- Basis: Preferred (refines DEC-062 and DEC-063)
- Context: DEC-062 makes `dispatch_tool` the single entry point for tool
  calls and DEC-063 needs the loop to see the structured result of each
  execution; a dispatcher that returns only text hides that result.
- Decision: `dispatch_tool` returns `ToolOutcome(observation: str,
  execution: ExecutionResult | None)`. `execution` is set only when
  `exec_python` actually ran the script, after validating its arguments
  with the same `ExecPythonArgs` as the wrapper.
- Why: one entry point and one validation for every tool call; the loop
  gets the DEC-063 result without special-casing `exec_python` or
  validating twice.
- Alternatives: return `str` and let the loop call `run_python` itself for
  `exec_python` (two code paths, arguments validated twice, the paths can
  drift); return a tuple (untyped, against the Pydantic-everywhere rule).
- Code: `tools/handlers.py` — `ToolOutcome`, `dispatch_tool`

### DEC-068 LangGraph is the agent framework, from Module 1
- Date: 2026-11-07 · Area: Framework (Module 1) · Status: accepted (refined by DEC-069)
- Basis: Required (C1.1: the README names and explains the chosen framework;
  C2.3: PM and Coder in one orchestration graph); the choice of LangGraph —
  Preferred
- Context: DEC-047 left the ReACT loop in plain Python and the framework
  open until the Module 1 submission. The README cannot name a framework the
  code does not use, and a later switch must be justified (C2.6).
- Decision: use LangGraph for every agent and for the orchestration. In
  Module 1 the Coder's ReACT loop (`run_agent`) becomes a LangGraph graph;
  the prompt, parser, Pydantic models, tools and memory stay as they are and
  are called from the nodes.
- Why:
  - Explicit, deterministic control flow: nodes and conditional edges
    decide what runs next, so the limits the assessor forces (10 ReACT
    iterations, C1.4; QA→Coder loop limit, C3.3; task order, C2.4) are
    conditions in the graph, not left to the LLM.
  - Typed shared state is native (`StateGraph` over a TypedDict or Pydantic
    model), as C2.2 and C2.3 ask.
  - Nodes are plain Python functions, so the validated text format
    (DEC-060), the tool confinement and validation (DEC-036, DEC-042,
    DEC-062) and the status rules (DEC-052, DEC-055) are kept: no LLM output
    reaches a tool without Pydantic validation (C1.3, C4.6).
  - Per-call retries and the circuit breaker (C4.2, C4.3) stay in our code,
    without fighting a framework's internal retries.
  - LangSmith, one of the C4.1 options, traces the graph's nodes; our
    OpenAI-SDK LLM calls still need wrapping to report tokens.
  - Trade-off: more code than CrewAI to define roles, and no free-form
    agent conversation (AutoGen's strength); our flow PM → Coder → QA is a
    fixed sequence with bounded loops, so neither is needed.
- Alternatives: AutoGen and CrewAI (their own agent classes, prompts and
  tool calling clash with DEC-060, DEC-055 and DEC-052, so the Coder would
  be rewritten; turn-taking is driven by a group chat manager or a crew
  process, which makes the forced limits harder to guarantee); name
  LangGraph in the README and keep the plain loop until Module 2 (no work
  now, but the README would not match the code, risking C1.1).
- Code: `agents/coder_agent.py` — `build_agent` (through DEC-069); `requirements.txt`

### DEC-069 The Coder is a LangChain `create_agent` with native tool calling
- Date: 2026-11-07 · Area: Coder Agent (Module 1) · Status: accepted
- Basis: Required (C1.4: bounded action/observation loop with a plan and a
  record; C4.6: every LLM output validated before it is acted on); the
  agent factory and tool calling — Preferred (refines DEC-068)
- Context: DEC-068 chose LangGraph and first planned custom nodes around
  the text ReACT format (DEC-060). LangGraph's `create_react_agent` is
  deprecated; its successor is `langchain.agents.create_agent`, a LangGraph
  graph customized with middleware. C1.4 says hidden model reasoning is not
  required, so the text format is our choice, not a requirement.
- Decision:
  - The Coder loop is built with `create_agent`, using the model's native
    tool calling: tools are passed as schemas, not described in the prompt,
    and the text `Thought` / `Action` / `Action Input` / `FINAL ANSWER`
    format and its parser are dropped.
  - Kept: `code` read from disk (DEC-052), statuses and `result` from a
    real execution (DEC-055, DEC-056), two-tier memory, workspace
    confinement, the subprocess with timeout, `run_agent`, `chat()` and
    `main()` signatures.
  - The behavior the default agent gets wrong for us is overridden:
    DEC-071 (plan), DEC-072 (thought), DEC-073 (explicit finish), DEC-074
    (one tool per iteration).
- Why: the standard LangGraph agent, which the assessor recognizes; the
  10-call limit, the validated final answer and per-call retries with
  jitter (C4.2) come built in; token usage reaches LangSmith traces (C4.1,
  C4.4); fake chat models make the mocked agent tests easier (C4.7). Doing
  it now, with one agent, is cheaper than after the PM and QA exist.
- Alternatives: custom LangGraph nodes around our text parser (DEC-068's
  first plan: least change, but none of the built-ins, and a later move
  rewrites three agents); custom nodes with tool calling (full control,
  but the loop, limit and retries are written by hand); deprecated
  `create_react_agent`.
- Revisit when: the technical spike shows that the limit, the explicit
  finish or the argument validation cannot be guaranteed with middleware;
  then fall back to custom nodes with tool calling.
- Code: `agents/coder_agent.py` — `build_agent`, `run_agent`

### DEC-070 The iteration limit counts tool-loop model calls, not the plan
- Date: 2026-11-07 · Area: Coder Agent (Module 1) · Status: accepted
- Basis: Required (C1.4: a loop counter stops execution after at most 10
  iterations); what counts — Preferred
- Context: the plan step (DEC-071) adds one LLM call before the loop.
- Decision: an iteration is one model call inside the action/observation
  loop (with its tool call or its error observation); at most 10. The plan
  call is outside the loop and does not count, so a task makes at most
  1 + 10 LLM calls.
- Why: C1.4 bounds the action/observation loop; counting the plan would
  leave 9 iterations for the work.
- Alternatives: count the plan as iteration 1 (the README and the limit
  would disagree with "10 iterations of the loop").
- Code: `agents/coder_agent.py` — `MAX_ITERATIONS`, `make_plan`, `build_agent`

### DEC-071 The plan comes from a structured planning step before the loop
- Date: 2026-11-07 · Area: Coder Agent (Module 1) · Status: accepted
- Basis: Required (C1.4: concise plan); the planning step — Preferred
  (supersedes DEC-053)
- Context: with tool calling the model may call a tool without writing any
  text, so "plan = first Thought" (DEC-053) is no longer guaranteed.
- Decision: before the loop, one LLM call returns a Pydantic-validated
  `Plan` (a list of steps). The plan goes into the loop's context and into
  `CoderResult.plan`. It runs for every message, questions included.
- Why: the plan always exists and is validated (C1.4, C4.6), and the loop
  follows the plan it was given.
- Alternatives: ask in the prompt for a plan in the first response's text
  (cheaper, but the plan may be missing); count on the first tool call's
  thought (DEC-072; a reason for one action, not a plan).
- Code: `agents/coder_agent.py` — `Plan`, `PLAN_SYSTEM_PROMPT`, `make_plan`,
  `inject_context`

### DEC-072 Every tool call carries a required `thought`
- Date: 2026-11-07 · Area: Coder Agent (Module 1) · Status: accepted
- Basis: Preferred (C1.4: action/observation record; hidden reasoning is
  not required)
- Context: with tool calling the reasoning text before an action is
  optional, and models often leave it empty; the ReACT Thought → Action →
  Observation record would have gaps.
- Decision: every tool the model sees, `finish` included, has a required
  `thought` argument (why this action, given the last observation). It is
  validated with the other arguments, stored in `StepRecord.thought` and
  removed before the tool runs.
- Why: a complete ReACT record without spending iterations on
  "missing thought" errors.
- Alternatives: ask for it in the prompt without requiring it (gaps in the
  record); require non-empty message text (format errors cost iterations).
- Note (implementation): the `thought` of each call goes to `StepRecord.thought`; it is
  dropped before `dispatch_tool` in the tool function itself.
- Code: `tools/agent_tools.py` — `CALL_MODELS`, `_parameters_with_thought`;
  `agents/coder_agent.py` — `Finish`, `result_from_messages`

### DEC-073 The agent ends only through `finish`; plain text is an error
- Date: 2026-11-07 · Area: Coder Agent (Module 1) · Status: accepted
- Basis: Required (C1.5: no success claimed without execution; C1.2: the
  recall test's questions still end as `answered`); the explicit finish —
  Preferred (refines DEC-052, DEC-056)
- Context: by default a tool-calling agent stops when the model answers
  with text and no tool call. For a Coder this ends tasks halfway or with
  code pasted in the chat but never written.
- Decision:
  - The only way to end is the `finish` tool with `main_file` (or null)
    and `explanation`, validated with Pydantic. `finish` with null ends as
    `answered` (DEC-056); with a file, the status follows DEC-055.
  - A response with text and no tool call gets back an error observation
    (call a tool, or `finish`) and counts as an iteration.
- Why: tasks never end implicitly; questions still end as `answered`, at
  the cost of an extra iteration when the model first answers in text.
- Alternatives: plain text ends as `answered` (natural for questions, but
  coding tasks can end unfinished); plain text ends as `answered` only if
  no tool was called yet (still misses code pasted in the chat at once).
- Note (implementation): `ToolStrategy` names the tool after the class, so the model
  sees `Finish`, not `finish`. A valid `Finish` leaves a `ToolMessage` after
  the model's response, so `require_tool_call` checks the last AI message,
  not the last message. On the 10th model call no nudge is sent: the model
  would never read it (the limit ends the run).
- Code: `agents/coder_agent.py` — `Finish`, `NUDGE_MESSAGE`, `require_tool_call`

### DEC-074 One tool call per iteration
- Date: 2026-11-07 · Area: Coder Agent (Module 1) · Status: accepted
- Basis: Preferred (C1.4: action/observation record and loop counter)
- Context: tool-calling models can return several tool calls in one
  response, and the default agent runs them in parallel.
- Decision: parallel tool calls are disabled; one model call is one action
  and one observation.
- Why: the record and the counter stay one-to-one, and a write never races
  an execution (DEC-055's "no write after the run").
- Alternatives: allow several calls per iteration (fewer iterations, but
  ordering and the "last valid run" become ambiguous).
- Code: `agents/coder_agent.py` — `inject_context`

### DEC-075 LLM through `ChatOpenAI` pointed at OpenRouter
- Date: 2026-11-07 · Area: LLM client (Module 1) · Status: accepted
- Basis: Preferred (refines DEC-002)
- Context: `create_agent` (DEC-069) needs a LangChain chat model, not the
  raw OpenAI SDK client.
- Decision: `llm_client.get_client()` is replaced by
  `get_chat_model(model)`, which returns a `ChatOpenAI` with OpenRouter's
  base URL and `OPENROUTER_API_KEY`. "OpenAI" is the API protocol that
  OpenRouter exposes for every model; `LLM_MODEL` can be any OpenRouter
  model that supports tool calling. Dependencies: `langchain>=1.4,<2`,
  `langchain-openai>=1.7,<2`, `langgraph>=1.2,<2`; `openai` is no longer a
  direct dependency. Retries stay at `ChatOpenAI`'s defaults until C4.2
  (Module 4, `ModelRetryMiddleware` with jitter).
- Why: one place configures the provider; the model is a parameter, so
  agents can use different models (C4.5).
- Alternatives: a provider-specific LangChain package per model (several
  configurations for the same OpenRouter endpoint).
- Code: `llm_client.py` — `get_chat_model`; `requirements.txt`

### DEC-076 LangChain tool adapter in `tools/agent_tools.py`
- Date: 2026-11-07 · Area: Tools (Module 1) · Status: accepted
- Basis: Required (C4.6: invalid tool arguments never run); the adapter —
  Preferred (refines DEC-062)
- Context: `create_agent` takes LangChain tool objects. Our tools are
  three layers: implementations (`file_io.py`, `code_executor.py`),
  validation and dispatch (`handlers.py`), and now what the model sees.
  LangChain's own validation errors repeat every argument, including whole
  file contents, and an exception raised inside a tool function stops the
  whole agent.
- Decision:
  - `tools/agent_tools.py` defines one call model per tool: the strict
    `ReadFileArgs`, `WriteFileArgs`, `ExecPythonArgs` plus a required
    `thought` (DEC-072); descriptions come from `tools/schemas.py`
    (unchanged lab schemas).
  - Each LangChain tool (`response_format="content_and_artifact"`) drops
    `thought` and calls `dispatch_tool`; the observation is the content and
    the `ExecutionResult` the artifact (DEC-063, DEC-067).
  - A `wrap_tool_call` middleware validates the arguments with the call
    models before LangChain runs the tool; invalid calls get our short
    "Error: invalid arguments ..." message and never run. It also logs one
    line per iteration.
- Why: implementations and `handlers.py` stay framework-free; the adapter
  is the only LangChain-specific tool code and can be reused by QA
  (Module 3); `dispatch_tool` never raising keeps the agent alive.
- Alternatives: adapter inside `handlers.py` (mixes the framework into the
  validation layer); in `coder_agent.py` (QA could not reuse it);
  LangChain's validation errors as they are (long messages, wasted tokens).
- Note (implementation): the tools are declared with the lab's JSON schema plus
  `thought`, so LangChain does not validate them at all and only our
  messages reach the model; `dispatch_tool` validates again. The
  per-iteration log line is written by `require_tool_call`, the only hook
  that sees every model response (text answers and `Finish` included).
  `tools/agent_tools.py` is not exported from `tools/__init__.py`, so
  `import tools` does not load LangChain.
- Code: `tools/agent_tools.py` — `check_tool_call`, `AGENT_TOOLS`;
  `agents/coder_agent.py` — `validate_tool_call`

### DEC-077 Memory and window are injected on every model call
- Date: 2026-11-07 · Area: Memory / Coder Agent (Module 1) · Status: accepted
- Basis: Required (C1.2: Chroma queried before each LLM call, retrieved
  context injected; window of the last N turns); how — Preferred (refines
  DEC-057, DEC-058)
- Context: inside `create_agent` the model calls happen in the framework's
  loop; the agent state only holds the current task's messages.
- Decision:
  - A `wrap_model_call` middleware calls `build_context()` before every
    model call: the system message gets the Coder prompt, the plan
    (DEC-071) and the retrieved memories, and the window's messages go
    before the task. The plan call also uses `build_context()`.
    `memory.py` does not change.
  - The window stores each whole turn (DEC-057) in OpenAI message format,
    tool calls included (`convert_to_openai_messages` /
    `convert_to_messages`, checked to round-trip).
  - The "Model call limits exceeded" message LangChain adds at the limit
    is left out of the window: the model never wrote it.
- Why: the C1.2 behavior is unchanged and visible in the same log line
  (DEC-025); memory keeps one implementation.
- Alternatives: a `before_model` hook that writes memories into the agent
  state (they would pile up in the turn); LangGraph's own store or
  checkpointer (C1.2 requires Chroma and our window).
- Note (implementation): the per-task data (task, window, plan) reaches the middleware
  as the agent's run-time `context`. The limit message only appears when the
  limit is reached with tool calls; with text answers the run simply ends
  after the 10th call.
- Code: `agents/coder_agent.py` — `CoderContext`, `inject_context`,
  `make_plan`, `_drop_limit_message`, `run_agent`

### DEC-078 `CoderResult` is computed from the final messages
- Date: 2026-11-07 · Area: Coder Agent (Module 1) · Status: accepted
- Basis: Required (C1.4 record, C1.5 result from a real execution); how —
  Preferred (refines DEC-065)
- Context: `create_agent` returns the whole conversation and, when
  `finish` was called, `structured_response`. The spike kept the last
  execution in a custom state updated by a middleware during the run.
- Decision: one function reads the final messages after the run: one
  `StepRecord` per AI message (thought and action from the call
  arguments, observation from the answering tool message, nudges as
  errors); the last valid execution is the artifact of the last
  `exec_python` with no `write_file` after it (DEC-055); `finish` present
  gives the DEC-055/056 status, absent gives `max_iterations`; `code` is
  read from disk (DEC-052); `plan` comes from the planning step.
- Why: one middleware fewer; all the status logic in one pure function
  that is easy to test with invented messages (C4.7).
- Alternatives: custom agent state updated by a `wrap_tool_call`
  middleware (logic spread across hooks).
- Note (implementation): one `StepRecord` per tool call (one per model call, since
  parallel calls are off) or per text answer; the accepted `Finish` has no
  observation.
- Code: `agents/coder_agent.py` — `result_from_messages`, `StepRecord`

### DEC-079 Middleware order; the call limit goes last
- Date: 2026-11-07 · Area: Coder Agent (Module 1) · Status: accepted
- Basis: Required (C1.4: the loop stops after at most 10 iterations, with
  no crash under the assessor's probe)
- Context: the spike showed that `ModelCallLimitMiddleware` counts calls
  in its own `after_model`, and `after_model` hooks run in reverse list
  order. With the limit first, `require_tool_call` (DEC-073) jumped back
  to the model before the count: a model answering only text looped
  until `GraphRecursionError`.
- Decision: middleware order `[inject_context, validate_tool_call,
  require_tool_call, ModelCallLimitMiddleware(run_limit=10,
  exit_behavior="end")]`, with a comment in the code; `recursion_limit` is
  set above what 10 iterations need, only as a safety net.
- Why: the limit counts every model call, nudges included, and ends
  cleanly.
- Alternatives: our own counter middleware (duplicates the built-in one).
- Code: `agents/coder_agent.py` — `build_agent`, `RECURSION_LIMIT`

### DEC-080 A declared main file counts only if this task wrote or ran it
- Date: 2026-11-07 · Area: Coder Agent (Module 1) · Status: accepted
- Basis: Preferred (refines DEC-056; C1.5: statuses from facts, not from
  the model's claim)
- Context: in a real session, a question about a file from an earlier
  task ("what did the file you just wrote print?") ended as `unverified`:
  the model declared that file as `main_file` in `Finish` although it
  wrote nothing in this task. Clearer wording in the prompt and in
  `Finish` did not stop it (`gpt-4.1-mini`, 2 of 2 runs).
- Decision: the declared `main_file` counts as this task's deliverable
  only if this task called `write_file` or `exec_python` on that same path
  (compared after resolving it in the workspace) and the call was not
  rejected by validation.
  - Not touched and the file exists: treated as null; the task ends as
    `answered` (`main_file`, `code` and `result` empty) and one INFO line
    records it. The model referred to an earlier file; this task
    delivered text, not code.
  - Not touched and the file does not exist (or is outside the
    workspace): it stays declared and the task ends as `unverified`
    (DEC-052, DEC-055): the model claimed a deliverable that does not
    exist.
- Why: statuses describe the evidence this task produced, not the kind of
  request, which the system does not classify (DEC-056). `answered`
  means "no code delivered in this task", so a question about an earlier
  file is not shown as a failed coding task; a declared file that does
  not exist is a false claim and stays flagged as `unverified`. Counting
  a run of the file keeps "check whether greet.py works" (run it, change
  nothing) as `success`, not `answered`.
- Alternatives: keep `unverified` for every untouched file (consistent
  with "not checked", but questions about earlier files look like failed
  tasks); `answered` also for a missing file (one-line rule, but hides a
  false claim); stronger prompt only (already failed once, no guarantee);
  count only writes (a task that only runs an existing file would end as
  `answered`).
- Code: `agents/coder_agent.py` — `_touched_paths`, `result_from_messages`

### DEC-081 The PM creates 2 to 8 tasks, as few as the requirement allows
- Date: 2026-11-09 · Area: PM Agent (Lab 2.1) · Status: accepted
- Basis: Required (C2.1: at least two tasks for the API task; C2.4: at most
  eight); "as few as possible" — Preferred
- Context: the lab asks for 2–4 tasks. Each task is solved by the Coder
  within 10 ReACT iterations (C1.4), so a large requirement squeezed into
  four tasks gives tasks too big for one run.
- Decision: the PM is asked for between 2 and 8 tasks and told to use the
  fewest that keep each task small enough for one Coder run.
- Why: 2 and 8 are the bounds the rubric checks; asking for few tasks keeps
  the run short and the handoff simple for small requirements.
- Alternatives: 2–4 as the lab (task size grows with the requirement);
  a fixed number (does not fit both a two-endpoint API and a larger app).
- Code: `agents/pm_agent.py` — `MIN_TASKS`, `MAX_TASKS`, `TASKS_SYSTEM_PROMPT`, `TaskListBase`

### DEC-082 More than 8 tasks are consolidated deterministically
- Date: 2026-11-09 · Area: PM Agent (Lab 2.1) · Status: accepted
- Basis: Required (C2.4: consolidate to at most eight without losing
  requirement coverage); deterministic merge — Preferred
- Context: the LLM may ignore the 8-task limit, and the assessor forces
  inputs that yield more than eight tasks. Deleting the excess is Not Yet.
- Decision: if the task list has more than 8 tasks, consecutive tasks are
  merged in code until 8 remain. A merged task joins the descriptions and
  acceptance criteria of its sources, covers all their spec criteria
  (DEC-083) and records them in `merged_from`. Order is preserved.
- Why: coverage is guaranteed by construction, it is testable without an
  LLM, and merging neighbours keeps dependency order.
- Alternatives: LLM merge with a coverage check and the deterministic merge
  as fallback (more natural tasks, more failure modes; candidate `IMP`);
  keep the first 8 (loses requirements, Not Yet).
- Code: `agents/pm_agent.py` — `consolidate_tasks`, `_merge`

### DEC-083 Structured spec with markdown details and criterion coverage
- Date: 2026-11-09 · Area: PM Agent (Lab 2.1) · Status: accepted
- Basis: Required (C2.1: name, description, acceptance criteria, tasks;
  C1.3/C4.6: Pydantic validation); `details` and coverage check — Preferred
- Context: the lab's spec is free markdown with five sections; C2.1 calls a
  prose-only spec Not Yet. C2.4 asks for a requirement mapping after
  consolidation.
- Decision: the spec is a Pydantic model with `name`, `description`,
  `acceptance_criteria` (each with an ID such as `REQ-1`; prefix `REQ-`
  so it never clashes with the `AC-<n>.<m>-<k>` IDs of our own specs), `tasks` and
  `details` (markdown with the lab's five sections). Each task lists the
  spec criteria it covers; validation fails if any spec criterion is not
  covered by a task.
- Why: the structured fields meet C2.1 and are machine-checkable; `details`
  keeps the lab's spec-first reasoning; the criterion IDs give the
  requirement mapping that C2.1 and C2.4 assessors look for.
- Alternatives: structured fields only (loses the lab's richer spec for the
  Coder); markdown only (Not Yet in C2.1).
- Code: `orchestration/state.py` — `SpecCriterion`, `ProjectSpec`; `agents/pm_agent.py` —
  `SpecDraft`, `_build_spec`, `_task_list_schema`

### DEC-084 Several tasks may target the same file
- Date: 2026-11-09 · Area: PM Agent (Lab 2.1) · Status: accepted
- Basis: Preferred
- Context: the lab requires a unique `file_path` per task. The graded API
  task is naturally one Flask/FastAPI file, and C2.1 still asks for at
  least two tasks.
- Decision: tasks do not need unique files; a later task may extend a file
  an earlier task created. The Coder reads existing files before editing.
- Why: avoids splitting small programs into artificial modules or adding
  filler tasks just to reach two files; what is graded is that the
  generated API works (C2.5).
- Alternatives: unique file per task as the lab (forces artificial splits).
- Code: `orchestration/state.py` — `TaskSpec.files`; `agents/pm_agent.py` —
  `TASKS_SYSTEM_PROMPT`

### DEC-085 Task priority is the execution order
- Date: 2026-11-09 · Area: PM Agent (Lab 2.1) · Status: accepted
- Basis: Required (C2.3: the handoff carries priority; C2.4: tasks run in
  order); integer meaning — Preferred
- Context: the lab's `CodingTask` has no priority.
- Decision: `priority` is an integer from 1 to n equal to the task's
  position in the execution order (1 runs first). Consolidation (DEC-082)
  renumbers it.
- Why: priority can never contradict the order the Coder follows.
- Alternatives: `high`/`medium`/`low` next to the order (a second field
  that changes nothing and can disagree with the order).
- Code: `agents/pm_agent.py` — `_build_tasks`, `_merge`

### DEC-086 The PM uses a more capable model than the Coder
- Date: 2026-11-09 · Area: PM Agent (Lab 2.1) · Status: accepted
- Basis: Required (C4.5: large model for the PM, small/fast for Coder and
  QA); doing it now — Preferred
- Context: every agent uses `LLM_MODEL` (`openai/gpt-4.1-mini`). The PM
  reasons once per run over the whole scope; the Coder calls the model up
  to 10 times per task.
- Decision: the PM reads its own model id from an environment variable,
  defaulting to a more capable model than the Coder's. The exact model is
  set in the technical phase.
- Why: a better decomposition helps every later step at the cost of only
  two calls per run; doing it now avoids touching the PM again in Module 4.
- Alternatives: same model for all agents until Module 4 (rework later).
- Code: `agents/pm_agent.py` — `DEFAULT_PM_MODEL`, `make_pm_node`

### DEC-087 The PM is a fixed two-call pipeline; failures end in state
- Date: 2026-11-09 · Area: PM Agent (Lab 2.1) · Status: accepted
- Basis: two calls and failing into state — Required (lab); printing the
  error — Preferred; no retry beyond the client's — Provisional
- Context: the PM has no tools and nothing to decide between steps, so a
  ReACT loop adds nothing. A node that raises crashes the graph.
- Decision: the PM makes one call for the spec and one for the tasks, never
  writes files or runs code. Any failure is caught: the error goes to
  `state.error` and the progress log, is printed and logged at ERROR, the
  graph reaches END and nothing is reported as success.
- Why: spec-first gives better decompositions (lab); the error is visible
  for debugging without crashing the run.
- Alternatives: a ReACT PM (no tools to act with); raising (crashes the
  graph).
- Revisit when: Module 4 adds per-call retries with backoff and jitter
  (C4.2). Invalid outputs are handled by DEC-088.
- Code: `agents/pm_agent.py` — `make_pm_node`; `orchestration/graph.py`

### DEC-088 An invalid PM output gets one corrective retry
- Date: 2026-11-09 · Area: PM Agent (Lab 2.1) · Status: accepted
- Basis: Required (C1.3/C4.6: invalid output never reaches later steps);
  one corrective retry — Preferred
- Context: an LLM output can fail Pydantic validation or the coverage check
  of DEC-083. Failing at once would end a whole run over a formatting slip,
  and the assessor runs the system several times.
- Decision: when a PM call returns an output that fails validation, the PM
  calls the model once more with the validation error so it can fix it. If
  the second output is also invalid, the run fails as in DEC-087 with the
  validation error. Each PM step makes at most two calls (four per run).
- Why: recovers from most format slips at a bounded cost; the message the
  model sees is the same one shown when debugging.
- Alternatives: fail at once (fragile); up to three corrections (little gain
  over one; a second failure usually means the requirement was
  misunderstood).
- Code: `agents/llm_helpers.py` — `structured_call`

### DEC-089 The shared state is a Pydantic model
- Date: 2026-11-09 · Area: Orchestration (Lab 2.1) · Status: accepted
- Basis: Required (C2.2: Pydantic or TypedDict schema); Pydantic —
  Preferred
- Context: the lab's state is a TypedDict with tasks as plain dicts. LLM
  outputs must be validated with Pydantic anyway (C1.3, C4.6).
- Decision: `ProjectState` and the models it holds are Pydantic models;
  the LangGraph graph is built on `ProjectState`.
- Why: one schema validates the LLM output, defines the state and
  serialises the handoff (`model_dump_json()`, C2.3); unlike a TypedDict,
  invalid values (e.g. an unknown task status) are rejected at run time
  when the next node reads the state.
- Alternatives: TypedDict as the lab (no run-time validation and a second,
  parallel schema next to the Pydantic ones).
- Code: `orchestration/state.py` — `ProjectState`; `orchestration/graph.py` —
  `build_graph`

### DEC-090 State fields: spec as planned, tasks as executed
- Date: 2026-11-09 · Area: Orchestration (Lab 2.1) · Status: accepted
- Basis: Required (C2.1: spec with name, description, acceptance criteria,
  tasks; C2.2: requirement, spec, task list, per-task status, accumulated
  code; C2.3: task ID, description, acceptance criteria, priority); the
  split — Preferred
- Context: C2.1 wants the tasks inside the spec, and C2.2 wants a task list
  whose status changes as the Coder works.
- Decision: `ProjectState` holds `requirement`, `spec` (`ProjectSpec`:
  name, description, markdown `details`, criteria with IDs, tasks — what the
  PM decided, never changed afterwards), `tasks` (the same tasks plus
  `status`, the handoff the Coder updates), `code` (path → content,
  written by the Coder from Lab 2.3), `progress` (log appended through an
  `operator.add` reducer) and `error`. Each task has `task_id`, `title`,
  `description`, `acceptance_criteria`, `covers` (spec criterion IDs),
  `files`, `priority` and `merged_from`. Task IDs and priorities are
  assigned by code, not by the LLM.
- Why: keeps the plan apart from its execution, so the Coder updates one
  task without rewriting the spec; code-assigned IDs and priorities are
  always unique and ordered.
- Alternatives: a single task list inside `spec` carrying the status (every
  status change rewrites the whole spec).
- Code: `orchestration/state.py`; `agents/pm_agent.py` — `_build_spec`,
  `_build_tasks`

### DEC-091 PM structured calls use `create_agent` with `ToolStrategy`
- Date: 2026-11-09 · Area: PM Agent (Lab 2.1) · Status: accepted
- Basis: Preferred
- Context: DEC-088 asks for one corrective retry on invalid output.
  `ToolStrategy` already feeds validation errors back to the model, but has
  no retry cap. The coverage check (DEC-083) depends on the criterion IDs
  of each run.
- Decision: a shared helper in `agents/llm_helpers.py` runs one structured
  call as a `create_agent` with no tools, `ToolStrategy(schema)` and
  `ModelCallLimitMiddleware(run_limit=2)`. If the run ends without a
  structured response it raises with the last validation error. The task
  schema is built per run with a validator that checks coverage against
  that run's criterion IDs, so a coverage failure is retried like any
  other validation error.
- Why: same mechanism as the Coder (DEC-069); LangChain feeds the error
  back to the model.
- Alternatives: own helper around `with_structured_output(include_raw=True)`
  (explicit cap and plain-function check, but a second mechanism next to
  the Coder's); `.with_retry()` (retries without showing the error, so it
  corrects nothing).
- Code: `agents/llm_helpers.py` — `structured_call`; `agents/pm_agent.py` —
  `_task_list_schema`

### DEC-092 Consolidation splits tasks into 8 even consecutive groups
- Date: 2026-11-09 · Area: PM Agent (Lab 2.1) · Status: accepted
- Basis: Preferred (implements DEC-082)
- Context: DEC-082 merges consecutive tasks when the LLM returns more than
  eight despite the prompt.
- Decision: n > 8 tasks are split into 8 consecutive groups whose sizes
  differ by at most one, the larger groups first (11 → 2,2,2,1,1,1,1,1).
  A merged task joins titles, descriptions, acceptance criteria, covered
  criterion IDs and files of its group and lists the original task IDs in
  `merged_from`; IDs and priorities are renumbered. The task schema accepts
  more than eight tasks so the excess reaches consolidation instead of
  triggering a corrective retry.
- Why: predictable, pure and easy to test; keeps order and coverage.
- Alternatives: repeatedly merge the smallest neighbouring pair (more even
  sizes, less predictable).
- Code: `agents/pm_agent.py` — `consolidate_tasks`, `_group_sizes`, `_merge`

### DEC-093 PM model: `openai/gpt-4.1` through `PM_MODEL`
- Date: 2026-11-09 · Area: PM Agent (Lab 2.1) · Status: accepted
- Basis: Preferred (implements DEC-086)
- Context: the Coder uses `LLM_MODEL` (`openai/gpt-4.1-mini`).
- Decision: the PM reads `PM_MODEL`, default `openai/gpt-4.1`. The Coder
  keeps `LLM_MODEL`.
- Why: the larger model of the same family keeps the tool-calling behaviour
  already tested; the PM makes 2–4 calls per run, so the higher price per
  token weighs little.
- Alternatives: a Claude Sonnet model (named in the guide, but a provider
  change with no need); renaming `LLM_MODEL` to `CODER_MODEL` now (touches
  Module 1 for no gain; left for Module 4).
- Code: `agents/pm_agent.py` — `DEFAULT_PM_MODEL`, `make_pm_node`; `.env.example`

### DEC-094 Module layout for the PM and the graph
- Date: 2026-11-09 · Area: Orchestration (Lab 2.1) · Status: accepted
- Basis: Required (C1.1, C2.3: graph in `orchestration/`); the rest —
  Provisional
- Context: the lab has `state.py`, `graph.py` and `main.py` in its root.
  DEC-064 kept the Coder in one file until another agent needed shared
  code.
- Decision: `orchestration/state.py` (state and models, shared by PM and
  Coder), `orchestration/graph.py` (`build_graph()`), `agents/pm_agent.py`
  (the PM), `agents/llm_helpers.py` (the structured-call helper of DEC-091)
  and `main.py` in the repo root as the entry point
  (`python main.py "requirement"`), later the Docker `ENTRYPOINT`.
  `agents/coder_agent.py` is not touched.
- Why: the models belong to neither agent; a root `main.py` is the obvious
  way in for anyone cloning the repo (guide §1.3) and for the assessor.
- Alternatives: `python -m orchestration` via `__main__.py` (less
  discoverable); a generic `agents/utils.py` (tends to become a catch-all).
- Revisit when: more shared helpers appear (the helper module's name and
  split may change), or Lab 2.3 wires the Coder into the state (DEC-065).
- Code: `orchestration/state.py`, `orchestration/graph.py`, `agents/pm_agent.py`,
  `agents/llm_helpers.py`, `main.py`

### DEC-095 Task acceptance criteria are structured Given/When/Then
- Date: 2026-11-09 · Area: Orchestration (Lab 2.1) · Status: accepted
- Basis: Preferred
- Context: the spec has two levels of criteria. Spec criteria (with IDs)
  say what the whole requirement must meet and drive the coverage check
  (DEC-083); task criteria say how the code of one task is checked. In
  Module 3, QA writes pytest tests that check behaviour (C3.1).
- Decision: each task acceptance criterion is a `TaskCriterion` with
  non-empty `given`, `when` and `then` fields. Spec criteria stay plain
  statements with an ID.
- Why: a Given/When/Then check translates almost directly into a test for
  the Coder and QA; as fields, Pydantic enforces the form and a missing
  part triggers the corrective retry (DEC-088).
- Alternatives: a regular expression over free text (brittle with commas,
  case or extra "and"); Given/When/Then also for spec criteria (they state
  what, not how to check it); plain strings as the lab (vague checks).
- Code: `orchestration/state.py` — `TaskCriterion`, `TaskSpec`

### DEC-096 `main.py` defaults to the demo task and can print JSON
- Date: 2026-11-09 · Area: Orchestration (Lab 2.1) · Status: accepted
- Basis: Preferred
- Context: `main.py` is the entry point (DEC-094). The lab's `main.py` has a
  default requirement; in Module 4 `docker compose up` must run a task end
  to end (C4.8). C2.3 lists the serialised handoff as evidence.
- Decision: without arguments `main.py` runs the graded Module 2 demo
  requirement; `--json` prints the whole final state with
  `model_dump_json(indent=2)` instead of the readable summary. Exit codes:
  0 success, 1 the run ended with an error, 2 invalid usage (an empty or
  blank requirement is rejected before the graph runs).
- Why: one command with no input shows the graded behaviour; the JSON is
  the serialised handoff and helps debugging; separate exit codes tell a
  usage mistake from a failed run without reading the output, and a blank
  requirement never costs an LLM call (`NonEmptyStr` alone accepts spaces).
- Alternatives: require the requirement (one more step for the assessor and
  for Docker); readable summary only (no direct view of the serialised
  state).
- Code: `main.py` — `DEMO_REQUIREMENT`, `main`

### DEC-097 A failed task does not stop the remaining tasks
- Date: 2026-11-10 · Area: Coder node (Lab 2.2) · Status: accepted
- Basis: Preferred
- Context: the Coder runs the PM's tasks in order. A task can end without
  success (iteration limit, failed or unverified execution) while later
  tasks remain.
- Decision: the task is marked `failed` and the Coder moves on to the next
  task. The run is never reported as a success while any task failed.
- Why: more partial output for the user and for QA (Module 3), which can
  fix the failure; matches the lab (a failed artifact is a valid record and
  the loop goes on); keeps the honest reporting C3.3 will need.
- Alternatives: stop at the first failure (saves tokens, but leaves
  independent tasks unattempted).
- Revisit when: Module 3 adds the QA loop, if building on a broken task
  turns out to waste too many iterations.
- Code: `agents/coder_agent.py` — `make_coder_node`; `orchestration/graph.py` —
  `route_after_coder`

### DEC-098 Each task gets the project context and the files that exist
- Date: 2026-11-10 · Area: Coder node (Lab 2.2) · Status: accepted
- Basis: Preferred
- Context: a task alone does not say what earlier tasks built; pasting all
  the accumulated code makes every prompt grow with each task.
- Decision: the Coder receives the task (description, acceptance criteria,
  files) plus a short project context (the spec's name and description) and
  the list of files already written in the run; it opens them with
  `read_file` when it needs them.
- Why: the Coder knows where it stands without bloating the prompt; the
  tools already let it read any file of the workspace.
- Alternatives: only the task (blind to earlier work); all accumulated code
  in the prompt (cost grows with each task).
- Code: `agents/coder_agent.py` — `_task_prompt`, `make_coder_node`

### DEC-099 One memory window per graph run, shared by its tasks
- Date: 2026-11-10 · Area: Coder node (Lab 2.2) · Status: accepted
- Basis: window of the last N turns, observable — Required (C1.2); one
  window per run — Preferred
- Context: DEC-048 defined a session as one window across user messages and
  asked to revisit what the Coder keeps between PM tasks. Within a task the
  agent already keeps all its iterations in its own messages (one turn,
  DEC-057), so a fresh window per task would always be empty and never
  slide.
- Decision: a graph run is a Coder session (DEC-048): one window is created
  per run and shared by all its tasks, each task being one turn. Chroma is
  still queried before every LLM call; tasks that slide out of the window
  come back through it (DEC-049).
- Why: in task 2 the Coder remembers what it did in task 1; the window keeps
  its meaning and slides with more than N tasks (up to 8, C2.4).
- Alternatives: a fresh window per task (always empty, C1.2 evidence lost).
- Code: `agents/coder_agent.py` — `CoderRunContext`, `make_coder_node`

### DEC-100 Lab 2.2 builds the Coder node; PM→Coder wiring is Lab 2.3
- Date: 2026-11-10 · Area: Coder node (Lab 2.2) · Status: accepted
- Basis: Preferred
- Context: the lab tests the Coder in isolation from a task fixture and
  leaves the combined pipeline to Lab 2.3.
- Decision: Lab 2.2 builds and tests the Coder node from a prepared state
  with tasks already written; `main.py` and the full PM→Coder graph change
  in Lab 2.3.
- Why: same split as the course; each lab stays small and reviewable.
- Alternatives: wire PM→Coder now (bigger spec, overlaps Lab 2.3).
- Code: `orchestration/graph.py` — `build_coder_graph`; `tests/test_integration_coder.py`

### DEC-101 State records each task's status, the code on disk and its result
- Date: 2026-11-10 · Area: Coder node (Lab 2.2) · Status: superseded by DEC-178 in the team graph (kept for the Coder-only graph)
- Basis: status per task and accumulated code — Required (C2.2); full
  result per task — Preferred
- Context: C2.2 asks for per-task status and accumulated code in shared
  state; C1.5 asks the Coder's output to carry `code`, `explanation`, `plan`
  and a real `result`. `ProjectState.code` exists since Lab 2.1 but stays
  empty.
- Decision: each task goes `pending → done | failed` in one node step (an
  `in_progress` set inside the step would never be visible in the state,
  so it stays unused for now); it is `done` only when the Coder's result
  is `success`. `code` (file path →
  content) is updated with the files as they are on disk after each task,
  so a later task's edit replaces the earlier version. The full
  `CoderResult` of each task is kept in the state, one per task.
- Why: `code` shows where the project stands; the results show what
  happened in each task, prove C1.5 per task and are what QA reads in
  Module 3.
- Alternatives: only statuses and code (C1.5 evidence and the plan/result
  of each task are lost from the state); only results (no single view of
  the project's files).
- Code: `agents/coder_agent.py` — `make_coder_node`

### DEC-102 A fatal error ends the run; the node never retries a whole task
- Date: 2026-11-10 · Area: Coder node (Lab 2.2) · Status: accepted
- Basis: failing into state — Required (lab); no task-level retry —
  Required (C4.2: retries at the individual call)
- Context: `run_agent` lets API and memory errors propagate (DEC-027) once
  the client's own retries are spent. Invalid model output is already fed
  back inside the loop (DEC-073, DEC-076), bounded by 10 iterations.
- Decision: the Coder node catches any exception, writes it to
  `state.error` and the progress log, marks the current task `failed` and
  ends the run without reporting success, as the PM does (DEC-087). It
  does not retry the task.
- Why: a node that raises crashes the graph; retrying the whole task
  would redo the plan and every iteration, which C4.2 rules out.
- Alternatives: retry the task in the node (repeats the agent loop,
  against C4.2); keep going with the next task (the cause, e.g. the API
  down, would hit every task).
- Revisit when: Module 4 adds per-call retries with backoff and jitter
  (C4.2); the node stays as is.
- Code: `agents/coder_agent.py` — `make_coder_node`, `_with_task`

### DEC-103 The Coder self-loop is driven by task statuses
- Date: 2026-11-10 · Area: Coder node (Lab 2.2) · Status: accepted
- Basis: self-loop, one graph step per task — Required (lab); routing from
  statuses — Preferred
- Context: the lab adds `current_task_index` and `routing` to the state to
  pick the next task and leave the loop. Our tasks already carry a status
  (DEC-101) and come sorted by priority (DEC-085).
- Decision: the Coder node runs the first `pending` task (superseded by
  DEC-119: the pending task with the lowest priority). A router
  `route_after_coder` sends control back to the Coder while a task is
  `pending` and `error` is empty, and to END otherwise. No index or routing
  field is added.
- Why: one source of truth, so the state cannot contradict itself (an
  index pointing past a pending task); each step turns one `pending` task
  into `done` or `failed`, so the loop always ends (PM + 8 tasks = 9
  steps). LangGraph 1.2's default recursion limit is 10007, so it is no
  safety net; an explicit limit is IMP-010.
- Alternatives: the lab's index and routing fields (two more fields that
  can disagree with `tasks`).
- Code: `agents/coder_agent.py` — `_next_pending`; `orchestration/graph.py` —
  `route_after_coder`, `_add_coder`

### DEC-104 The run's memory window travels in the LangGraph run context
- Date: 2026-11-10 · Area: Coder node (Lab 2.2) · Status: accepted
- Basis: Preferred
- Context: DEC-099 needs one window per graph run. The state must stay
  JSON-serialisable and the window is private to the Coder (DEC-048).
- Decision: the graph declares a `context_schema`; whoever invokes the
  Coder graph (the tests now, `run()` from Lab 2.3) creates a new window
  for each `invoke(..., context=...)` and the Coder node reads it from the
  runtime. A missing context is a configuration error (DEC-109).
- Why: one window per run by construction, even if the graph is compiled
  once and reused (Module 4 cache, Docker service); same mechanism the
  Coder already uses inside its agent (`CoderContext`, DEC-077).
- Alternatives: a window created in `make_coder_node` (shared silently
  between runs once the graph is reused); the window's turns in the state
  (against DEC-048, grows the state and the traces).
- Code: `agents/coder_agent.py` — `CoderRunContext`; `orchestration/graph.py` —
  `build_coder_graph`

### DEC-105 The node turns a task into the Coder's prompt; `run_agent` stays
- Date: 2026-11-10 · Area: Coder node (Lab 2.2) · Status: accepted
- Basis: Preferred
- Context: `run_agent(task: str, window)` already meets C1.2–C1.5 and is
  tested; the handoff is a `TaskState`. `run_agent` always uses the
  default model, so the node could not be tested with a fake one.
- Decision: `make_coder_node(model)` lives in `agents/coder_agent.py`, like
  `make_pm_node` (DEC-094). A helper builds the task text from the task
  (description, Given/When/Then criteria, planned files) plus the context
  of DEC-098. `run_agent` gains an optional `model`; without it nothing
  changes. Long-term memory stores that whole text (DEC-019).
- Why: reuses the Module 1 Coder untouched in behaviour; the fake model
  makes the node testable like the PM.
- Alternatives: a new task-shaped entry point next to `run_agent` (two
  paths to keep in sync); storing only the description in memory (one more
  parameter; revisit if retrieval gets noisy, see IMP-006).
- Code: `agents/coder_agent.py` — `run_agent`, `_task_prompt`,
  `make_coder_node`

### DEC-106 `code` holds the files each task actually wrote
- Date: 2026-11-10 · Area: Coder node (Lab 2.2) · Status: accepted
- Basis: Preferred
- Context: the PM plans the files of each task (`TaskSpec.files`,
  DEC-084) because only it sees all tasks and can make a later task extend
  an earlier file. The Coder may still name or add files differently.
- Decision: the planned files reach the Coder as guidance. After each task,
  the files written by its valid `write_file` calls (as in DEC-080) are
  read from disk into `code`, keyed by their path relative to the
  workspace; a later write replaces the earlier content. A call rejected by
  validation is marked `StepRecord.rejected` and skipped; a file that
  cannot be read as text (binary, unreadable) is skipped with a WARNING, so
  the node never raises (DEC-102).
- Why: `code` matches what is on disk, the same rule C1.5 applies to the
  Coder's `code`; it never lists files that do not exist.
- Alternatives: the planned `TaskSpec.files` (may name files that were
  never written); the PM not planning files (reopens the closed Lab 2.1
  spec and loses cross-task coordination).
- Code: `agents/coder_agent.py` — `_written_files`,
  `result_from_messages`; `orchestration/state.py` — `StepRecord.rejected`

### DEC-107 Each task keeps its `CoderResult` next to its status
- Date: 2026-11-10 · Area: Coder node (Lab 2.2) · Status: accepted
- Basis: Preferred
- Context: DEC-101 keeps the full result of each task in the state;
  `CoderResult` has no task ID. DEC-090 makes `tasks` the tasks as
  executed. DEC-065 planned to move `CoderResult` to the shared state.
- Decision: `TaskState` gains `result: CoderResult | None` (None until the
  Coder runs it, or after a fatal error). `CoderResult` and `StepRecord`
  move to `orchestration/state.py`; `agents/coder_agent.py` imports them.
- Why: status and result of a task in one place, which is where QA
  (Module 3) and the assessor look; no parallel structure to keep aligned.
- Alternatives: a `results` list (needs a task ID added or a wrapper); a
  `results` dict by task ID (a second structure parallel to `tasks`).
- Code: `orchestration/state.py` — `TaskState.result`, `CoderResult`,
  `StepRecord`

### DEC-108 Flask is a project dependency
- Date: 2026-11-10 · Area: Coder node (Lab 2.2) · Status: accepted
- Basis: Required (C2.5: the graded demo is graded on working
  Flask/FastAPI code)
- Context: the Coder runs its scripts with the project's interpreter
  (`sys.executable`). Without Flask in the environment, any generated API
  fails on `import flask`, so the graded demo can never succeed.
- Decision: `flask>=3,<4` goes in `requirements.txt`. Generated APIs are
  verified with `app.test_client()` in a `__main__` block, never by
  starting the server (it would block until the 10 s timeout). The
  verification part is superseded by DEC-112 (separate check script;
  `__main__` serves the app); the Flask dependency stands.
- Why: the graded demo and the E2E fixture (`/health`, `/echo`) need it,
  as will the Docker image (C4.8); one dependency the project needs anyway.
- Alternatives: a stdlib `http.server` API (not what the guide asks for);
  a non-web demo in the test (postpones C2.5 evidence and reopens the spec).
- Revisit when: (resolved by DEC-112) Lab 2.3 — the PM writes the tasks, so who tells the Coder
  not to start servers (Coder prompt, PM prompt or both) is decided there.
- Code: `requirements.txt`; `tests/test_integration_coder.py` —
  `test_ac_2_2_15_demo_tasks`

### DEC-109 A missing run context is a configuration error; the task stays pending
- Date: 2026-11-10 · Area: Coder node (Lab 2.2) · Status: accepted
- Basis: Preferred
- Context: the window comes from the run context (DEC-104). If the Coder
  graph is invoked without `context=`, `runtime.context` is None; before
  this decision the node caught the `AttributeError` and marked the first
  task `failed` with a message that hid the cause (independent review F4).
- Decision: the node checks the context before running a task. Without
  it, it returns an `error` naming the fix (`context=CoderRunContext()`),
  logs it at ERROR and leaves every task untouched; the router ends the
  run (DEC-103).
- Why: the task never ran, so `pending` is the truthful status; the error
  tells the caller what to change instead of blaming the task.
- Alternatives: mark the task `failed` (reports a task failure that never
  happened); create a window on the fly (hides a wiring bug and breaks one
  window per run, DEC-099).
- Code: `agents/coder_agent.py` — `make_coder_node`

### DEC-110 The Coder runs after the PM only with no error and at least one task
- Date: 2026-11-11 · Area: Pipeline (Lab 2.3) · Status: accepted
- Basis: Preferred
- Context: the lab routes after the PM on a shared `routing` string, the
  error and a non-empty task list. Our PM already guarantees 2–8 tasks on
  success (DEC-081) and routing reads the state, not a signal field
  (DEC-103).
- Decision: a router after the PM sends control to the Coder when `error`
  is empty and `tasks` is not empty; otherwise the run ends without
  calling the Coder. No `routing` field is added.
- Why: a PM failure never reaches the Coder (the assessor forces one); the
  empty-list guard makes a future PM regression fail at the boundary
  instead of inside the Coder; one source of truth, as in DEC-103.
- Alternatives: route on `error` only (an empty list would reach the
  Coder, which reports "no pending task"); a `routing` field (a second
  signal that can contradict the state).
- Code: `orchestration/graph.py` — `route_after_pm`, `build_graph`

### DEC-111 A run succeeds only with no error and every task done
- Date: 2026-11-11 · Area: Pipeline (Lab 2.3) · Status: superseded by DEC-181
- Basis: Preferred (anticipates C3.3: never report success with failures)
- Context: with PM and Coder in one run there are three endings: all tasks
  done, some task `failed` while the loop went on (DEC-097), or a fatal
  error (DEC-087, DEC-102).
- Decision: a run is a success only when `error` is empty and every task
  is `done`. `main.py` ends with one verdict line (`RESULT: success`,
  `RESULT: incomplete — <task IDs> failed` or `RESULT: error — ...`) and
  exits 0 on success, 1 on an incomplete run or an error, 2 on invalid
  usage. It also prints, per task, its status, main file, iterations and
  an excerpt of its result, and the files generated.
- Why: the user, the assessor and scripts (Docker, CI) can tell a success
  from a run with unresolved issues without reading the log; the README
  can document exactly how.
- Alternatives: success when there is no fatal error (a failed task would
  exit 0); a separate exit code for incomplete runs (more cases to
  document for little gain).
- Code: `main.py` — `_verdict`, `_print_state`, `main`

### DEC-112 Long-running programs are never run; the Coder verifies them through an import
- Date: 2026-11-11 · Area: Pipeline (Lab 2.3) · Status: accepted
- Basis: Preferred (protects C2.5: executable Flask code that passes the
  request fixture)
- Context: DEC-108 left open who tells the Coder not to start servers once
  the PM writes the tasks. A script that calls `app.run()` never ends, so
  `exec_python` kills it at the 10 s timeout and nothing is verified. In
  Lab 2.2 the test's task text asked for `app.test_client()` checks inside
  `app.py`'s `__main__` block.
- Decision: a generated API starts its server from its own `__main__`
  block (`python app.py` serves it). The Coder never runs a program that
  does not end: it writes a separate check script that imports it and
  calls it in-process (for Flask, `app.test_client()`) and runs that. The
  rule lives in the Coder's system prompt only; the PM prompt does not
  change.
- Why: the assessor can run `python app.py` and send the fixture to a
  real server; the check script is the same pattern QA uses in Module 3
  (pytest + `test_client`); the Coder is the one that executes code, so a
  rule there holds whatever wording the PM uses.
- Alternatives: `__main__` runs the checks and never serves (simpler for
  the model, but `python app.py` does not start a server, a risk for
  C2.5); the rule in both prompts (duplicated, may drift); in the PM
  prompt only (depends on the PM writing it into every task).
- Code: `agents/coder_agent.py` — `CODER_SYSTEM_PROMPT`, `PLAN_SYSTEM_PROMPT`;
  `tests/api_fixture.py`

### DEC-113 Each project gets its own folder under the workspace, named by code
- Date: 2026-11-11 · Area: Pipeline (Lab 2.3) · Status: superseded by DEC-114
- Basis: Preferred (keeps C1.3 confinement; protects C2.2 and C2.5)
- Context: every run wrote into the same `workspace/`, which already holds
  files from earlier runs; a second demo run could read a stale `app.py`,
  and nobody could tell which files belong to which run.
- Decision: each run writes into `workspace/<project>/` and the Coder's
  tools are confined to that folder. The project name comes from the user
  (`--project`) or, without it, from the PM spec's `name`; code turns it
  into a slug of lowercase letters, digits and hyphens and rejects
  anything else, so the LLM never chooses the folder. A name given by the
  user whose folder already holds files stops the run with exit code 2
  before any LLM call; a name taken from the spec gets a numeric suffix
  (`echo-api-2`) instead. Nothing is deleted. `main.py` prints the folder.
- Why: one meaningful folder per project; no mixing of old and new files;
  repeated runs without `--project` always work (Docker, the assessor);
  a narrower confinement boundary than the whole workspace.
- Alternatives: one folder per run (safe but meaningless names); empty the
  workspace at start (deletes work silently); reuse an existing folder
  (the Coder does not know its files, so old code mixes in — continuing a
  project is IMP-011).

### DEC-114 Each run starts with an empty workspace; earlier files are archived
- Date: 2026-11-11 · Area: Pipeline (Lab 2.3) · Status: accepted
- Basis: Provisional (simplification until projects can be continued)
- Context: DEC-113 planned one folder per project, but no run can continue
  an earlier project yet (IMP-011), so the folders only kept old and new
  files apart. The assessor runs the system many times in a row.
- Decision: before invoking the graph, `run()` moves everything in
  `WORKSPACE_DIR` to `<workspace>_history/<timestamp>/` (next to the
  workspace, ignored by git) and starts with an empty workspace; `main.py`
  prints where it went. If the workspace is the repo root or contains it,
  nothing is moved and the run stops with an error. The tools keep the
  single `WORKSPACE_DIR` boundary (DEC-036).
- Why: no mixing of old and new files, nothing lost, no extra step for
  repeated runs; the archive is outside the tools' boundary, so the Coder
  cannot read it; far less code than per-project folders.
- Alternatives: per-project folders (DEC-113; waits for IMP-011); delete
  the workspace (loses work; dangerous with a misconfigured
  `WORKSPACE_DIR`); refuse a non-empty workspace (friction for repeated
  runs, may look like a failure to the assessor).
- Revisit when: IMP-011 (continue a project) is implemented; per-project
  folders come with it.
- Code: `orchestration/workspace.py` — `archive_workspace`; `orchestration/graph.py` — `run`;
  `tests/conftest.py` — `_temporary_workspace`

### DEC-115 The full graph has an explicit step limit and never loses the state
- Date: 2026-11-11 · Area: Pipeline (Lab 2.3) · Status: superseded by DEC-180
- Basis: Preferred (guards C2.4 and the future C3.3 loop; C4.4 cost)
- Context: LangGraph's default recursion limit is 10007 steps, so it is no
  safety net (IMP-010). Today the Coder loop ends by construction (one
  task per step, at most 8 tasks), but Module 3 adds the QA loop. When the
  limit is hit, `invoke` raises and the state is lost.
- Decision: `run()` passes `recursion_limit = 1 + MAX_TASKS + 2` (PM, one
  step per task, margin) and iterates `graph.stream(..., stream_mode=
  "values")`, keeping the last state. If the limit is hit, it returns that
  state with `error` set; it never raises.
- Why: a routing bug stops after a few steps instead of running until the
  cost shows it; the run still ends with an honest error and the progress
  so far, like any other failure (DEC-087, DEC-102).
- Alternatives: wait for Module 3 (no guard until then); `invoke` with the
  limit (the exception loses the state).
- Code: `orchestration/graph.py` — `STEP_LIMIT`, `run`

### DEC-116 `exec_python` refuses a file that starts a web server
- Date: 2026-11-11 · Area: Pipeline (Lab 2.3) · Status: accepted
- Basis: Preferred (protects C2.5; makes DEC-112 hold by construction)
- Context: with the DEC-112 rule in its prompts, the real Coder
  (`gpt-4.1-mini`) still planned "run app.py to check it" in most runs.
  It then either hit the 10 s timeout, or removed the `__main__` block so
  the file could run, so `python app.py` no longer served the API (4 of 5
  runs of AC-2.3-15).
- Decision: before running a file, `exec_python` (through
  `dispatch_tool`) reads it; if it creates a Flask app and calls its
  `.run(`, or calls `uvicorn.run(` or `.serve_forever(`, the file is not
  run and the observation explains why and what to do instead (a check
  script that imports it). The prompt rules of DEC-112 stay and are
  reinforced in the plan and loop prompts.
- Why: "the Coder never runs a server" becomes true in code, as path
  confinement is (DEC-036); no 10 s wait or wasted iteration; the model
  has no reason left to drop the `__main__` block.
- Alternatives: prompt changes only (not reliable with a small model, and
  every attempt costs real runs); accept the timeout and test only the
  real server (does not stop the model from removing `__main__`).
- Limits: a heuristic for Flask, FastAPI/uvicorn and stdlib servers; any
  other long-running program still ends at the timeout, as before (better
  detection: IMP-013). Since the API file itself is never run, a task's
  `success` comes from the last script run after the last write, which
  nothing forces to import the API (IMP-012).
- Code: `tools/handlers.py` — `_server_start`, `_server_refusal`, `dispatch_tool`

### DEC-117 Every PM task changes Python code
- Date: 2026-11-11 · Area: Pipeline (Lab 2.3) · Status: accepted
- Basis: Preferred (protects C2.5 and DEC-111)
- Context: a task is `done` only when the Coder ends `success`, which needs
  a main file and a run of code (DEC-101). In a real demo run the PM
  planned "Add requirements.txt" as its own task; it could never succeed,
  so the run ended `incomplete` with a working API (independent review F1).
- Decision: the PM's task prompt says every task creates or changes
  Python code that can be checked by running a script, and that
  dependency, documentation and configuration files go in a coding task's
  `files`. `TaskDraft.files` must include a `.py` file; a list without one
  is a validation error and gets the corrective retry (DEC-088).
- Why: the prompt alone is not reliable with an LLM; the validator makes
  the rule hold, and the retry tells the model what to change.
- Alternatives: count a written non-Python file as `success` (a task that
  never ran code would look verified); drop such tasks after planning
  (loses the files from the plan and may break coverage, C2.4).
- Code: `agents/pm_agent.py` — `TASKS_SYSTEM_PROMPT`, `TaskDraft._has_python_file`

### DEC-118 A body that is not JSON gets 400, whatever its content type
- Date: 2026-11-11 · Area: Pipeline (Lab 2.3) · Status: accepted
- Basis: Preferred (protects C2.5: the assessor supplies its own request
  fixture)
- Context: the fixture only sent malformed JSON with a JSON content type.
  Flask's `request.get_json()` answers 415 to a body with another or no
  content type, so an API passing our fixture could fail the assessor's
  "invalid input" request (independent review F2).
- Decision: the fixture sends four invalid bodies (malformed JSON, a
  `text/plain` body, an empty body, no content type) and each must get
  400. The Coder's API rule asks to answer 400 to any body that is not
  JSON (for Flask, `get_json(silent=True)` and 400 when it is None).
- Why: "basic input validation" reads as 400 for bad input; one rule
  covers every way a client can send a body that is not JSON.
- Alternatives: accept 415 as valid (the guide's fixture is unknown, so
  400 is the safer reading); put the rule in the PM prompt (DEC-112 keeps
  API rules in the Coder).
- Code: `tests/api_fixture.py` — `INVALID_BODIES`; `agents/coder_agent.py` —
  `CODER_SYSTEM_PROMPT`

### DEC-119 The Coder picks the pending task with the lowest priority
- Date: 2026-11-11 · Area: Pipeline (Lab 2.3) · Status: accepted
- Basis: Required (C2.3: the Coder consumes the handoff's priority; C2.4:
  tasks run in order); the rule — Preferred
- Context: DEC-103 ran the first `pending` task in list order. The PM
  numbers priorities in list order (DEC-085), so the result was right, but
  the Coder never read `priority`, and a state built any other way would
  run in the wrong order (independent review F5).
- Decision: `_next_pending` returns the pending task with the lowest
  `priority`; ties keep list order. Supersedes the task choice of DEC-103;
  the status-driven loop stays.
- Why: the handoff field the rubric names is the one that decides the
  order; same behaviour for every state the PM writes.
- Alternatives: keep list order and only test it (the Coder would still
  ignore `priority`); sort `tasks` in the PM (the order would depend on
  the writer again).
- Code: `agents/coder_agent.py` — `_next_pending`

### DEC-120 Progress notes are logged as each step ends
- Date: 2026-11-11 · Area: Pipeline (Lab 2.3) · Status: accepted
- Basis: Preferred (C2.4: per-task progress after each completion)
- Context: the state got each task's notes as it finished, but `main.py`
  printed `[PROGRESS]` only after the whole run, so a person watching the
  console saw no task finish until the end (independent review F6).
- Decision: `run()` logs every new progress note at INFO as soon as the
  graph step that wrote it ends (it already streams the steps, DEC-115),
  plus the archive note before the graph starts. `main.py` keeps the full
  `[PROGRESS]` list in its final summary.
- Why: one place covers the PM and the Coder notes; the default
  `LOG_LEVEL=INFO` shows them live on stderr, and `--json` output on stdout
  stays clean.
- Alternatives: print from the nodes (agents would write to the console);
  log inside each node (two places, and `run()` notes would be missed).
- Code: `orchestration/graph.py` — `run`

### DEC-121 Every agent is told that Flask is the only package installed
- Date: 2026-11-11 · Area: Pipeline (Lab 2.3) · Status: accepted
- Basis: Preferred (protects C2.5)
- Context: generated code runs with this project's interpreter, where
  Flask is the only web framework installed (DEC-108). Nothing told the
  agents so; in a real demo run the PM chose FastAPI, the Coder's check
  failed with `No module named 'fastapi'` and the run ended `incomplete`
  (found while verifying the R1 fixes).
- Decision: `PYTHON_ENVIRONMENT` in `agents/llm_helpers.py` says the
  project is Python 3.11 and that, besides the standard library, Flask is
  the only third-party package, to be used for any web server or API. The
  PM's spec and task prompts and the Coder's plan and loop prompts end
  with it.
- Why: one rule in both agents, so the spec never asks for a package the
  Coder cannot import, and the request fixture (Flask) matches.
- Alternatives: install FastAPI, uvicorn and httpx too (more dependencies,
  and the fixture and the server guard would need FastAPI support).
- Revisit when: a module needs another package for generated code (e.g.
  pytest for QA in Module 3).
- Code: `agents/llm_helpers.py` — `PYTHON_ENVIRONMENT`; `agents/pm_agent.py`,
  `agents/coder_agent.py` — system prompts

### DEC-122 The QA agent never modifies the Coder's code
- Date: 2026-11-16 · Area: QA Agent (Module 3) · Status: accepted
- Basis: Required (C3.2: QA returns structured fixes and the Coder revises);
  how it is enforced — Preferred
- Context: Module 3 adds a QA agent that reviews and tests the Coder's
  output. A QA that edits code itself would mix the two roles and skip the
  Coder revision that C3.2 grades.
- Decision: the QA only reads, tests and reports; every fix goes back to
  the Coder as a structured instruction. The rule is enforced by the tools
  each agent gets (the QA has no write access to the Coder's files), not
  by a prompt. The QA may write its own pytest files (C3.1); where they go
  is decided in Lab 3.2.
- Why: separation of responsibilities (the user's principle): one agent
  detects, one agent fixes. Enforcing it through tools means a model that
  ignores its prompt still cannot break it.
- Alternatives: let the QA patch trivial defects itself (fails C3.2 and
  blurs who owns the code).
- Code: — (applies from Lab 3.2)

### DEC-123 The graded protocol route is chosen at Lab 3.3
- Date: 2026-11-16 · Area: Protocol (Module 3) · Status: superseded by DEC-162
- Basis: Provisional
- Context: C3.5 grades one route: MCP (official SDK, a server exposing the
  file-system tools and the Coder as its client) or A2A (Coder/QA messages
  with sender, receiver, intent, payload, correlation_id and intent
  validation). The labs build both: MCP in Labs 3.1-3.2, A2A in Lab 3.3. No
  lab makes the Coder an MCP client.
- Decision: the route is chosen when Lab 3.3 starts, with both protocols
  seen. Until then, Lab 3.1's MCP server is built so the MCP route stays
  open (DEC-124). If MCP is chosen, a separate spec makes the Coder an MCP
  client before Module 3 closes.
- Why: nothing in Lab 3.1 needs the choice; deciding after seeing both
  avoids committing early.
- Alternatives: choose MCP now (premature; A2A not seen yet).
- Revisit when: Lab 3.3 starts.
- Code: —

### DEC-124 The MCP server's root is the agents' workspace
- Date: 2026-11-16 · Area: MCP server (Lab 3.1) · Status: accepted
- Basis: Preferred (keeps the C3.5 MCP route open, DEC-123)
- Context: the lab's server reads from a sample `project_files/` folder.
  In this project, the code the Coder writes lives in `WORKSPACE_DIR`
  (DEC-036, DEC-045).
- Decision: the MCP server serves `WORKSPACE_DIR`, not a `project_files/`
  folder.
- Why: the server is the shared file layer between agents; pointed at
  `workspace/` it sees the Coder's real output, and the same root works if
  the Coder becomes its client.
- Alternatives: a `project_files/` folder as in the lab (no other component
  uses it; the code would have to be copied there).
- Code: `tools/mcp_server.py` (`_relative`, `main`)

### DEC-125 The MCP server exposes `read_file` and a recursive listing
- Date: 2026-11-16 · Area: MCP server (Lab 3.1) · Status: accepted
- Basis: Preferred
- Context: anything the server exposes is usable by every client that
  connects, so it should expose only what the agents need. `workspace/`
  can hold subfolders and noise (`__pycache__/`, hidden files) that the
  lab's flat `project_files/` did not.
- Decision: one tool, `read_file(path)`, and one resource,
  `file://project/listing` (text/plain): every file under the root,
  recursively, one path per line, relative to the root, skipping
  `__pycache__/` and hidden entries. No `write_file` on the server for now.
- Why: each listed line can be passed unchanged to `read_file`, so the QA
  sees what exists and reads it without guessing paths. Without a write
  tool the QA cannot edit the Coder's code (DEC-122).
- Alternatives: a top-level listing as in the lab (folders hide their
  files, noise included); add `write_file` now (not needed until a Coder
  MCP client exists, DEC-123).
- Revisit when: the MCP route is chosen in Lab 3.3 (the Coder client
  needs `write_file`).
- Code: `tools/mcp_server.py` (`_list_files`, `read_resource`)

### DEC-126 The MCP server reuses the tool safety rules and hides what the listing hides
- Date: 2026-11-16 · Area: MCP server (Lab 3.1) · Status: accepted
- Basis: Required (C1.3, C4.6: validated tool arguments, no crash on bad
  input); hiding hidden files and `__pycache__/` — Preferred
- Context: MCP servers are trust boundaries: the caller is an LLM that can
  be wrong or manipulated, and everything exposed is reachable by any
  connected client.
- Decision: `read_file` on the server applies the same rules as the local
  tools: confinement to `WORKSPACE_DIR` via `resolve_in_workspace`
  (DEC-036, DEC-042), strict Pydantic argument validation, never raising
  (every failure returns `ERROR: ...` with `isError=True`), and the
  `READ_MAX_CHARS` cap (DEC-041). On top of that it rejects any path with a
  hidden component (`.env`, `.git/...`) or a `__pycache__` component, the
  same entries the listing skips (DEC-125).
- Why: what the listing does not show cannot be read either, so a secret
  that lands in `workspace/` by accident is not reachable over MCP; one
  set of rules for local tools and the server.
- Alternatives: confinement only, as the local `read_file` (a stray `.env`
  in the workspace would be readable).
- Code: `tools/mcp_server.py` (`_is_exposed`, `_read_file`)

### DEC-127 The MCP server logs one line per request to stderr
- Date: 2026-11-16 · Area: MCP server (Lab 3.1) · Status: accepted
- Basis: Required if the MCP route is chosen (C3.5 evidence: invocation
  logs linked to the grading run); otherwise lab success criterion
- Context: the lab requires the server log to show `read_file` going
  through the protocol. With stdio, stdout carries the protocol messages.
- Decision: the server logs to stderr, one line per event (start with its
  root, each tool call and resource read with its result and size),
  prefixed with the server's PID. Rejected calls log at WARNING. File
  contents are never logged.
- Why: a PID different from the client's proves the call crossed a process
  boundary; it is the invocation log C3.5 asks for at almost no cost.
  Not logging contents keeps secrets out of logs and traces (DEC-126).
- Alternatives: also log returned contents (noisy, leaks what DEC-126
  hides); no server log (fails the lab and, on the MCP route, C3.5).
- Code: `tools/mcp_server.py` (`_reject`, `_configure_logging`)

### DEC-128 The MCP server and client live in `tools/` and run as modules
- Date: 2026-11-16 · Area: MCP server (Lab 3.1) · Status: accepted
- Basis: Required (C1.1, C5.3: the mandated layout); module placement —
  Preferred
- Context: the lab puts `mcp_server.py`, `mcp_client.py` and a demo
  `main.py` at the repo root. Our `main.py` already runs the pipeline.
- Decision: the server is `tools/mcp_server.py`, started with
  `python -m tools.mcp_server`; the client is `tools/mcp_client.py`, whose
  `python -m tools.mcp_client [path]` is the lab's demo (lists tools and
  resources, reads one file).
- Why: the server exposes file-system tools and reuses the safety code in
  `tools/`; running it as a module makes those imports work from the repo
  root without touching `sys.path`.
- Alternatives: a new `protocols/` package (an extra folder the guide does
  not ask for); files at the root as in the lab (breaks the layout and
  needs `sys.path` hacks).
- Code: `tools/mcp_server.py`, `tools/mcp_client.py`

### DEC-129 The MCP SDK is pinned to the 1.x line
- Date: 2026-11-16 · Area: MCP server (Lab 3.1) · Status: accepted
- Basis: Required (C3.5: official Python MCP SDK); the 1.x line — Preferred
- Context: the official SDK has two maintained lines: 1.x (1.30.0,
  2026-09) and 2.x (2.3.0, 2026-10), whose API is reorganised and whose
  types moved to a separate `mcp-types` package. The lab and its tests use
  the 1.x API (`Server`, `request_handlers`, `stdio_client`).
- Decision: `mcp>=1.30,<2`.
- Why: it is the official SDK and the API the course material teaches;
  2.x is unverified here and would move us away from the handouts.
- Alternatives: 2.x (newer, API not checked against the labs).
- Revisit when: the Coder becomes an MCP client (DEC-123) or 1.x stops
  receiving fixes.
- Code: `requirements.txt`

### DEC-130 The MCP server uses the low-level `Server` and its own validation
- Date: 2026-11-16 · Area: MCP server (Lab 3.1) · Status: accepted
- Basis: Preferred (applies DEC-126)
- Context: the SDK offers the low-level `Server` (handlers and JSON Schema
  written by hand) and `FastMCP` (schema from type hints, exceptions turned
  into errors). The low-level `call_tool` also validates the arguments
  against `inputSchema` by default and answers `Input validation error:
  ...`, without our `ERROR:` prefix.
- Decision: low-level `Server`, as in the lab, with
  `call_tool(validate_input=False)`: the strict Pydantic model is the only
  validator. Every failure is returned as a `CallToolResult` with
  `isError=True` and text starting with `ERROR:`; handlers never raise.
- Why: one validator and one error format for every failure (bad
  arguments, unknown tool, rejected path), so a client tells an error from
  content by `isError` or the prefix, never by guessing.
- Alternatives: `FastMCP` (the SDK decides validation and error text);
  keep the SDK's schema validation (two validators, two error formats).
- Code: `tools/mcp_server.py` (`call_tool`, `_error`)

### DEC-131 The server's `read_file` reuses the local pieces and reports relative paths
- Date: 2026-11-16 · Area: MCP server (Lab 3.1) · Status: accepted
- Basis: Preferred (applies DEC-126)
- Context: `file_io.read_file` returns its errors as text that includes the
  absolute path (`Error reading file '/abs/path': ...`), which would leak
  the server's layout to any client.
- Decision: the server validates with `ReadFileArgs` (strict, confined),
  then checks exposure and that the target is an existing file, then calls
  `file_io.read_file` for the read and the `READ_MAX_CHARS` cap. A residual
  error (permissions, not UTF-8) is recognised by its exact prefix and
  rewritten as `ERROR: <relative path>: <reason>`. One function,
  `_is_exposed`, decides visibility for both the listing and `read_file`;
  it checks the requested path and the resolved one, so a visible symlink
  to a hidden file is rejected. The workspace is read from
  `tools.handlers.WORKSPACE_DIR` at call time.
- Why: one set of rules (DEC-126) without touching Module 1 code; "what is
  not listed cannot be read" holds by construction; reading the root at
  call time keeps the test fixtures' temporary workspace working.
- Alternatives: a separate reader in the server (duplicates the truncation
  of DEC-041); make `file_io` raise exceptions (cleaner, but changes Module
  1 code for no graded gain).
- Code: `tools/mcp_server.py` (`_is_exposed`, `_read_file`, `_list_files`)

### DEC-132 The client starts the server with an explicit workspace
- Date: 2026-11-16 · Area: MCP client (Lab 3.1) · Status: accepted
- Basis: Preferred
- Context: with stdio the client starts the server as a child process. The
  1.x SDK passes the child only a small set of variables (`HOME`, `PATH`,
  ...), not the whole environment.
- Decision: the client starts `[sys.executable, "-m", "tools.mcp_server"]`
  with `cwd` at the repo root and `WORKSPACE_DIR` set explicitly in `env`
  to the client's workspace. The server still runs `load_dotenv()` through
  `tools.handlers`, so the API key is in its process; it never calls the
  LLM or runs code, and never returns or logs environment values.
- Why: the server always serves the same root the caller sees, and tests
  can point it at a temporary folder instead of the real `workspace/`.
- Alternatives: let the server read `WORKSPACE_DIR` from `.env` (tests
  could not isolate it and would read the real `workspace/`).
- Code: `tools/mcp_client.py` (`_server_parameters`, `connect_and_run`)

### DEC-133 MCP tests run the real server: in memory, plus one stdio test
- Date: 2026-11-16 · Area: Tests (Lab 3.1) · Status: accepted
- Basis: Required (C4.7 and the C2.x notes: tests check behaviour, not
  fixed objects); the split — Preferred
- Context: the lab tests the client with `MagicMock` sessions, which pass
  even if the server has no handler or a wrong schema. The SDK's
  `create_connected_server_and_client_session` connects a real
  `ClientSession` to our server inside the test process.
- Decision: almost every server and client test goes through the full MCP
  protocol against the real server in memory (no subprocess, no network).
  One test starts the server over stdio as a separate process and checks
  that the call works and that the server's stderr log shows a PID other
  than the test's. No test mocks the session.
- Why: the in-memory tests are as fast as mocks and catch server bugs; the
  stdio test is the only proof that the call crosses a process boundary
  (lab criterion; C3.5 evidence if MCP is chosen) and costs 1-2 s.
- Alternatives: mocks only, as in the lab (prove nothing about the
  server); no stdio test and a `manual` check of the PID (depends on
  someone looking).
- Code: `tests/conftest.py` (`mcp_session`), `tests/test_mcp_server.py`,
  `tests/test_mcp_client.py`

### DEC-134 Async tests use pytest-asyncio in auto mode
- Date: 2026-11-16 · Area: Tests (Lab 3.1) · Status: accepted
- Basis: Preferred
- Context: the MCP APIs are async, so tests need a plugin that runs
  coroutines. No test in the repo was async before Lab 3.1.
- Decision: `pytest-asyncio` with `asyncio_mode = auto` in `pytest.ini`.
- Why: it is what the lab uses and `async def test_...` needs no marker;
  auto mode changes nothing for the existing synchronous tests.
- Alternatives: the `anyio` plugin that ships with `mcp` (no new
  dependency, but a marker and an `anyio_backend` fixture on every test).
- Code: `pytest.ini`, `requirements.txt`

### DEC-135 The MCP client waits at most `MCP_TIMEOUT` seconds per request
- Date: 2026-11-16 · Area: MCP client (Lab 3.1, review R1) · Status: accepted
- Basis: Required (C4.6: no hang or crash on failure; the evaluator forces
  failures)
- Context: the independent review of Lab 3.1 found that a dead or stalled
  server makes `connect_and_run` wait forever (the SDK's `ClientSession`
  has no read timeout by default).
- Decision: every request of the client waits at most `MCP_TIMEOUT`
  seconds (environment variable, default 30, must be > 0), then raises an
  error. The demo exits with 0 when the server answers, also with an
  `ERROR:` text, and with 1 when it cannot talk to the server.
- Why: a request to a live server takes milliseconds and starting the
  server under WSL takes 1-2 s, so 30 s never cuts a healthy call and
  still ends a hung one. A rejected read is a normal answer; failing to
  reach the server is a system failure, so only that gives exit code 1.
- Alternatives: no timeout (hangs); a fixed value in code (the evaluator
  and Docker cannot tune it).
- Code: `tools/mcp_client.py` (`_timeout`, `connect_and_run`, `main`)

### DEC-136 The MCP server checks the file it really reads and escapes client values in its log
- Date: 2026-11-16 · Area: MCP server (Lab 3.1, review R1) · Status: accepted
- Basis: Required (C1.3, C4.6); complements DEC-126, DEC-127, DEC-131
- Context: the independent review of Lab 3.1 found that `_is_exposed`
  normalised `..` lexically while the read follows symlinks first, so
  `d/../config` with `d -> .git/hooks` read `.git/config`; that a file name
  that is not UTF-8 killed the stdio server when the listing was
  serialised; that a name with a newline broke the listing; that client
  strings with newlines forged log lines; and that `__pycache__` was
  matched case-sensitively although the repo lives on NTFS.
- Decision: the exposure rule checks the requested name (ignoring `.` and
  `..`) and the symlink-resolved file that is actually read, and matches
  `__pycache__` case-insensitively. A requested absolute path that is not
  lexically inside the workspace is not served. The listing skips names
  that are not valid UTF-8 or contain a line break. Rejection messages
  name the path as the client sent it; success lines name the file read,
  relative to the workspace. Client-controlled values are written to the
  log with `%r`, so they cannot add lines.
- Why: the check and the read must look at the same file, or a symlink
  opens a gap; names that cannot be sent or asked back must not be listed;
  the log is the evidence of each call (DEC-127), so a client must not be
  able to write into it. Naming the path as sent never reveals where a
  symlink points.
- Alternatives: reject any `..` component (simpler, but refuses harmless
  paths like `pkg/../a.py` and still needs the real-target check for
  symlinked folders); strip control characters instead of `%r` (loses
  what the client really sent).
- Code: `tools/mcp_server.py` (`_is_exposed`, `_is_hidden`,
  `_is_servable_name`, `_read_file`, `_reject`)

### DEC-137 Lab 3.2 builds a QA that writes and runs pytest tests
- Date: 2026-11-17 · Area: QA Agent (Lab 3.2) · Status: accepted
- Basis: Required (C3.1)
- Context: the Lab 3.2 handout builds a QA that only sends the code to an
  LLM for review and returns an `IssueList`. C3.1 marks "QA is only an LLM
  review" as Not Yet: the QA must write real pytest tests for the
  acceptance criteria, run them in a subprocess with a timeout, parse the
  failures and return structured issues and fixes. Labs 3.3 and 3.4 reuse
  the Lab 3.2 QA as it is, so no later lab adds the tests.
- Decision: Lab 3.2 builds the executable QA. From the handout it keeps
  the file read through the MCP server, the `Issue`/`IssueList` models and
  the validator that refuses approval on blocking issues (DEC-139). The
  LLM review stays as a second, advisory source of issues.
- Why: building an LLM-only QA now would make Lab 3.3 build its loop on an
  `approved` flag decided by an LLM; switching it to test results later
  would redo the loop's meaning, its termination tests and the A2A
  payload.
- Alternatives: follow the handout now and add the tests in a separate
  spec before Module 3 closes (touches the QA and the loop twice).
- Code: — (applies from the Lab 3.2 spec)

### DEC-138 The QA tests each task against that task's acceptance criteria
- Date: 2026-11-17 · Area: QA Agent (Lab 3.2) · Status: accepted
- Basis: Preferred
- Context: the QA could test each task once the Coder finishes it, or the
  whole project once against the spec-level criteria.
- Decision: the QA works per task: it receives one task of the PM's
  handoff (with its Given/When/Then acceptance criteria) and writes and
  runs the tests for those criteria.
- Why: reuses the handoff that already exists (C2.3); each failure is
  linked to a concrete criterion (C3.1 evidence) and its fix goes back to
  the task that caused it (C3.2: failing assertion, fix and retest linked
  to the same task).
- Alternatives: one QA pass at the end against the spec (cheaper, but
  failures are hard to attribute and the Coder would revise everything).
- Code: — (applies from the Lab 3.2 spec)

### DEC-139 Approval depends on a configurable blocking severity; only failing tests are High
- Date: 2026-11-17 · Area: QA Agent (Lab 3.2) · Status: superseded by DEC-174
- Basis: Required (C3.1, C3.2: the loop exits when all tests pass; lab:
  `approved` enforced by a `model_validator`); the threshold — Preferred
- Context: issues come from two sources: executed tests (evidence) and the
  LLM review (opinion). The handout sets `approved=False` whenever a High
  issue exists. An LLM that invents a High issue would block a working
  task until the loop limit.
- Decision: a failing test always produces a High issue. Issues from the
  LLM review alone are Medium or Low, never High. `QA_BLOCKING_SEVERITY`
  (`High` | `Medium` | `Low`, default `High`) sets the lowest severity
  that blocks: `approved` is False whenever any issue is at or above it,
  enforced by the model's validator whatever the LLM returned. A task is
  never approved if no test ran. With the default, the task passes when
  its tests pass.
- Why: blocking needs executed evidence, not an opinion; the threshold
  lets the user ask for stricter reviews. With `Low` the loop rarely
  converges (an LLM almost always finds a style remark) and ends at the
  limit with an unresolved-issue report, which C3.3 allows.
- Alternatives: tests only, no threshold (no way to make the review
  count); tests plus High issues from the review (an invented issue can
  block until the limit); LLM review only (Not Yet in C3.1).
- Code: `orchestration/state.py` (`Issue`, `QAReport` validators, `QAReport.blocking_issues`)

### DEC-140 Separate `workspace_coder/` and `workspace_qa/` folders, each agent confined to its own
- Date: 2026-11-17 · Area: QA Agent (Lab 3.2) · Status: accepted
- Basis: Preferred; completes DEC-122 (where the QA's tests live)
- Context: the QA writes pytest files. If the Coder could edit them, the
  easy way to pass would be to change the test instead of the code; if it
  could read them, it would tend to special-case the test inputs. The fix
  instructions already carry the failing test, assertion and expected vs
  actual values.
- Decision: the Coder's folder `workspace/` is renamed `workspace_coder/`
  and its variable `WORKSPACE_DIR` becomes `CODER_WORKSPACE_DIR`. The QA
  gets `workspace_qa/`, set by `QA_WORKSPACE_DIR`, kept after the run as
  evidence (C3.1 asks for the generated pytest files). The Coder has no
  access to `workspace_qa/` (its tools stay confined to its own folder,
  DEC-036). The QA reads the Coder's code only through the MCP server,
  which is read-only (DEC-124, DEC-125), writes only in `workspace_qa/`,
  and runs the tests in a subprocess with a timeout and without
  credentials (DEC-039), since running them runs the Coder's code.
- Why: one agent detects and one fixes (DEC-122), enforced by what each
  agent can reach, not by a prompt; the names say whose folder each one
  is.
- Alternatives: tests inside the Coder's workspace (the Coder could edit
  them); Coder with read-only access to the tests (needs a new tool and
  invites overfitting); keep `WORKSPACE_DIR` for the Coder (fewer changes,
  but the name no longer says whose folder it is).
- Code: `tools/handlers.py` (`CODER_WORKSPACE_DIR`), `agents/qa_agent.py`
  (`load_qa_settings`, `write_tests`), `tools/code_executor.py` (`run_pytest`)

### DEC-141 The QA retries its own broken output within one `QA_MAX_ATTEMPTS` budget
- Date: 2026-11-17 · Area: QA Agent (Lab 3.2) · Status: accepted
- Basis: Preferred; same corrective-retry idea as DEC-088
- Context: a test can fail because the code is wrong (an assertion fails)
  or because the QA's own test is broken (it cannot be collected: syntax
  error, bad import). The LLM can also return output that breaks the
  schema. Sending the QA's own errors to the Coder would waste its
  iterations on correct code.
- Decision: an assertion failure goes to the Coder as a fix instruction;
  the QA never retries it (the Coder↔QA loop and its limit come in Lab
  3.3, C3.3). Invalid LLM output and tests that cannot be collected count
  as one failed QA attempt; the next attempt gets the error to correct
  it. Both share one budget, `QA_MAX_ATTEMPTS` (environment variable,
  default 2). When it runs out, the result is not approved and carries an
  issue saying the QA could not produce runnable tests, not attributed to
  the Coder.
- Why: for the QA both failures mean "no usable tests"; one number is
  easier to understand and bounds the worst case (2 calls, not 2×2).
- Alternatives: send every failure to the Coder (wastes its iterations);
  separate budgets for invalid output and uncollectable tests (more
  control, rarely useful).
- Code: `agents/qa_agent.py` (`write_tests`, `_test_task`, `_skip_uses`, `_judge_run`, `run_qa`)

### DEC-142 A QA that cannot do its job returns a structured, unapproved result
- Date: 2026-11-17 · Area: QA Agent (Lab 3.2) · Status: accepted
- Basis: Required (C3.3: never claim success; C4.6: no crash); transient
  retries — Provisional
- Context: the QA can fail outside its control: the MCP server is down,
  the LLM call fails or times out, the test run times out, or the review
  call gives invalid output after its attempts.
- Decision: the QA never raises to the graph and never approves by
  default: it returns `approved=False` with the cause. If only the LLM
  review fails and the tests ran: with `QA_BLOCKING_SEVERITY=High` the
  result is decided by the tests and notes "review unavailable"; with
  `Medium` or `Low` it is not approved, since the absence of blocking
  issues cannot be checked. Transient errors (network, LLM timeout, MCP
  down) get no retry yet, as in the PM (DEC-087).
- Why: what cannot be checked is never approved; per-call retries with
  backoff and jitter are C4.2 and arrive for every agent at once in
  Module 4.
- Alternatives: raise and let the graph fail (crashes the run); retry
  transient errors now in the QA only (early, and unlike the PM and
  Coder).
- Revisit when: Module 4 adds per-call retries and the circuit breaker
  (C4.2, C4.3).
- Code: `agents/qa_agent.py` (`run_qa`, `_qa_failure`, `review_code`)

### DEC-143 Lab 3.2 builds the QA as a standalone component
- Date: 2026-11-17 · Area: QA Agent (Lab 3.2) · Status: accepted
- Basis: Preferred
- Context: the QA could be wired into the graph after the Coder now, or
  built and tested alone, as the handout does.
- Decision: Lab 3.2 delivers a QA function with a typed input (the task
  and its files) and a typed output (the QA report), with mocked unit
  tests and one live test. The graph node, the Coder↔QA loop and the
  messages between agents come in Lab 3.3; the three-agent pipeline in
  Lab 3.4.
- Why: follows the labs' split and does not build work a later lab
  covers; the typed boundary is what Lab 3.3 wires in.
- Alternatives: add the QA node to the graph now (early, without the
  loop).
- Code: — (applies from the Lab 3.2 spec)

### DEC-144 The QA is a fixed pipeline, not a ReACT or plan-execute agent
- Date: 2026-11-17 · Area: QA Agent (Lab 3.2) · Status: accepted
- Basis: Preferred
- Context: the QA always does the same steps: read the code, write tests,
  run them, turn failures into issues, review, report. Its only branch is
  known in advance (tests that cannot be collected are regenerated,
  DEC-141).
- Decision: the steps are fixed in code; the LLM is called only where
  judgement is needed: writing the tests and reviewing the code.
- Why: an LLM choosing the next step adds nothing when the steps never
  change, and could skip the test run, which would turn the QA back into
  an LLM-only review (Not Yet in C3.1). The attempt budget (DEC-141) holds
  by construction. Same pattern as the PM (DEC-087).
- Alternatives: ReACT with `write_test`/`run_tests` tools (flexible, but
  the model may skip running or not stop); plan-execute (the plan would
  always be the same).
- Code: `agents/qa_agent.py` (`run_qa`)

### DEC-145 QA tests run in place against the Coder's folder
- Date: 2026-11-17 · Area: QA Agent (Lab 3.2) · Status: accepted
- Basis: Preferred; refines DEC-140
- Context: the tests could run against a copy of the Coder's files, read
  through MCP into `workspace_qa/`, or directly against
  `workspace_coder/`.
- Decision: the QA reads the Coder's code through MCP to give it to the
  LLM (test writing gets only its interface, DEC-158; the review gets it
  whole). pytest runs the test file from
  `workspace_qa/<task_id>/` with `cwd` and `PYTHONPATH` set to
  `workspace_coder/` (like the Coder's scripts, DEC-040), with
  `-p no:cacheprovider` and `PYTHONDONTWRITEBYTECODE=1` so nothing is
  left in the Coder's folder.
- Why: a copy adds ways to fail (truncated reads, files the listing hides,
  non-text files) and isolates nothing: test code can write anywhere the
  user can, copy or not; the real isolation is the sandbox (no
  credentials, timeout). The Coder and the QA never run at the same time,
  so the code run is the code read.
- Alternatives: a copy in `workspace_qa/` read through MCP (tests exactly
  what was read, but fails on truncated or hidden files).
- Code: `tools/code_executor.py` (`run_pytest`), `tools/mcp_client.py`
  (`read_multiple_files`), `agents/qa_agent.py` (`run_qa`)

### DEC-146 `run_pytest` shares the sandbox of `run_python` and stays out of MCP
- Date: 2026-11-17 · Area: Tools (Lab 3.2) · Status: accepted
- Basis: Required (C3.1: subprocess with an enforced timeout; C1.3);
  where it lives — Preferred
- Context: the QA needs to run pytest with the same protections as the
  Coder's scripts. It could also be exposed as an MCP tool.
- Decision: the process handling of `run_python` (environment allowlist,
  closed stdin, own process group killed at the end, timeout `EXEC_TIMEOUT`,
  output truncation) moves to a shared function in
  `tools/code_executor.py`; `run_python` keeps its behaviour and
  `run_pytest` is a new local function on top of it. It is not exposed
  through the MCP server.
- Why: one sandbox, already tested for C1.3/C4.6. The MCP server is
  read-only (DEC-125, DEC-126) and the MCP route of C3.5 asks for
  file-system tools; adding execution changes its security model for no
  criterion, and the protocol is still open (DEC-123).
- Alternatives: a second subprocess wrapper for pytest (duplicates the
  safety rules); `run_tests` as an MCP tool (see above).
- Code: `tools/code_executor.py` (`_run_sandboxed`, `run_pytest`)

### DEC-147 pytest results are read from its JUnit XML report and exit code
- Date: 2026-11-17 · Area: QA Agent (Lab 3.2) · Status: accepted
- Basis: Preferred
- Context: the QA must know which test failed and with which assertion,
  and tell failing assertions from tests that could not be collected
  (DEC-141).
- Decision: pytest writes `--junitxml` into the task's QA folder; the QA
  parses it with `xml.etree` (expat 2.9 guards against entity expansion).
  The exit code classifies the run: 0 passed, 1 assertions failed, 2/4/5
  the tests could not be collected or none ran.
- Why: stable, structured and in the standard library.
- Alternatives: parse pytest's text output (fragile); `pytest-json-report`
  (a new dependency for the same data).
- Code: `tools/code_executor.py` (`_read_junit`, `run_pytest`)

### DEC-148 Generated tests come as a schema, each test tied to one criterion
- Date: 2026-11-17 · Area: QA Agent (Lab 3.2) · Status: accepted
- Basis: Required (C1.3: LLM output validated before acting; C3.1: issues
  linked to failing assertions); the shape — Preferred
- Context: the LLM writes the tests. The QA must check them before running
  anything and must be able to link a failed test to the criterion it
  checks.
- Decision: the LLM returns a `preamble` (imports) and a list of tests,
  each with `criterion_index`, `name` and `code`. Before running, the QA
  checks: the assembled file parses (`ast.parse`, which does not execute
  it); each name starts with `test_`, is unique and is defined by its
  `code`; every criterion of the task has at least one test. The schema is
  built per task with that check, as the PM does for coverage (DEC-091),
  so a failed check is fed back to the model as a validation error.
- Why: invalid output never reaches execution, and a failed test maps to
  its criterion without parsing names.
- Alternatives: free-form test file (no link to criteria, checks only by
  running it).
- Code: `agents/qa_agent.py` (`_pytest_draft_schema`, `write_tests`)

### DEC-149 Issues carry a fix, a source and a criterion; the report computes `approved`
- Date: 2026-11-17 · Area: QA Agent (Lab 3.2) · Status: accepted
- Basis: Required (C3.1: structured issue and fix instructions; lab:
  `Issue` fields and the `model_validator`); the extra fields — Preferred
- Context: the lab's `Issue` has `severity`, `location`, `description`. The
  Coder needs an actionable instruction, the rules differ by where an
  issue comes from (DEC-139, DEC-141), and the evidence of C3.1/C3.2 links
  failures to acceptance criteria.
- Decision: `Issue` keeps the lab's three fields and adds `fix` (what the
  Coder must change), `source` (`test`: an executed test failed, always
  High; `review`: LLM opinion, Medium or Low only; `qa`: the QA could not
  do its job, High and not the Coder's fault) and `criterion` (the
  Given/When/Then broken, empty when none). `QAReport` holds the task ID,
  the issues, the test results, the blocking severity used and notes;
  its validator computes `approved` from those, whatever value it was
  given, and rejects a `review` issue marked High. The review call writes
  the `fix` of each failing test; if the review is unavailable, a minimal
  fix is built from the assertion ("Make test_X pass; it failed with:
  ...").
- Why: the Coder always gets an instruction; the report decides approval
  from data it holds, not from environment variables read during
  validation; it is the payload Lab 3.3 sends back to the Coder.
- Alternatives: the lab's three fields only (no fix instruction, no link
  to criteria).
- Code: `orchestration/state.py` (`Issue`, `QAReport`), `agents/qa_agent.py` (`_judge_run`, `review_code`)

### DEC-150 `run_qa` is async and uses `QA_MODEL`
- Date: 2026-11-17 · Area: QA Agent (Lab 3.2) · Status: accepted
- Basis: Required (C4.5: small model for the QA); async — Preferred
- Context: the MCP client is async, the lab's `run_qa_agent` is async and
  Lab 3.3 runs the agents over an asyncio broker; `structured_call` is
  synchronous.
- Decision: `run_qa` is a coroutine; LLM calls go through
  `structured_call` in `asyncio.to_thread`. The model comes from `QA_MODEL`
  (default `openai/gpt-4.1-mini`), read when the QA runs, as the PM does
  (DEC-093).
- Why: a sync wrapper with `asyncio.run` fails inside a running event
  loop, which is where Lab 3.3 calls it; its own variable lets the QA
  model change without touching the Coder's.
- Alternatives: sync `run_qa` (breaks under Lab 3.3's broker); reuse
  `LLM_MODEL` (couples QA and Coder).
- Code: `agents/qa_agent.py` (`run_qa`)

### DEC-151 QA settings come from environment variables checked at startup
- Date: 2026-11-17 · Area: QA Agent (Lab 3.2) · Status: accepted
- Basis: Preferred
- Context: DEC-139..DEC-141 and DEC-150 add settings.
- Decision: `CODER_WORKSPACE_DIR` (default `workspace_coder`, replaces
  `WORKSPACE_DIR`), `QA_WORKSPACE_DIR` (default `workspace_qa`),
  `QA_MODEL`, `QA_MAX_ATTEMPTS` (default 2, at least 1) and
  `QA_BLOCKING_SEVERITY` (default `High`). Invalid values stop the program
  at startup with a message naming the variable, like `EXEC_TIMEOUT`
  (DEC-045). A `WORKSPACE_DIR` still set without `CODER_WORKSPACE_DIR`
  is an error naming the new variable, so an old `.env` is never ignored
  silently. All are documented in `.env.example`.
- Why: a wrong setting fails at once and clearly, not halfway through a
  run; the evaluator can tune each limit.
- Alternatives: accept `WORKSPACE_DIR` as an alias (two names for one
  setting).
- Code: `tools/handlers.py` (`_coder_workspace_dir`), `agents/qa_agent.py` (`load_qa_settings`)

### DEC-152 A failure is blamed on the file where it happens
- Date: 2026-11-17 · Area: QA Agent (Lab 3.2) · Status: accepted
- Basis: Preferred; refines DEC-141 and DEC-146
- Context: DEC-141 sends the Coder's failures to the Coder and makes the
  QA retry its own. Import errors, collection errors and hangs can come
  from either side: a missing module may be the Coder's (it never created
  a task file) or the QA's (it invented a name); a hang may be an endless
  loop in the Coder's code or a test that waits forever.
- Decision: the owner is the file where the problem happens.
  - Before running, the QA checks the draft's imports with `ast`: a module
    that is neither a task file nor installed, or a name the Coder's file
    does not define and the task never mentions, is the QA's (the draft is
    rejected and regenerated within `QA_MAX_ATTEMPTS`); a missing task
    file, or a missing name the task mentions, is the Coder's (a `test`
    High issue, no regeneration).
  - A name the test file uses but never imports or defines (e.g. the
    class without its import) is the QA's: the draft is rejected before
    running, since the `NameError` would otherwise happen inside a test
    and be blamed on the Coder (found by the live test, AC-3.2-26).
  - The preamble may hold only imports, functions and classes, and each
    test's code only its function, so the test file runs nothing at
    import time.
  - A collection error is blamed by the deepest frame of its traceback
    that lies in the Coder's or the QA's folder; when none does, it is the
    QA's.
  - Each test gets its own timeout through `pytest-timeout`
    (`QA_TEST_TIMEOUT`, default 2 s, at least 1 and lower than
    `EXEC_TIMEOUT`); a timed-out test is blamed by the frame where it was
    stuck, and the other tests keep running. The whole run has its own
    bound (DEC-161); a run that hits it is the Coder's, since the test
    file runs almost nothing at import: only decorator arguments and
    default values, a rare way for the QA to hang that is accepted (the
    issue is worded neutrally). Corrected after the Lab 3.2 review.
  - A failure inside a test that runs (a false assertion or any exception)
    is the Coder's.
- Why: the Coder gets every defect that is its own, and is never sent the
  QA's mistakes; a hang in one test no longer hides the other results.
  Blaming exceptions inside running tests more finely (e.g. a method the
  task never named) adds much logic for little gain.
- Alternatives: every collection error is the QA's (a missing task file
  would never reach the Coder); every timeout is the Coder's (a test that
  waits forever would cost the Coder iterations).
- Code: `agents/qa_agent.py` (`_import_problems`, `_undefined_names`, `_pytest_draft_schema`, `_blame`, `_judge_run`, `_test_task`)

### DEC-153 `Issue` and `QAReport` live in the shared state and count tests
- Date: 2026-11-17 · Area: QA Agent (Lab 3.2) · Status: accepted
- Basis: Preferred
- Context: the lab defines `Issue` in the QA's file. In Lab 3.3 the QA's
  report travels in the graph's shared state and in the payload back to
  the Coder. The report must hold enough of the test run to decide
  `approved` (DEC-149).
- Decision: `Severity`, `Issue` and `QAReport` are defined in
  `orchestration/state.py`, next to `CoderResult`. The report holds the
  test run as two counters, `tests_passed` and `tests_failed`; the detail
  of each failing test lives in its `test` issue.
- Why: the state never imports from `agents/`, as today; the counters are
  all the approval rule needs, and a per-test list would repeat each
  failing test already described by its issue.
- Alternatives: models in `agents/qa_agent.py` (the state would import
  from an agent); a list with every test, its criterion and its outcome
  (richer, no AC needs it).
- Revisit when: Lab 3.3 needs the passing tests or their criteria.
- Code: `orchestration/state.py`

### DEC-154 The QA's folder never overlaps the Coder's
- Date: 2026-11-17 · Area: QA Agent (Lab 3.2) · Status: accepted
- Basis: Preferred; protects DEC-140
- Context: `QA_WORKSPACE_DIR` and `CODER_WORKSPACE_DIR` are set
  independently. If the QA's folder were the Coder's, or inside it, the
  Coder's tools could read and edit the tests.
- Decision: loading the QA settings raises `ValueError` naming
  `QA_WORKSPACE_DIR` when the QA's folder is the Coder's, inside it, or
  contains it.
- Why: the separation of DEC-140 is enforced by configuration checks, not
  by trusting the `.env`.
- Alternatives: trust the configuration (one wrong line breaks DEC-140
  without notice).
- Code: `agents/qa_agent.py` (`load_qa_settings`)

### DEC-155 The QA's pytest runs isolated from the project's configuration and plugins
- Date: 2026-11-17 · Area: Tools (Lab 3.2) · Status: accepted
- Basis: Preferred; makes DEC-152's timeouts usable
- Context: the QA's tests live inside the repo, so pytest would read the
  project's `pytest.ini` and load every installed plugin (LangSmith,
  asyncio, anyio). Measured on the development machine: about 10 s to
  start with all plugins, about 2 s without them, against a run timeout
  of `EXEC_TIMEOUT` (10 s by default). Separately, pytest-timeout counts
  the formatting of a failure's traceback; on the WSL `/mnt/c` disk that
  took more than 1 s and turned a failing test into a pytest INTERNALERROR.
- Decision: `run_pytest` starts pytest with no configuration file
  (`-c /dev/null`, `--rootdir` = the test's folder), with no `conftest.py`
  search above the test's folder (`--confcutdir` = the test's folder;
  without it pytest walks every parent folder, loading any `conftest.py`
  it finds and failing on unreadable entries such as `/mnt/c`), with plugin
  autoloading disabled (`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`) and only
  `pytest_timeout` loaded, and with `timeout_func_only=true`, so the
  per-test timeout covers only the test function. The run timeout still
  bounds everything else.
- Why: the run fits well inside its timeout, behaves the same on any
  machine, and a slow failure report never breaks the run.
- Alternatives: inherit the project's configuration and plugins (most of
  the timeout spent starting); a larger default timeout (hides the
  cause).
- Revisit when: the generated tests need a plugin, e.g. async tests.
- Code: `tools/code_executor.py` (`run_pytest`)

### DEC-156 `run_pytest` reports an unexpected failure as status `error`
- Date: 2026-11-17 · Area: Tools (Lab 3.2) · Status: accepted
- Basis: Preferred; follows DEC-142
- Context: besides passing, failing, not collecting and timing out, pytest
  can fail in ways that say nothing about the code or the tests: an
  internal error, a JUnit report that is missing or unreadable, a process
  that cannot start.
- Decision: those cases return `status="error"` with the output; nothing
  is raised. The QA turns it into a `qa` issue, never a Coder's one.
- Why: the QA cannot claim anything from a run it cannot read, and the
  Coder must not be blamed for it.
- Alternatives: fold them into `collection_error` (the QA would retry a
  draft that was fine); raise (crashes the QA, C4.6).
- Code: `tools/code_executor.py` (`run_pytest`)

### DEC-157 Each generated test is exactly one synchronous function with its own name
- Date: 2026-11-18 · Area: QA Agent (Lab 3.2) · Status: accepted
- Basis: Preferred; refines DEC-148 and DEC-152
- Context: DEC-148 asks that each test's name is defined by its code, and
  DEC-152 that a test's code holds only its function, so the test file
  runs nothing at import time. The isolated pytest loads no asyncio plugin
  (DEC-155).
- Decision: the `code` of each generated test must parse to exactly one
  top-level `def` (not `async def`) whose name is the test's `name`.
  Helpers go in the `preamble`. One rule and one error message cover the
  name, the single statement and the sync check.
- Why: a clear error for the model to correct, and fewer cases to check;
  an async test would never run under the isolated pytest.
- Alternatives: separate checks for each condition (same effect, more
  messages); allow helpers next to each test (code that may run at
  import).
- Code: `agents/qa_agent.py` (`_pytest_draft_schema`)

### DEC-158 Tests are written from the criteria and the code's interface, not its bodies
- Date: 2026-11-18 · Area: QA Agent (Lab 3.2) · Status: accepted
- Basis: Preferred; refines DEC-145 and DEC-148
- Context: the LLM that writes the tests needs the Coder's module, class
  and method names so the imports and calls work. Seeing the bodies, it
  can copy the code's behaviour into the expected values (a tail-append
  `insert` gets a test expecting `[1, 2, 3]`), and a buggy task is
  approved. A test that calls with the wrong type fails inside the test,
  which DEC-152 blames on the Coder.
- Decision: test writing gets, per file, a skeleton extracted with `ast`:
  imports, functions and classes with full signatures (types, defaults),
  decorators, typed class fields, module constants (with their value
  only when it is a simple literal) and docstrings; every body becomes
  `...`. Attributes set inside methods (`self.x = ...`) are left out. A
  file that does not parse is sent as one line saying so. The LLM review
  (T7) gets the whole code.
- Why: the expected values can only come from the criteria; types,
  defaults and decorators prevent malformed calls that would be blamed
  on the Coder.
- Alternatives: the whole code with a stricter prompt (the model still
  sees the bug); no code at all (the model guesses names the task does
  not give, wasting `QA_MAX_ATTEMPTS`).
- Code: `agents/qa_agent.py` (`_interface`, `_render_task`)

### DEC-159 Each test draft is one model call, in one loop for every QA-owned failure
- Date: 2026-11-18 · Area: QA Agent (Lab 3.2) · Status: accepted
- Basis: Preferred; refines DEC-141
- Context: DEC-141 gives one `QA_MAX_ATTEMPTS` budget to invalid drafts
  and to drafts that run but fail by the QA's own fault (DEC-152).
  `structured_call` retries invalid output internally and does not say
  how many calls it spent, so the remaining budget is unknown after it.
- Decision: `write_tests` makes exactly one model call per draft. `run_qa`
  loops at most `QA_MAX_ATTEMPTS` times; any QA-owned failure (a draft
  rejected by the schema, the QA's import mistakes, a collection error or a
  timeout in the test's own code) starts the next call with the error, and
  the previous file when there is one. When the budget runs out, the
  report holds only the `qa` issue "no runnable tests could be produced",
  with no `test` issue from the broken draft.
- Why: one loop and one counter for every QA failure (1 turn = 1 call);
  the corrective feedback is the same for all of them; `llm_helpers` stays
  unchanged. Results of a draft that was itself broken are not trusted.
- Alternatives: count the calls `structured_call` spends (a new helper
  returning the count; two retry mechanisms); report the Coder's failures
  of the broken draft too (mixes results of an untrusted draft).
- Code: `agents/qa_agent.py` (`write_tests`, `_test_task`)

### DEC-160 The LLM review runs after the tests, sees the whole code and has its own budget
- Date: 2026-11-18 · Area: QA Agent (Lab 3.2) · Status: superseded by DEC-174
- Basis: Preferred; refines DEC-137, DEC-139 and DEC-149
- Context: the test-writing call sees only the code's interface
  (DEC-158), so the default fix of a failing test says what failed, not
  where to change the code. DEC-149 gives that job to the LLM review.
- Decision: after the tests, a second model call reviews the whole code
  with the task, the test file and the failures. Its schema, built per
  report, holds exactly one fix per `test` issue (matched by its number
  in the request's list; the real model did not copy location strings)
  and advisory issues that may only be Medium or Low; a missing,
  unknown or repeated fix is a validation error sent back to the model.
  The review's fixes replace the default ones and its issues are added
  with source `review`. It runs only when the report comes from the
  QA's work (tests or the Coder's import problems), not when the report
  is already a `qa` failure. It has its own `QA_MAX_ATTEMPTS` budget
  (worst case 2 test calls and 2 review calls). If it fails, DEC-142
  applies.
- Why: the review never decides approval, so a missing or failing review
  only costs fix quality; its own budget keeps the test calls, which do
  decide, untouched.
- Alternatives: share the test budget (the review would never run after
  a regeneration); review even after a `qa` failure (calls spent on a
  report that cannot be approved).
- Code: `agents/qa_agent.py` (`review_code`, `_code_review_schema`, `run_qa`)

### DEC-161 The QA's pytest run timeout grows with the number of tests
- Date: 2026-11-18 · Area: QA Agent (Lab 3.2) · Status: accepted
- Basis: Preferred; refines DEC-152
- Context: each test has its own timeout (`QA_TEST_TIMEOUT`, 2 s) and the
  run had `EXEC_TIMEOUT` (10 s). When the Coder's `insert` hangs and six
  tests call it, six 2 s timeouts pass 10 s: the run is killed before
  pytest writes its report, every per-test result is lost and the issue
  said the code hangs at import (found by the Lab 3.2 review).
- Decision: `run_qa` gives pytest `EXEC_TIMEOUT + tests × QA_TEST_TIMEOUT`
  seconds, clamped by the sandbox to `MAX_TIMEOUT` (30 s). The total is a
  ceiling: a run that finishes earlier ends earlier. A run that still
  hits it is a `test` High issue worded neutrally ("importing the task's
  code or a test hangs").
- Why: every hanging test is stopped by its own timeout and reported
  with the file and line where it hung, so the Coder gets a precise fix.
  The run is still bounded (C3.1). The Coder's `exec_python` keeps its
  10 s default (C1.3); this only sizes the QA's test run, from
  configurable values, and is documented in the README so it is not
  mistaken for a missing timeout.
- Alternatives: keep `EXEC_TIMEOUT` for the whole run (loses results
  when several tests hang); forbid every expression at import in the
  test file (breaks `parametrize` for a rare case).
- Code: `agents/qa_agent.py` (`_test_task`, `_judge_run`)

### DEC-162 The graded protocol route (C3.5) is A2A
- Date: 2026-11-19 · Area: Protocol (Lab 3.3) · Status: accepted
- Basis: Preferred (C3.5 grades one route; supersedes DEC-123)
- Context: C3.5 accepts MCP (official SDK, a server exposing the
  file-system tools and the Coder as its client) or A2A (Coder/QA messages
  with sender, receiver, intent, payload, correlation_id and intent
  validation). Labs 3.1-3.2 built the MCP server and the QA reads files
  through it; Lab 3.3 builds A2A for the Coder-QA review loop.
- Decision: the Coder-QA review loop exchanges A2A messages (sender,
  receiver, intent, payload, correlation_id, with intent validation). The
  QA keeps reading files through the MCP server (DEC-145); that pathway
  stays but is not the graded route.
- Why: A2A models agent-to-agent dialogue, which is what the review loop
  is; MCP models agent-to-tool access, and through it the agents would
  only communicate indirectly through shared files. The loop has to be
  built anyway, so A2A is its envelope (about 5-6 tasks, one spec) and the
  Coder's Module 1 tools stay untouched.
- Alternatives: the MCP route, with the Coder as an MCP client (a second
  spec of about 8-9 tasks in total, changes code already Met under C1.3
  and C1.5, and the review messages would still travel outside the
  protocol).
- Code: —

### DEC-163 The QA reviews each task in its own bounded loop
- Date: 2026-11-19 · Area: Coder-QA loop (Lab 3.3) · Status: accepted
- Basis: Required (C3.3: limit from an environment variable, default 5,
  never exceeded); per task and counted in QA reviews — Preferred
- Context: the Coder runs the PM's tasks one by one and the QA reviews one
  task (Lab 3.2). The evaluator forces the limit and counts the rounds
  ("the limit was five, but the run started a sixth" is Not Yet).
- Decision: after the Coder finishes a task, the QA reviews it, and the
  task goes back to the Coder until the QA approves it or the limit is
  reached; only then does the next task start. One iteration is one QA
  review (n = 1 is the first). The limit, `QA_MAX_ITERATIONS` (default 5),
  applies to each task: if review n = limit is not approved, the task
  closes and no review n + 1 starts.
- Why: defects are fixed before other tasks build on them, each A2A
  exchange is about one task, and the QA works as built in Lab 3.2. A
  limit for the whole run would run out after one or two tasks.
- Alternatives: review the whole project at the end (failures found when
  later tasks already depend on them); one limit for the whole run.
- Code: —

### DEC-164 A task that ends the loop unapproved stays failed and the run goes on
- Date: 2026-11-19 · Area: Coder-QA loop (Lab 3.3) · Status: accepted
- Basis: Preferred; confirms DEC-097 now that the QA loop exists
- Context: DEC-097 asked to be revisited when Module 3 added the QA loop.
  A task can reach the review limit with failures while later tasks remain.
- Decision: the task is marked `failed` with its report of unresolved
  issues, and the next task starts. Nothing goes back to the PM:
  re-planning is IMP-018.
- Why: tasks that do not depend on the failed one still get done, and the
  QA of later tasks catches what breaks because of it. No lab or criterion
  asks for re-planning, which would open a second loop to bound.
- Alternatives: stop the run at the first failed task (saves tokens,
  leaves independent tasks unattempted); send the task back to the PM
  (IMP-018).
- Code: —

### DEC-165 A run ends `success` only if the QA approved every task
- Date: 2026-11-19 · Area: Coder-QA loop (Lab 3.3) · Status: accepted
- Basis: Required (C3.3: never claim success with unresolved failures;
  the README must say how to tell both outcomes apart); exit code —
  Preferred
- Context: the evaluator forces a run that does not converge and checks
  that it is not reported as a success.
- Decision: every run ends with an overall status: `success` when the QA
  approved every task, `unresolved` otherwise. An `unresolved` run comes
  with a final report listing each unapproved task, its blocking issues
  and the review it stopped at. `main.py` prints it and exits with a
  non-zero code unless the status is `success`.
- Why: one field says the outcome, the report says what is left, and the
  exit code makes it visible the same way in logs, Docker and scripts.
- Alternatives: only per-task statuses (the reader must work out the
  outcome); exit code 0 always (a failed run looks fine to a script).
- Code: —

### DEC-166 Every LLM call has its own timeout
- Date: 2026-11-19 · Area: LLM client (Lab 3.3) · Status: accepted
- Basis: Preferred
- Context: `ChatOpenAI` uses the OpenAI SDK's default timeout of 600 s,
  and nothing bounds a whole run. With the QA loop a run makes many more
  calls, so one call that hangs can stall the demo or the container for
  ten minutes.
- Decision: each LLM call gets a timeout, configurable through
  `LLM_TIMEOUT`, set now instead of in Module 4. Retries and the circuit
  breaker stay for Module 4 (C4.2, C4.3).
- Why: a small change that bounds the slowest piece of the loop; the
  value is configured, not hard-coded.
- Alternatives: wait for Module 4 (runs can hang until then).
- Code: `llm_client.py` (`get_chat_model`), `orchestration/settings.py`

### DEC-167 The Coder critiques each submission once and revises only real bugs
- Date: 2026-11-19 · Area: Coder self-reflection (Lab 3.3) · Status: superseded by DEC-172
- Basis: Required (C3.4: a self-critique after generating and before QA,
  with the revised artifact sent to QA); the shape of the step — Preferred
- Context: C3.4 is Not Yet when the critique is only logged or causes no
  revision. Forcing the model to always find something would make it
  invent defects.
- Decision: before every submission to the QA, after the Coder's ReACT
  pass, one structured LLM call without tools critiques the result. It
  sees the code, the task and its criteria, and the `plan`,
  `explanation` and `result` of the `Finish`, but not the ReACT trace. It
  lists the edge cases it checked, each `ok` or `bug` with its reason. If
  any is a `bug`, a second ReACT pass of the Coder (up to 10 calls) gets
  those bugs, the task with its criteria and the current files, and fixes
  only them; its output goes to the QA with no second critique. If all
  are `ok`, the code goes to the QA unchanged and the log says so. This
  holds for every submission, also after a pass that hit its 10 calls
  (what is on disk is critiqued and sent).
- Why: the `explanation` carries the reasons behind each choice without
  the noise of every tool call, and re-reading its own full reasoning
  tends to make a model agree with itself. A ReACT revision runs the
  fixed code before it is sent, so `result` still comes from a real run
  (C1.5). One critique per submission, without exceptions, is easy to
  check in the log and cannot loop.
- Alternatives: the critique sees only the code (misses deliberate
  choices) or the whole trace (many tokens, self-confirming); a single
  LLM call rewrites the code (sent to QA without ever running); the
  critique must always find something (invented defects); skip the
  critique after a pass that hit its limit (a submission without
  reflection, a gap for C3.4).
- Code: —

### DEC-168 A run has a time budget checked between steps
- Date: 2026-11-19 · Area: Coder-QA loop (Lab 3.3) · Status: accepted
- Basis: Preferred
- Context: every piece is bounded, but the sum is not: a run of 8 tasks
  that never converge could take about four hours.
- Decision: `RUN_TIMEOUT` (default 30 min) is checked between graph
  steps. Once it is spent, the remaining tasks close as `failed` with the
  reason "out of time" and the run ends `unresolved` with its report
  (DEC-165). A step that has started is not interrupted.
- Why: a clean, reported exit with little code. The run can overshoot
  the budget by at most the step in progress.
- Alternatives: no total budget (runs of hours); cancel the step in
  progress (half-written files, harder to report).
- Code: —

### DEC-169 A failure of the QA itself is retried once and never charged to the Coder
- Date: 2026-11-19 · Area: Coder-QA loop (Lab 3.3) · Status: accepted
- Basis: Preferred
- Context: when the QA cannot do its job (the MCP server does not start,
  its model returns nothing valid), its report holds only `qa` issues,
  whose fix says there is nothing for the Coder (DEC-142). Sent back as a
  `fix_instruction`, it would spend the Coder's reviews on nothing.
- Decision: a report whose issues are all `qa` repeats the QA review once,
  on the same code, without a Coder pass and without counting as a
  review. If it fails again, the task closes `failed` with the reason
  "the QA could not review it", not blamed on the Coder.
- Why: a transient failure (e.g. the MCP server starting slowly) gets a
  second chance, and the Coder's budget goes only to its own defects.
- Alternatives: count it as a review (wastes the Coder's budget); retry
  until it works (unbounded).
- Code: —

### DEC-170 An invalid A2A message closes its task as a protocol error
- Date: 2026-11-19 · Area: A2A (Lab 3.3) · Status: accepted
- Basis: Required (C3.5: intent validation); what happens next —
  Preferred
- Context: A2A messages are built by our code, not by an LLM. An unknown
  intent, an unknown agent, `sender == receiver` or a reply whose
  `correlation_id` does not match the request is a bug.
- Decision: the message is rejected and never acted on, the error is
  logged at ERROR, and its task closes `failed` with a protocol-error
  issue. The run goes on with the next task (DEC-164). No retry.
- Why: a deterministic bug gives the same message again, so a retry
  wastes time; closing only the task keeps the rest of the run.
- Alternatives: retry the exchange (same result); stop the whole run
  (loses independent tasks).
- Code: —

### DEC-171 A critique with no valid output lets the code go to QA as it is
- Date: 2026-11-19 · Area: Coder self-reflection (Lab 3.3) · Status: accepted
- Basis: Preferred
- Context: the critique is an LLM call validated with Pydantic; it can
  fail to give a valid output.
- Decision: the critique gets one corrective retry (two calls, as the PM).
  If it is still invalid, the code on disk goes to the QA unchanged and
  the log notes "critique unavailable".
- Why: the QA still checks the code with executed tests, and the
  evaluator sees the critique in every other submission. Failing the
  task instead would punish the Coder for a problem of the critique.
- Alternatives: fail the task (loses a task that may be correct); retry
  more times (more cost for a rare case).
- Code: `agents/coder_reflection.py` (`evaluate_version`)

### DEC-172 Self-reflection scores each version with a rubric and sends the best
- Date: 2026-11-19 · Area: Coder self-reflection (Lab 3.3) · Status: accepted (context superseded by DEC-173; items, score and trigger by DEC-182)
- Basis: Required (C3.4: a self-critique after generating and before QA
  that drives a revision); the rubric, the score and the best-of choice —
  Preferred
- Context: the self-critique cycle is generate, evaluate, reflect,
  improve and evaluate again. DEC-167 merged evaluate and reflect and sent
  the improved code without checking it, so an improvement that made the
  code worse went to the QA.
- Decision: after the Coder's ReACT pass (generate), one structured LLM
  call without tools evaluates the version against a rubric and reflects
  on it, with the context of DEC-167 (code, task and criteria, `plan`,
  `explanation`, `result`; no ReACT trace). The rubric has one item per
  acceptance criterion of the task plus a fixed list of edge cases; each
  item is `ok`, `bug` or `n/a` with brief evidence (evaluate), and each
  `bug` gets its cause and a fix plan (reflect). The code computes the
  score from the verdicts, not the LLM: criteria `ok` count 2 points,
  edge cases `ok` 1 point, `n/a` nothing; score = points ok / applicable
  points. If every item is `ok`, the version goes to the QA. Otherwise a
  ReACT pass (improve) gets the reflection of the best version so far,
  the task with its criteria and the current files, and fixes only those
  bugs; the new version is evaluated the same way. This repeats up to
  `REFLECTION_MAX_ROUNDS` improvements (default 1). Each version's files
  and `CoderResult` are kept; the version with the highest score is
  restored on disk and sent to the QA, the improved one on a tie. Each
  improvement starts from the best version so far and also gets the
  regressions of the last discarded attempt (items `ok` before and `bug`
  after) with its `explanation`. A pass that hit its 10 calls is evaluated
  like any other (DEC-167); an evaluation with no valid output follows
  DEC-171.
- Why: separate evaluate and reflect sections keep the verdict apart
  from the diagnosis in one call; a score computed from verdicts is
  reproducible, while a number asked from the LLM is not. Keeping the
  best version means an improvement that made things worse never reaches
  the QA; the improved code was still produced and judged from the
  critique. The regressions stop a new round from repeating a change that
  already failed. One round by default because the QA follows with
  executed tests; the cost per submission is up to 26 Coder calls.
- Alternatives: always send the improved version (a worse version can
  reach the QA); a score given by the LLM (arbitrary, varies between
  calls); evaluate and reflect in two calls (double cost, the second
  rephrases the first); restart from the best version with no lesson (it
  tends to repeat the same failing change).
- Revisit when: the rubric items and the critique prompt are designed
  (end of the Lab 3.3 technical phase).
- Code: —

### DEC-173 The self-evaluation sees only the version and its task, with no memory
- Date: 2026-11-19 · Area: Coder self-reflection (Lab 3.3) · Status: accepted
- Basis: Preferred; replaces the context part of DEC-172
- Context: DEC-172 gave the evaluate-and-reflect call the code plus the
  `plan`, `explanation` and `result` of the ReACT pass, so the critique
  would not flag a deliberate choice as a bug. With a rubric built from
  the acceptance criteria, the criteria define what is correct, not the
  Coder's reasons. The Coder's memory also carries the pass: the window
  holds its whole trace and Chroma its `explanation` (`store_outcome`).
- Decision: the call receives only the version's files and the task with
  its acceptance criteria (which come from the PM, not from ReACT). No
  `plan`, `explanation` or `result`, and no memory: neither the window
  nor Chroma. The Coder's ReACT calls (plan and every pass) keep using
  both memory layers as before.
- Why: an evaluator that does not read the author's reasoning judges what
  is there instead of agreeing with it, like an external reviewer.
  Without memory the trace cannot come back through the window or
  Chroma. The PM and the QA already call the LLM without memory.
- Alternatives: the context of DEC-172 (the evaluation is anchored on the
  author's reasoning); memory through `build_context` (brings the trace
  back).
- Risk: C1.2 says Chroma is queried before every LLM call. It is read as
  the Coder's ReACT agent, which still queries it on every call; this
  evaluator call is documented in the README as the exception and why.
- Code: `agents/coder_reflection.py` (`evaluate_version`)

### DEC-174 Every QA issue comes from an executed test; the LLM only explains failures
- Date: 2026-11-19 · Area: QA Agent (Lab 3.3) · Status: accepted
- Basis: Required (C3.1: real tests decide; fix instructions linked to
  failing assertions); dropping the advisory review — Preferred
- Context: the QA's LLM review (DEC-160) did two jobs: it turned each
  failing test into a fix that says where to change the code, and it
  added advisory Medium or Low issues of its own (DEC-139). With the
  Coder's rubric evaluation before the QA (DEC-172), the advisory issues
  repeat an LLM opinion, and in a `fix_instruction` they can make the
  Coder spend reviews on remarks no test supports.
- Decision: the review call runs only when some test failed, and it only
  writes one fix per failure (the matching and validation of DEC-160 are
  kept). It never adds issues. Every issue therefore comes from an
  executed test or from the QA's own failure (`qa`), and all are High.
  `QA_BLOCKING_SEVERITY` and the `review` issue source are removed;
  `severity` stays in `Issue` (the lab's schema). A task is approved
  when its tests ran and all passed (as DEC-139 with its default).
- Why: approval and feedback rest only on executed evidence, the LLM
  opinion lives in one place (the Coder's self-evaluation), and an
  approved review makes no extra model call. The fix of each failure
  keeps saying where to change the code, which the test alone cannot.
- Alternatives: keep the review as it is (duplicated opinion, noise in
  the fixes); drop the review entirely (the Coder gets only what failed
  and spends ReACT calls finding where).
- Code: `agents/qa_agent.py` (`review_code`, `CodeReviewBase`, `run_qa`), `orchestration/qa_report.py`

### DEC-175 A2A messages travel in a mailbox inside the shared state
- Date: 2026-11-19 · Area: A2A (Lab 3.3) · Status: accepted
- Basis: Required (C3.5: sender, receiver, intent, payload,
  correlation_id and intent validation; C2.3: one orchestration graph);
  the mailbox — Preferred
- Context: the lab's `Broker` keeps one asyncio queue per agent and runs
  the Coder and the QA as concurrent tasks outside any graph. Our agents
  run as nodes of one LangGraph graph (C2.3), and the evaluator checks
  the messages in the run's logs.
- Decision: `orchestration/a2a.py` defines `A2AMessage` (Pydantic:
  `sender`, `receiver`, `intent`, `payload: dict`, `correlation_id`,
  UUID4 by default) with its validation: known agents and intent,
  `sender != receiver`, an intent the receiver accepts, a reply that
  carries its request's `correlation_id`, and a payload validated by one
  Pydantic model per intent. `ProjectState.messages` is an append-only
  list of messages. Nodes use only `send` and `inbox` from that module;
  every message is logged at INFO with sender, receiver, intent, task,
  review and correlation id.
- Why: everything stays inside the graph and in the final state, which
  is JSON-serializable, so the message history itself is C3.5 evidence.
  The append reducer also merges messages from parallel branches, and
  with nodes going only through `send` and `inbox`, a queue or network
  transport could replace the state later without touching the agents.
- Alternatives: the lab's asyncio `Broker` (outside the graph, harder to
  test, messages not in the state); a synchronous broker in the run
  context (messages not in the state or the traces).
- Code: `orchestration/a2a.py` (`A2AMessage`, `send`, `inbox`), `ProjectState.messages`

### DEC-176 The QA answers each review request with one of three intents
- Date: 2026-11-19 · Area: A2A (Lab 3.3) · Status: accepted
- Basis: Required (C3.3: at the limit the QA returns a final report of
  unresolved issues); the extra intent — Preferred
- Context: the lab has `review_request`, `fix_instruction` and
  `approved`. C3.3 asks the QA itself for the final report when the
  limit is reached.
- Decision: the Coder sends `review_request` with the task, the review
  number n and the limit. The QA answers `approved` (tests ran and all
  passed), `fix_instruction` (tests failed and reviews are left; the
  payload is the report with one fix per failing test) or `unresolved`
  (review n = limit not approved, or the QA failed twice as in DEC-169;
  the payload is the final report). The router maps them to done, back
  to the Coder and failed.
- Why: the final report comes from the QA, as C3.3 says, and the router
  needs no counting of its own. The rubric grades the guide's fields, not
  a closed list of intents.
- Alternatives: the lab's three intents with the router counting n (the
  final report would not come from the QA).
- Code: `orchestration/a2a.py` (`ACCEPTED_INTENTS`, payload models)

### DEC-177 Self-reflection is its own graph node between the Coder and the QA
- Date: 2026-11-19 · Area: Coder self-reflection (Lab 3.3) · Status: accepted (code location superseded by DEC-192)
- Basis: Preferred (C3.4 asks for evidence that reflection runs before QA)
- Context: the cycle of DEC-172 could run inside the Coder node or as a
  node of its own.
- Decision: the graph runs `coder → reflect → qa`. The `reflect` node
  runs DEC-172 (evaluate and reflect, improve, evaluate the improvement,
  keep the best version and restore it on disk). Its code lives in
  `agents/coder_agent.py`, since the guide places reflection inside the
  Coder agent.
- Why: the order is part of the graph's structure, so reflection before
  QA is visible without reading code; the node is tested on its own and
  gets its own span in Module 4.
- Alternatives: inside the Coder node (the order is hidden and the node
  grows).
- Code: —

### DEC-178 With the QA in the graph, only the QA's verdict closes a task
- Date: 2026-11-19 · Area: Coder-QA loop (Lab 3.3) · Status: accepted
- Basis: Required (C2.2: status of each task in shared state; C3.2: done
  means the QA approved it); the fields — Preferred; supersedes DEC-101
  for the team graph
- Context: DEC-101 closes the task in the Coder's step: `done` when the
  Coder's result is `success`. With a QA loop, `done` must mean approved
  by the QA, and the task must survive several Coder passes.
- Decision: in the team graph the Coder leaves its task `in_progress`;
  the router closes it `done` or `failed` from the QA's answer.
  `TaskState` gains `reviews` (n) and `qa_report` (the last report). The
  Coder-only graph of Lab 2.2 (`build_coder_graph`) keeps DEC-101 through
  a parameter of the node, so its behavior and tests do not change.
- Why: each task's state shows where it is in the loop, and nothing is
  marked done before the QA approves it.
- Alternatives: keep DEC-101 and add a separate approval flag (two
  sources of truth for one status).
- Code: —

### DEC-179 The QA node runs the async QA to completion inside the sync graph
- Date: 2026-11-19 · Area: Coder-QA loop (Lab 3.3) · Status: accepted
- Basis: Preferred
- Context: `run_qa` is async (MCP client, DEC-150); the graph runs with
  the synchronous `stream`.
- Decision: the `qa` node is synchronous and calls
  `asyncio.run(run_qa(...))`. The single retry of DEC-169 lives in this
  node. The graph stays sequential: while the QA reviews a task, nothing
  else runs, and the next task starts only after the verdict (DEC-163).
- Why: no event loop is running inside a synchronous graph run, so
  `asyncio.run` is safe; the rest of the system does not change.
- Alternatives: make the whole graph async (`astream`): touches `run()`,
  `main.py` and the tests of Modules 1-2 for no graded gain. An async
  pipeline is IMP-019.
- Code: —

### DEC-180 Loop settings are read per run, a timeout node closes the run, and the step limit follows the loop
- Date: 2026-11-19 · Area: Coder-QA loop (Lab 3.3) · Status: accepted
- Basis: Required (C3.3: the limit is configurable through an environment
  variable); the rest — Preferred; supersedes DEC-115
- Context: the loop adds `QA_MAX_ITERATIONS` (DEC-163), `RUN_TIMEOUT`
  (DEC-168), `LLM_TIMEOUT` (DEC-166) and `REFLECTION_MAX_ROUNDS`
  (DEC-172). DEC-115's step limit (`1 + MAX_TASKS + 2`) counted one step
  per task. A router cannot change the state, so it cannot close the
  remaining tasks when time runs out.
- Decision: the settings are read and validated when each run starts, so
  tests and the evaluator can change them. `ProjectState.deadline` holds
  the absolute end time; the routers send the run to an `out_of_time`
  node once it has passed, which closes the remaining tasks `failed`
  ("out of time") and ends the run. `LLM_TIMEOUT` goes to
  `ChatOpenAI(timeout=...)`. The step limit is computed per run as
  `1 + MAX_TASKS × QA_MAX_ITERATIONS × 3 + 3` (PM; coder, reflect and qa
  per review; `out_of_time` and margin); reaching it still returns the
  last state with `error` set, as DEC-115.
- Why: the cut-off is visible in the graph and reported like any other
  ending; the step limit stays a guard against routing bugs whatever
  limit the user configures.
- Alternatives: read the settings at import (tests cannot change them);
  check the deadline only in `run()` (cannot close the tasks inside the
  graph); keep DEC-115's formula (the loop would hit it on the first
  task).
- Code: —

### DEC-181 The run's outcome is a computed field and the verdict names unresolved runs
- Date: 2026-11-19 · Area: Coder-QA loop (Lab 3.3) · Status: accepted
- Basis: Required (C3.3, DEC-165); the form — Preferred; supersedes DEC-111
- Context: DEC-111 already exits 0 only when every task is done and there
  is no error, with the verdict `RESULT: incomplete`. DEC-165 names the
  outcomes `success` and `unresolved` and asks for a final report.
- Decision: `ProjectState.outcome` is a computed field (`success` or
  `unresolved`), so it is also in `--json`. `final_report()` lists each
  unapproved task with its blocking issues, the review it stopped at and
  why (limit, QA failure, protocol error, out of time). `main.py` prints
  `RESULT: success`, `RESULT: unresolved — …` with the report, or
  `RESULT: error — …` for a fatal error; exit codes stay 0, 1 and 2.
- Why: one field and one verdict word match the README; computed, it can
  never disagree with the task statuses.
- Alternatives: a stored status field (can drift from the tasks); keep
  "incomplete" (a different word from the one documented).
- Code: —

### DEC-182 The self-evaluation rubric: fixed items, defect kinds and a strict ranking
- Date: 2026-11-19 · Area: Coder self-reflection (Lab 3.3) · Status: accepted
- Basis: Preferred; replaces the items, score and trigger of DEC-172
- Context: DEC-172 left the rubric's items for later and scored versions
  with 2 points per criterion and 1 per edge case. A severity chosen
  freely by the LLM varies between calls, so two versions could not be
  compared; a severity tied to the item misjudges a crash found under an
  edge case. The course's critique prompt adds security, types and
  severity levels, but sees no task and asks to catch every exception.
- Decision: the rubric checks one item per acceptance criterion of the
  task (C0..Cn, never `n/a`) plus a fixed list: E1 empty input, E2 one
  element and boundaries, E3 repeated values, E4 invalid input and
  errors (as the task says, with a clear message, no broad `except`
  hiding failures), E5 interface (files, names and signatures as in the
  task), E6 state consistent across calls, E7 safe import and
  termination, E8 security (paths, injection, credentials; `n/a`
  without files, network or processes), E9 type annotations on public
  functions, E10 style, naming and docstrings, and E11 any other real
  defect that fits none of the above (a file never closed, a behaviour
  the description asks for but no criterion checks). Each item gets `ok`, `bug`
  or `n/a` with evidence; a `bug` needs a concrete input and the wrong
  result traced through the code. Each `bug` names its defect kind from
  a closed list, and the code maps the kind to a severity: High for
  `logic_error`, `crash` (exception, hang or endless loop on valid
  input) and `security`; Medium for `missing_edge_case` and
  `unclear_error`; Low for `missing_type_annotation`, `style`, `naming`
  and `docstring`. Versions are ranked by their bug counts compared in
  order (High, then Medium, then Low): one High is worse than any number
  of Medium, one Medium worse than any number of Low; on a tie the
  improved version wins. Only a High or Medium bug starts an improvement
  pass; Low bugs count in the ranking and stay in the record.
- Why: the items make every evaluation look at the same things; picking
  a kind from given definitions is steadier than inventing a severity,
  so the ranking of two versions is reproducible. A strict order means
  no pile of minor remarks can outweigh a crash. Type annotations, style
  and docs are not tested by the QA, so they never cost an improvement
  pass of up to 11 calls.
- Alternatives: severity by item (a crash under E1 would be Medium);
  severity chosen by the LLM (varies between calls); weighted points
  3/2/1 (enough Medium bugs would outweigh a High); missing annotations
  as Medium (an improvement pass for a cosmetic gap); the course prompt as
  is (no task given to check correctness against, and catching every
  exception hides bugs and breaks tasks that must raise).
- Code: `agents/coder_reflection.py` (`RUBRIC_ITEMS`, `KIND_SEVERITY`, `best_version`)

### DEC-183 Every bug of the self-evaluation gets a diagnosis with a minimal fix
- Date: 2026-11-19 · Area: Coder self-reflection (Lab 3.3) · Status: accepted
- Basis: Preferred (the "reflect" step of DEC-172)
- Context: the evaluation says what is wrong; the improvement pass needs
  to know why and what to change, or it has to guess. Low bugs do not
  start an improvement (DEC-182), but later passes can still learn from
  them.
- Decision: the same call that evaluates writes one diagnosis for every
  `bug`, Low ones included, with `item` (rubric item), `kind` (defect
  kind, DEC-182), `location` (function and file), `evidence` (concrete
  input and wrong result), `cause` (why it fails) and `fix` (the
  smallest change that fixes it, not a rewrite, and never against
  another criterion of the task). The code checks there is exactly one
  diagnosis per `bug` and none for `ok` or `n/a` items; an invalid output
  follows DEC-171.
- Why: a cause and a minimal fix let the improvement pass change only
  what is broken, which protects what already worked (the ranking of
  DEC-182 penalises regressions). Diagnosing every bug in the same call
  costs few tokens and keeps the Low ones available to later passes.
- Alternatives: diagnose only High and Medium (Low bugs lost for later
  passes); a free-form critique text (cannot be checked or matched to
  the rubric).
- Code: `agents/coder_reflection.py` (`Bug`, `ItemVerdict`)

### DEC-184 Each task keeps an explicit review history in the state
- Date: 2026-11-20 · Area: Coder-QA loop (Lab 3.3) · Status: accepted
- Basis: Preferred
- Context: from the second pass on, the Coder must know what was already
  tried on the task and what failed, so it does not repeat a failed
  approach. Memory cannot give this reliably: the sliding window
  (DEC-057) drops older passes (two passes per review), and Chroma
  recalls by similarity, not by order.
- Decision: `TaskState.history` holds one record per review: the
  `explanation` of the version sent, the self-evaluation result (bugs per
  severity, version chosen) and the QA result (passed and failed tests,
  with name and criterion). Every pass after the first renders it as a
  "Background" section of its prompt, and marks a test that fails again
  ("fails for the 2nd time"). It is task-scoped working state, not a
  third memory layer: it is deterministic and lives in the typed state.
- Why: a complete, ordered summary of the task's attempts at a fixed,
  small cost; it is also the evidence for C3.2 and the source of the
  final report (DEC-181).
- Alternatives: rely on the window and Chroma only (loses early reviews,
  no order); pass the previous ReACT traces (many tokens, mostly noise).
- Code: —

### DEC-185 The sliding window keeps whole passes during the loop
- Date: 2026-11-20 · Area: Coder memory (Lab 3.3) · Status: accepted
- Basis: Provisional
- Context: each ReACT pass enters the window as one turn with its full
  trace (DEC-057, DEC-077), and the window is injected before every Coder
  LLM call. In the loop this costs many tokens and pushes earlier tasks
  out of the window sooner.
- Decision: no change. The window keeps whole passes during the loop;
  the history of DEC-184 covers what the window drops.
- Why: changing the turn format touches a Required decision of Module 1
  and its C1.2 evidence, with a regression risk; the cost is better
  judged in Module 4 with tracing and cost reports.
- Alternatives: compact turns (pass prompt plus final summary, no tool
  calls), recorded as IMP-020.
- Revisit when: Module 4 (C4.4) shows the window is a large share of the
  Coder's prompt tokens.
- Code: —

### DEC-186 Chroma keeps working in the loop; the self-evaluation and the QA use no memory
- Date: 2026-11-20 · Area: Coder memory (Lab 3.3) · Status: accepted
- Basis: Preferred
- Context: in the loop the Coder runs several passes per task, and two
  new steps call the LLM outside the Coder's ReACT pass: the
  self-evaluation and the QA.
- Decision: every Coder pass keeps storing its prompt and outcome in
  Chroma and querying it before each call, as today (DEC-031 still keeps
  the current prompt from coming back). The self-evaluation (DEC-173)
  neither reads nor writes memory: no window turn, nothing stored in
  Chroma. The QA keeps no memory, as in Lab 3.2. The QA's lessons reach
  Chroma only through the Coder's correction prompts, which carry the
  `fix_instruction`.
- Why: correction prompts hold the QA's lessons, so a later task can
  recall them ("reverse failed with one element in task_1") with no new
  code. Keeping the self-evaluation out of memory stops its opinions from
  leaking into the Coder's context.
- Alternatives: store the self-evaluation in Chroma (unverified opinions
  as memories); give the QA its own memory (not required, more state).
- Code: —

### DEC-187 What each Coder pass receives in its prompt
- Date: 2026-11-20 · Area: Coder-QA loop (Lab 3.3) · Status: accepted
- Basis: Preferred
- Context: the loop has three kinds of ReACT pass: the first one (n = 1),
  the improvement pass after the self-evaluation (DEC-172) and the
  correction pass after a `fix_instruction` (DEC-176). Each needs a
  different "what to fix", and all of them need to know the current
  code. The Coder cannot read `workspace_qa/` (DEC-154).
- Decision: every pass gets the project, the task and its criteria, and
  the current contents of the task's planned files that already exist
  on disk (capped like the read tool, DEC-041, and marked as truncated
  past the cap); other files written in the run stay listed by name
  only. Passes after the first also get the history of DEC-184. The
  improvement pass gets, as what to fix, the High and Medium bugs with
  their diagnosis (DEC-183) and the regressions of a discarded attempt
  (DEC-172), and, in the background, the Low bugs ("fix only if trivial
  and safe"). The correction pass gets, as what to fix, the failed tests
  (name, criterion, error, the QA's fix and the test's source, which the
  QA puts in the `fix_instruction` payload), and, in the background, the
  Medium and Low bugs left by the last self-evaluation. The prompt lists
  what to fix before what is pending.
- Why: one rule for file contents, with no special case for the first
  pass, saves the 1–2 read calls of the 10 the pass has (C1.4), also when
  another task already wrote the file. The test source tells the Coder
  what is expected so it can reproduce the failure. Putting pending bugs
  after the main fix lets the Coder learn from Medium and Low bugs
  without losing focus.
- Alternatives: file contents only from the second pass on (the Coder
  reads by hand what an earlier task wrote); no test source (the Coder
  guesses the expected behaviour from the assertion message).
- Code: —

### DEC-188 The QA report models live in their own module
- Date: 2026-11-20 · Area: A2A (Lab 3.3) · Status: accepted
- Basis: Provisional
- Context: the `fix_instruction`, `approved` and `unresolved` payloads
  carry a `QAReport`, which lived in `orchestration/state.py`, while
  `ProjectState` needs `A2AMessage` for its mailbox (DEC-175). Each
  module would import the other.
- Decision: `Severity`, `Issue`, `QAReport` (and the `NonEmptyStr` type
  they use) move unchanged to `orchestration/qa_report.py`. Both
  `state.py` and `a2a.py` import them from there, and `state.py`
  re-exports them, so existing imports keep working.
- Why: a move with no change of behaviour breaks the cycle and keeps the
  report fully validated inside each message.
- Alternatives: the report as an unvalidated `dict` (an invalid report
  could reach the Coder, against C1.3); import `a2a` at the end of
  `state.py` and rebuild the model (works or fails depending on which
  module is imported first).
- Revisit when: the shared models are gathered in one `models.py`
  (IMP-008).
- Code: `orchestration/qa_report.py`, `orchestration/state.py`

### DEC-189 A message validates itself; `send` checks it answers the open request
- Date: 2026-11-20 · Area: A2A (Lab 3.3) · Status: accepted
- Basis: Required (C3.5: intent validation; C1.3: validate before
  acting); the split — Preferred
- Context: some checks depend only on the message (agents, intent,
  payload) and one depends on the conversation (a reply must carry the
  correlation id of its request). The guide asks for `payload` as a
  dict.
- Decision: `A2AMessage` validates its own fields: known agents and
  intent, `sender != receiver`, an intent the receiver accepts, and a
  payload that its intent's model accepts, with a report consistent with
  the intent (approved for `approved`, not approved for
  `fix_instruction` and `unresolved`). The payload is stored as the
  model's JSON dump, so the state stays serializable; `payload_model()`
  rebuilds the typed payload. `send(state, message)` also checks that a
  reply carries the correlation id of the last `review_request` its
  receiver sent and that request has no reply yet; otherwise it raises
  `A2AProtocolError` and the message never enters the state.
- Why: a message alone cannot know which request is open; the state can.
  Storing the dump keeps the guide's dict field and the C2.2 JSON round
  trip, while no payload reaches a node without validation.
- Alternatives: keep the typed model in `payload` (not the guide's dict;
  JSON round trip needs a discriminator); check correlation in each node
  (repeated, easy to forget).
- Code: `orchestration/a2a.py` (`A2AMessage`, `payload_model`, `send`)

### DEC-190 Loop settings share one integer reader; the model cache keys on the timeout
- Date: 2026-11-20 · Area: Configuration (Lab 3.3) · Status: accepted
- Basis: Preferred
- Context: the loop adds `QA_MAX_ITERATIONS`, `RUN_TIMEOUT`, `LLM_TIMEOUT`
  and `REFLECTION_MAX_ROUNDS` (DEC-180). The QA already reads integer
  settings with a private helper. `get_chat_model` caches one model per
  id, so a timeout read inside it would stay fixed after the first call.
- Decision: `orchestration/settings.py` holds `LoopSettings`,
  `load_loop_settings(env)` and `int_setting`, moved from the QA, which
  now imports it. Every value is an integer with a minimum of 1 and no
  maximum; timeouts are in seconds. `get_chat_model(model)` reads and
  validates `LLM_TIMEOUT` on every call and caches one model per
  `(model, timeout)` pair.
- Why: one reader keeps the same checks and error messages everywhere;
  keying the cache on the timeout makes a changed `LLM_TIMEOUT` apply to
  the next run without changing the callers.
- Alternatives: copy the reader (two versions to keep in step); pass the
  timeout from each agent (three callers and their tests change for the
  same result).
- Code: `orchestration/settings.py`, `llm_client.py`

### DEC-191 A failing test's issue carries the test's code; an old threshold only warns
- Date: 2026-11-21 · Area: QA Agent (Lab 3.3) · Status: accepted
- Basis: Preferred
- Context: the correction pass gets the source of each failing test
  (DEC-187), since the Coder cannot read `workspace_qa/` (DEC-154); the
  report only knew the test's name. DEC-174 removes
  `QA_BLOCKING_SEVERITY`, which existing `.env` files may still set.
- Decision: `Issue` gains `test_code`, the failing test function as
  written, decorators included, taken with `ast` from the QA's test file
  (a parametrized `test_x[case]` is looked up as `test_x`); empty for
  every other issue. The field is not called `test_source` because
  `source` already names the issue's origin. When `QA_BLOCKING_SEVERITY`
  is set, the QA logs a WARNING that it is no longer used and goes on.
- Why: a few lines per failure tell the Coder exactly what is expected,
  without the passing tests. A threshold only changed how strict the
  verdict was, never where anything is written, so a warning is enough
  (unlike `WORKSPACE_DIR`, DEC-151).
- Alternatives: send the whole test file (noise, repeats passing tests);
  raise on the old variable (stops runs for a harmless leftover).
- Code: `orchestration/qa_report.py` (`Issue.test_code`),
  `agents/qa_agent.py` (`_judge_run`, `load_qa_settings`)

### DEC-192 Self-reflection code lives in `agents/coder_reflection.py`
- Date: 2026-11-21 · Area: Coder self-reflection (Lab 3.3) · Status: accepted
- Basis: Preferred; supersedes the code location of DEC-177
- Context: DEC-177 put the `reflect` node's code in `agents/coder_agent.py`
  because the guide places reflection inside the Coder agent. That file
  already has about 880 lines, and the rubric, prompt, models and node add
  about 400 more.
- Decision: the self-evaluation and the `reflect` node live in
  `agents/coder_reflection.py`, a module of the Coder agent called from
  its graph node. The graph order of DEC-177 does not change.
- Why: the name shows it belongs to the Coder, and it can be read and
  tested on its own.
- Alternatives: keep everything in `coder_agent.py` (one file near 1,300
  lines).
- Code: `agents/coder_reflection.py`

### DEC-193 The self-evaluation schema is built per task and an item may hold several bugs
- Date: 2026-11-21 · Area: Coder self-reflection (Lab 3.3) · Status: accepted
- Basis: Preferred (shape of DEC-182 and DEC-183)
- Context: one rubric item can fail in more than one place (E2 may break
  `reverse` with one element and `delete` of the last node). The valid
  items depend on the task's criteria.
- Decision: each item verdict has `item`, `verdict` (`ok`, `bug` or
  `n/a`), a brief `evidence` and a list of `bugs`; a `bug` item holds at
  least one, `ok` and `n/a` items none. Each bug has `kind`, `location`,
  `evidence` (concrete input and wrong result), `cause` and `fix`, so the
  diagnosis of DEC-183 is one per bug by construction. The ranking
  counts bugs, not items. The schema is built per task like the QA's
  draft (DEC-148): items C0..Cn of the task plus E1-E11, each exactly
  once, C items never `n/a`; any failed check goes back to the model as
  a validation error. The call uses the Coder's model (`LLM_MODEL`)
  through `get_chat_model`, so it shares `LLM_TIMEOUT`.
- Why: no bug is lost or merged with another, and a fixed per-task
  schema makes every evaluation cover the same items.
- Alternatives: one diagnosis per item (a second bug in the same item is
  lost); a separate list of diagnoses matched to items by name (two
  structures to keep consistent).
- Code: `agents/coder_reflection.py`

# Improvements backlog

Ideas that go beyond what the labs and the rubric require. Grouped by area;
each idea has a stable ID (`IMP-NNN`, never reused).

**Rules**
- An improvement must never break a rubric criterion: it adds on top of the
  required behavior (e.g. an extra limit), it does not replace it.
- Ideas are implemented only after the related lab is complete, or whenever
  explicitly requested, each in its own commit.
- Status: `idea` → `planned` → `done` (or `discarded`, with the reason in Notes).

**Template**

```markdown
### IMP-NNN Title
- Status: idea
- Area: <area> (<lab>)
- Why: <motivation>
- Rubric: <criteria touched and how the requirement stays met>
- Notes: -
```

---

## Memory (Lab 1.1)

### IMP-001 Token-budget sliding window
- Status: idea
- Area: Memory (Lab 1.1)
- Why: what degrades the context window is the number of tokens, not the
  number of turns; a few long turns (e.g. large code blocks) can fill the
  context while staying under N turns.
- Rubric: C1.2 requires keeping the last N turns, so the token budget must be an
  extra cap on top of `SLIDING_WINDOW_SIZE`, not a replacement; budget
  configurable via `.env`. Shares token counting with C4.4 (cost tracking).
- Notes: evict whole turns (oldest first) until under budget, so tool-call
  messages stay paired with their results.

### IMP-002 Always keep the first user message
- Status: idea
- Area: Memory (Lab 1.1)
- Why: the first user message usually states the overall goal of the session;
  once it slides out of the window, the agent loses that context.
- Rubric: C1.2 — the pinned message must not count towards the N turns, so the
  window still holds the last N turns; documented as an addition to the
  required behavior.
- Notes: decide whether the whole first turn or only the user message is pinned,
  and how it interacts with IMP-001 (does it count towards the token budget?).

### IMP-003 Decide what is worth storing with Jev
- Status: idea
- Area: Memory (Lab 1.1)
- Why: trivial messages ("ok", "thanks") add noise to semantic retrieval;
  a model could judge whether a message is worth keeping in long-term memory.
- Rubric: C1.2 — every relevant task context must still be stored and
  retrieved; the filter must not drop task information. An extra model call per
  turn adds latency and cost (C4.4).
- Notes: Jev is a new type of model that only makes decisions based on context
  (as described by the user; details to be clarified). Complements the
  empty-text validation of DEC-010. Could be one task of the memory curator
  agent (IMP-004).

### IMP-004 Asynchronous memory curator for semantic deduplication
- Status: idea
- Area: Memory (Lab 1.1)
- Why: exact deduplication (DEC-011) misses paraphrases ("Mi nombre es Jaime" /
  "Me llamo Jaime"); a similarity threshold alone can merge different facts
  ("Me llamo Jaime" / "Mi hermano se llama Jaime"). An agent reading the
  candidates in context can tell them apart. Jev (decides based on context) fits
  this role.
- Rubric: C1.2 — must never lose task context: merge or mark as duplicate
  instead of deleting, keeping an audit trail. If it becomes part of the
  pipeline it needs tracing (C4.1), retries (C4.2) and cost accounting (C4.4).
- Notes: running it asynchronously keeps the chat turn fast; the trade-off is
  eventual consistency (a duplicate can be retrieved until the curator runs).
  Could also cover IMP-003 (worth storing) and IMP-005 (fact updates).

### IMP-005 Handle updated facts
- Status: idea
- Area: Memory (Lab 1.1)
- Why: "uso Python 3.11" followed later by "ahora uso Python 3.12" is not a
  duplicate but an update; both are retrieved and the agent may use the stale
  one.
- Rubric: C1.2 — retrieval must keep supplying relevant context.
- Notes: options: rank by recency using the timestamp metadata (DEC-009), or let
  the memory curator (IMP-004) mark the older fact as superseded.

## ReACT loop

### IMP-006 Retrieval query adapted to the latest observation
- Status: idea
- Area: ReACT loop (Lab 1.3)
- Why: during a task the query is always the task (DEC-050), so the
  retrieved memories do not change between iterations; adding the latest
  observation could bring back, e.g., how a similar error was fixed before.
- Rubric: C1.2 — retrieval must still run before every LLM call and return
  context relevant to the task, so the observation is added to the task in
  the query, it does not replace it. Harder to evidence because results
  change per iteration; keep the DEC-025 log.
- Notes: a long observation (traceback, file contents) can dominate the
  query: consider using only its last lines or a size cap. Try it once the
  Coder works end to end, comparing retrieval with and without it.

## PM Agent (Lab 2.1)

### IMP-007 Reject duplicate tasks in the PM's task list
- Status: idea
- Area: PM Agent (Lab 2.1)
- Why: two identical task drafts pass validation, so a list could meet the
  minimum of two tasks without them being discrete (found in the Lab 2.1
  independent review, F4).
- Rubric: C2.1 asks for at least two discrete tasks; rejecting duplicates
  (same title or description) in the coverage validator would trigger the
  corrective retry (DEC-088) and keeps C2.1 met.
- Notes: rare with the real model; the lab's real-LLM test already checks
  coverage of distinct criteria.

## Coder node (Lab 2.2)

### IMP-009 Keep `code` in step with the disk after a fatal error
- Status: idea
- Area: Coder node (Lab 2.2)
- Why: when a fatal error happens after the Coder wrote files (e.g.
  `store_outcome` fails after the loop), the node returns no `code`, so the
  files are on disk but missing from `state.code`. The run stops there
  (DEC-102), so nothing builds on the gap today, but QA (Module 3) or a
  resumed run could read a stale `code`.
- Rubric: C2.2 (accumulated code must be truthful); C4.2/C4.3 (retries or
  an open breaker may let a run continue after an error, which would make
  the gap visible). The fix must not report the task as a success.
- Notes: options: scan the task's planned/known files on disk in the
  `except` path, or have `run_agent` return partial steps with the error.
  Raised during the T3 review of Lab 2.2.

### IMP-010 Explicit recursion limit on the full graph
- Status: done (DEC-115, Lab 2.3)
- Area: Coder node (Lab 2.2)
- Why: LangGraph 1.2's default recursion limit is 10007 steps, so it is no
  safety net. The loop ends by construction today (DEC-103), but Module 3
  adds the QA→Coder loop; a bug in a router would then run until the cost
  shows it.
- Rubric: C2.4 (at most 8 tasks), C3.3 (QA loop limit), C4.4 (cost). The
  limit must be above PM + 8 tasks + QA rounds, or it would stop valid runs.
- Notes: pass `config={"recursion_limit": ...}` on the outer invoke in
  `run()`, computed from the task count and the QA limit. Raised by the
  independent review of the Lab 2.2 spec (F5). Planned in Lab 2.3 as DEC-115.

## Pipeline (Lab 2.3)

### IMP-011 Continue an existing project
- Status: idea
- Area: Pipeline (Lab 2.3)
- Why: today a run always starts a new project folder and refuses an
  existing one (DEC-113). Extending a project ("add a /users endpoint")
  would need: the PM planning from the existing code and spec instead of
  the requirement alone (reopens the Lab 2.1 spec), `state.code` seeded
  from the project folder so the Coder reads before editing, the previous
  run's spec and task statuses persisted, and QA tests (Module 3) to catch
  regressions in what already worked.
  It also brings one folder per project under the workspace (DEC-113,
  superseded for now by DEC-114: each run archives the previous files).
- Rubric: no criterion asks for it. C2.2 (accumulated code must be
  truthful) and C2.5 (working demo) must stay met: a fresh project keeps
  today's behaviour, and continuing is an explicit opt-in (`--continue`)
  that only replaces the "folder exists" refusal.
- Notes: revisit once QA (Module 3) and state persistence (Module 4) exist.

### IMP-012 A refused server file needs a check that imports it
- Status: idea
- Area: Pipeline (Lab 2.3)
- Why: the API file is never run (DEC-116), so a task ends `success` when
  any script ran without error after the last write, e.g. a `check.py`
  that only prints "ok" (independent review F3). Option: when the main
  file is one the guard refuses, count only runs of scripts that import
  it, and record in `CoderResult` which file produced `result`.
- Rubric: C1.5 (`result` from a real execution of the delivered code),
  DEC-111 (an honest verdict). The change only narrows what counts as
  `success`; QA's real tests (C3.1) cover the gap from Module 3.
- Notes: -

### IMP-013 Detect servers with the AST instead of regexes
- Status: idea
- Area: Pipeline (Lab 2.3)
- Why: the regex guard misses `app: Flask = Flask(...)`,
  `create_app().run()`, `waitress.serve(app)` and `uvicorn.Server(...).run()`,
  and refuses a check script that names `app.run(` in a comment
  (independent review F4). A misses only costs the 10 s timeout and an
  iteration.
- Rubric: C1.3 (the timeout stays the safety net), C2.5. Parse the file
  with `ast`; a file that does not parse keeps today's behaviour.
- Notes: -

### IMP-014 Memories of files from archived runs
- Status: idea
- Area: Pipeline (Lab 2.3)
- Why: Chroma keeps memories across runs, but each run starts with an empty
  workspace (DEC-114); a recalled "app.py done" may lead the Coder to
  finish without writing the file (it then ends `unverified`). The task
  prompt already says which files exist in this run (DEC-098), which
  mitigates it (independent review F8).
- Rubric: C1.2 (retrieval before every call must stay), C2.5. Option:
  filter or label memories from earlier runs; revisit with IMP-011.
- Notes: -

## MCP (Lab 3.1)

### IMP-015 Generic MCP client calls instead of one function per tool
- Status: idea
- Area: MCP (Lab 3.1)
- Why: `tools/mcp_client.py` has one function per server tool
  (`call_read_file`). If the server gains `write_file` and `exec_python`,
  a single `call_tool(session, name, arguments)`, or `langchain-mcp-adapters`
  turning every server tool into a LangChain tool, avoids one wrapper per
  tool and lets an agent use whatever the server advertises.
- Rubric: only needed on the MCP route of C3.5 (the Coder as an MCP client,
  DEC-123, DEC-125); `call_read_file` stays, since AC-3.1-15 and the Lab 3.2
  QA use it. Labs 3.2-3.4 never ask for it: they use MCP only for the QA's
  `read_file` and A2A between Coder and QA.
- Notes: decide in the spec of the Coder as an MCP client, if the MCP route
  is chosen in Lab 3.3.

## QA Agent (Lab 3.2)

### IMP-016 Do not blame the QA for imports that are legitimate
- Status: idea
- Area: QA Agent (Lab 3.2)
- Why: the import check of DEC-152 rejects, as the QA's mistake, a test
  that imports a module created by an earlier task (task 2 may use task
  1's code) or a name the PM's specification mentions but the task does
  not. Both are legitimate, and each rejection spends one of the
  `QA_MAX_ATTEMPTS` attempts. Allowing every module in the Coder's folder
  (from the MCP listing resource) and looking names up in the whole
  specification would avoid that.
- Rubric: C3.1 (tests still run and check the task's criteria), C3.3 (the
  attempt budget still bounds the QA). Only widens what the check accepts.
- Notes: -

### IMP-017 An LLM arbiter for failures whose owner is unclear
- Status: idea
- Area: QA Agent (Lab 3.2)
- Why: DEC-152 blames the owner of the deepest frame of the traceback.
  Some failures land in the Coder's code but are the test's fault, e.g. a
  test calls `insert("5")` with the wrong type and the `TypeError` is
  raised inside the Coder's `insert`. For those ambiguous cases only
  (`TypeError`, `AttributeError` at the test/code boundary), one LLM call
  could decide the owner, within the `QA_MAX_ATTEMPTS` budget.
- Rubric: C3.1 (the verdict still comes from executed tests; the LLM only
  routes the failure), C3.3 (bounded by the attempt budget), C1.3/C4.6 (its
  output validated with a schema; any failure falls back to the fixed
  rule).
- Notes: deterministic rule kept for Lab 3.2; an arbiter adds cost and
  non-reproducible verdicts, so only for the ambiguous cases.

## Coder-QA loop (Lab 3.3)

### IMP-018 Re-plan a task that stays failed after the QA loop
- Status: idea
- Area: Coder-QA loop (Lab 3.3)
- Why: a task that reaches the review limit with failures stays `failed`
  and the run ends `unresolved`. The PM could re-plan it instead (split
  it, rewrite its criteria) and hand it back to the Coder, closer to a
  long-running agent that keeps working until the project is done.
- Rubric: C3.3 (re-planning opens a second loop that needs its own
  configurable limit, and the final report must still list what stays
  unresolved), C2.4 (a re-planned list must still have at most 8 tasks).
  Adds on top of the review limit; never replaces it.
- Notes: unlikely to be done; no lab or criterion asks for re-planning.

### IMP-019 Async pipeline: the Coder starts the next task while the QA reviews
- Status: idea
- Area: Coder-QA loop (Lab 3.3)
- Why: today the graph is sequential (DEC-179): while the QA tests task N,
  the Coder waits. With async nodes the Coder could start task N+1 in
  parallel and save wall-clock time.
- Rubric: C3.2 and C3.3 (each task's loop and limit must stay intact),
  C2.4 (order and progress per task). Risks: task N+1 may build on code
  the QA has not approved yet (against DEC-163), and the Coder may write
  files while the QA reads them, so the workspace needs per-task
  isolation or locking.
- Notes: unclear gain for the course's tasks; noted for later.

### IMP-020 Compact window turns for the Coder
- Status: idea
- Area: Coder-QA loop (Lab 3.3)
- Why: each ReACT pass enters the sliding window with its full trace,
  tool calls and repeated code included, and the window is injected in
  every Coder call (DEC-185). A turn made of the pass prompt plus its
  final summary would cut tokens and keep more tasks in the window.
- Rubric: C1.2 (the window must still be injected before every LLM
  call; changes DEC-057 and DEC-077, which are Required), C4.4 (cost).
  Risk: regression of the Module 1 memory evidence.
- Notes: decide with Module 4 cost reports.

## General

### IMP-008 One module for the models shared between agents
- Status: idea
- Area: Project layout (Lab 2.2)
- Why: Pydantic models live in five files (`orchestration/state.py`, both
  agents, `tools/handlers.py`, `tools/code_executor.py`). Shared ones
  (state, handoff, `CoderResult`, `ExecutionResult`) could sit in one
  `models.py`; LLM schemas (`Plan`, `Finish`, `SpecDraft`, `TaskDraft`)
  and tool argument checks stay next to the code that uses them.
- Rubric: C1.1/C5.3 (layout must still have the required folders), C2.2
  (state stays typed). Pure move of classes and imports in its own commit;
  the whole suite must stay green.
- Notes: decided to postpone during Lab 2.2; `CoderResult` moves to
  `orchestration/state.py` meanwhile (DEC-065).
  Lab 3.3 split `Issue` and `QAReport` into `orchestration/qa_report.py`
  to break an import cycle with the A2A messages (DEC-188); the user
  raised `models.py` again then.

### IMP-021 All prompts in one `prompts.yaml`
- Status: idea
- Area: Project layout (Lab 3.3)
- Why: prompt texts are spread over the agents (`CODER_SYSTEM_PROMPT`,
  `PLAN_SYSTEM_PROMPT`, `EVALUATION_SYSTEM_PROMPT`, the PM's and the QA's
  prompts, `PENDING_NOTE`, section headings). One file would let us tune
  wording in one place without touching code.
- Rubric: C1.3/C4.6 (outputs are still validated; the prompts only change
  wording), C4.8 (the file must ship in the Docker image), C5.3 (layout).
  Risk: a missing or renamed key breaks an agent at run time.
- Notes: only fixed texts move, as templates with named placeholders
  (e.g. `{python_environment}`, `{kind_help}`); how each pass prompt is
  assembled (DEC-187, DEC-195) stays in code. Load and check every key
  once at import, failing fast with the key's name, and test that each
  template formats. Keep the `DEC-NNN` anchors as YAML comments next to
  each prompt. Needs `pyyaml` pinned in `requirements.txt`. Own commit;
  the whole suite must stay green.

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

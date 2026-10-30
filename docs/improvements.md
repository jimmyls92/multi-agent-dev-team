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
- Notes: Jev is a new type of model; details to be clarified by the user.
  Complements the empty-text validation decided for `store_memory` (D3).

## ReACT loop

_No ideas yet._

## General

_No ideas yet._

# Lab 1.1 — Memory System with Conversation History & Semantic Retrieval

**Course:** Build Autonomous Multi-Agent Systems
**Module:** 1 · Section 5 · Lab 1.1 — covers rubric criterion **C1.2**
**Use when:** working on two-tier memory (`memory.py`, the `chat()` TODO in
`agents/coder_agent.py`, `tests/test_memory.py`) or when Lab 1.1 is mentioned.

Original lab README (the full handout lives in the course LMS):

| Lab file | Project file | Task |
|------|------|------|
| `memory.py` | `memory.py` (root, DEC-035) | Two-tier memory system — 3 TODOs |
| `agent.py` | `agents/coder_agent.py` | Coder Agent conversation loop — 1 TODO (`chat()`) |
| `test_memory.py` | `tests/test_memory.py` | Automated verification |

Adaptations in this project (DEC-001, DEC-002, DEC-007, DEC-035 in `docs/decisions.md`):
- Files live in the project scaffold (C1.1), so the agent runs as a module from the
  repo root: `python -m agents.coder_agent`; verify with `python -m tests.test_memory`.
- LLM access goes through OpenRouter (OpenAI-compatible) instead of Helicone; the
  client comes from `get_client()` in `llm_client.py` (DEC-034) and the key from
  `OPENROUTER_API_KEY` in `.env`.
- `tests/test_memory.py` is the official lab test with imports adapted to the
  scaffold. It needs a real `OPENROUTER_API_KEY` and keeps `SLIDING_WINDOW_SIZE` ≤ 6.
- Run the lab test against a separate store so its planted fact does not end up
  in the real memory (DEC-018):
  `CHROMA_PATH=.chroma-test python -m tests.test_memory`

Extra ideas for this area: `docs/improvements.md` → section "Memory (Lab 1.1)".

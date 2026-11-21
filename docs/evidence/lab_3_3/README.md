# Lab 3.3 — live evidence

INFO logs of real runs with the configured models (OpenRouter), kept as
evidence of the A2A review loop (C3.5), the self-reflection (C3.4) and the
linked-list demo (C3.6). Local paths are replaced by `<repo>`, `<venv>`
and `<tmp>`; no key or secret appears (DEC-199).

| File | What it shows |
|---|---|
| `ac_3_3_41_planted_bug.log` | `pytest --run-llm -k 41 tests/test_reflection.py`: a `reverse` that loses nodes is critiqued as a High bug in `reverse`, one improvement pass runs, v1 is evaluated with no High or Medium bug and is sent (`critique v0`, `v0:`, `v1:`, `sent v1` lines). |
| `ac_3_3_40_linked_list_demo.log` | `pytest --run-llm -k 40 tests/test_integration_loop.py`: the whole team on the guide's linked-list requirement ends `success`; each task's `review_request` and `approved` share a `correlation_id`. |
| `main_linked_list_demo.log` | `python main.py "<linked-list requirement>"`: the same requirement from the command line, ending `RESULT: success`. |
| `main_linked_list_demo_5_reviews.log` | An earlier command-line run of the same requirement where the QA sent task_2 back four times (`fix_instruction`) and approved it at review 5, the last allowed: the QA's feedback driving the Coder's revisions (C3.2). It ran before DEC-200, which changed only the self-evaluation's schema, retries and model. |

How to read them: every A2A message is one line
`A2A <sender> -> <receiver> intent=<intent> task=<task> review=<n> correlation_id=<id>`;
the self-reflection logs `critique vN`, `vN: <High>, <Medium>, <Low>` and
`sent vN`; the QA logs its pytest result and its verdict.

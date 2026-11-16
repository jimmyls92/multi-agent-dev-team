# Spec: Lab 3.1 — MCP file server

- **Status:** approved
- **Sources:** lab handout `docs/labs/lab_3_1_mcp_server.md`, project guide
  (Module 3, `docs/course_reference.txt`, instruction 18), rubric C3.5,
  C1.3, C4.6, C4.7
- **Decisions:** DEC-122..DEC-134 (the why lives there; do not repeat it here)

## Goal

An MCP server built with the official Python SDK serves the agents'
workspace: one tool, `read_file`, and one resource, `file://project/listing`.
A client starts it as a separate process over stdio and reads the Coder's
files through the protocol, never by importing them. Every request is
logged to stderr with the server's PID. Nothing in the pipeline uses it yet;
the QA agent connects to it in Lab 3.2.

## Lab vs project

| Lab says | Project requires | What we do |
|---|---|---|
| `mcp_server.py`, `mcp_client.py`, `main.py` at the root | C1.1 layout; `main.py` is the pipeline | `tools/mcp_server.py`, `tools/mcp_client.py`; demo `python -m tools.mcp_client` (DEC-128) |
| `mcp>=1.0.0` | Official SDK (C3.5) | `mcp>=1.30,<2` (DEC-129) |
| Serves `project_files/` | Shared file layer between agents | Serves `WORKSPACE_DIR` (DEC-124) |
| Top-level listing of `project_files/` | — | Recursive, relative paths, no hidden entries or `__pycache__/` (DEC-125) |
| `_read_file` rejects `../` and absolute paths | C1.3/C4.6: validated arguments, no crash | `ReadFileArgs` strict + confinement + hidden/`__pycache__` rejection + `READ_MAX_CHARS` (DEC-126, DEC-131) |
| `ERROR:` text in a content list | — | `CallToolResult` with `isError=True` and `ERROR:` text; SDK schema validation off (DEC-130) |
| `connect_and_run(server_script_path)` | Tests never touch the real `workspace/` | The client starts `python -m tools.mcp_server` with `WORKSPACE_DIR` in its env (DEC-132) |
| "Server log shows `read_file` through MCP" | C3.5 invocation logs (if MCP is chosen) | One stderr line per event with the server's PID; contents never logged (DEC-127) |
| Mocked `ClientSession` tests | C4.7: behaviour, not fixed objects | Real server in memory, plus one stdio test (DEC-133); `pytest-asyncio` auto mode (DEC-134) |

## Acceptance criteria

`Origin`: `C<x>.<y>` (rubric), `lab` or `ours`.
`Verify`: `unit` (fake model), `integration`, `llm` (real key, `--run-llm`)
or `manual`.

"In memory" = a real `ClientSession` connected to `tools.mcp_server.server`
through `mcp.shared.memory.create_connected_server_and_client_session`,
with `tools.handlers.WORKSPACE_DIR` pointing to a temporary workspace (the
autouse fixture of `tests/conftest.py`). Every test below is in
`tests/test_mcp_server.py` unless it says otherwise. No test needs a key or
the network.

### Tool registration

#### AC-3.1-1 — The server advertises exactly `read_file` with a JSON Schema

- **Origin:** lab
- **Verify:** integration — `test_ac_3_1_1_lists_read_file`
- **Given** a session in memory
- **When** the client calls `list_tools()`
- **Then** the tool names are exactly `["read_file"]`, and its `inputSchema`
  has `type: object`, a `path` property of type `string`, `path` in
  `required` and `additionalProperties: false`

#### AC-3.1-2 — An unknown tool returns an error

- **Origin:** lab
- **Verify:** integration — `test_ac_3_1_2_unknown_tool`
- **Given** a session in memory
- **When** the client calls `call_tool("write_file", {"path": "a.py"})`
- **Then** the result has `isError=True`, its text starts with `ERROR:` and
  names the tool, and no file is created

### Reading files

#### AC-3.1-3 — An existing file is returned unchanged

- **Origin:** lab
- **Verify:** integration — `test_ac_3_1_3_reads_file`
- **Given** a workspace with `pkg/util.py` containing `def add(a, b):\r\n    return a + b\n`
- **When** the client calls `read_file` with `{"path": "pkg/util.py"}`
- **Then** the result has `isError=False` and its only text content equals
  the file content exactly

#### AC-3.1-4 — Paths outside the workspace are rejected

- **Origin:** lab, C1.3, DEC-126
- **Verify:** integration — `test_ac_3_1_4_rejects_outside_paths`
- **Given** a workspace and a file `secret.txt` next to it (outside it)
- **When** the client calls `read_file` with `../secret.txt`, with the
  absolute path of `secret.txt`, and with `/etc/passwd`
- **Then** each result has `isError=True`, text starting with `ERROR:`, and
  none contains the content of the target file

#### AC-3.1-5 — Missing files and folders return an error

- **Origin:** lab
- **Verify:** integration — `test_ac_3_1_5_missing_or_folder`
- **Given** a workspace with a folder `pkg/` and no `nope.py`
- **When** the client calls `read_file` with `nope.py` and with `pkg`
- **Then** both results have `isError=True` and text starting with
  `ERROR:` that names the relative path

#### AC-3.1-6 — Hidden entries and `__pycache__` are never readable

- **Origin:** ours, DEC-126, DEC-131
- **Verify:** integration — `test_ac_3_1_6_rejects_hidden_and_pycache`
- **Given** a workspace with `.env`, `.git/config`, `__pycache__/m.pyc`,
  `pkg/__pycache__/n.pyc` and a symlink `notes.txt` pointing to `.env`
  (the symlink case is skipped where symlinks cannot be created)
- **When** the client calls `read_file` with each of those paths
- **Then** each result has `isError=True`, text starting with `ERROR:`, and
  none contains the content of the target file

#### AC-3.1-7 — Invalid arguments never reach the file system and the server keeps serving

- **Origin:** C1.3, C4.6, DEC-126, DEC-130
- **Verify:** integration — `test_ac_3_1_7_invalid_arguments`
- **Given** a session in memory and a workspace with `a.py`
- **When** the client calls `read_file` with `{}`, `{"path": 1}`,
  `{"path": ""}` and `{"path": "a.py", "mode": "w"}`, and then with
  `{"path": "a.py"}`
- **Then** the first four results have `isError=True` and text starting
  with `ERROR:` that names the problem; the last one returns the content
  of `a.py` (the session is still alive)

#### AC-3.1-8 — Long files are cut at `READ_MAX_CHARS`

- **Origin:** ours, DEC-041, DEC-126
- **Verify:** integration — `test_ac_3_1_8_truncates_long_files`
- **Given** `READ_MAX_CHARS` set to 10 and a workspace file of 25 characters
- **When** the client reads it
- **Then** the result has `isError=False`, starts with the first 10
  characters and ends with the truncation mark of `file_io.read_file`

#### AC-3.1-9 — Error messages never reveal absolute paths

- **Origin:** ours, DEC-131
- **Verify:** integration — `test_ac_3_1_9_errors_use_relative_paths`
- **Given** a workspace with `bin.dat` holding bytes that are not UTF-8
- **When** the client reads `bin.dat` and `nope.py`
- **Then** both results have `isError=True`, text starting with `ERROR:`
  that names the relative path, and neither contains the absolute path of
  the workspace

### Listing resource

#### AC-3.1-10 — The listing resource is advertised

- **Origin:** lab
- **Verify:** integration — `test_ac_3_1_10_lists_resource`
- **Given** a session in memory
- **When** the client calls `list_resources()`
- **Then** the result holds exactly one resource, with URI
  `file://project/listing` and MIME type `text/plain`

#### AC-3.1-11 — The listing is recursive and hides what `read_file` refuses

- **Origin:** ours, DEC-125, DEC-131
- **Verify:** integration — `test_ac_3_1_11_listing_content`
- **Given** a workspace with `b.py`, `a.py`, `pkg/c.py`, `.env`,
  `.git/config`, `__pycache__/m.pyc` and `pkg/__pycache__/n.pyc`
- **When** the client reads `file://project/listing`
- **Then** the text is exactly `a.py\nb.py\npkg/c.py` (sorted, `/`
  separators, files only), and calling `read_file` with each line returns
  `isError=False`

#### AC-3.1-12 — An empty or missing workspace gives an empty listing

- **Origin:** ours
- **Verify:** integration — `test_ac_3_1_12_empty_listing`
- **Given** an empty workspace, and separately a workspace folder that
  does not exist
- **When** the client reads `file://project/listing`
- **Then** the text is empty and no error is raised

#### AC-3.1-13 — An unknown resource URI is an error, not a crash

- **Origin:** ours, C4.6
- **Verify:** integration — `test_ac_3_1_13_unknown_resource`
- **Given** a session in memory
- **When** the client reads `file://project/other`
- **Then** the client gets an `McpError`, and a following `read_file`
  call on an existing file still succeeds

### Logging

#### AC-3.1-14 — Each request is logged once, rejected ones at WARNING, never the contents

- **Origin:** lab, DEC-127
- **Verify:** integration — `test_ac_3_1_14_logs_requests`
- **Given** a session in memory, `caplog` capturing the server's logger and
  a workspace file `a.py` whose content is a unique marker string
- **When** the client reads `a.py`, reads `../x` and reads the listing
- **Then** there is one INFO record for the `a.py` call with the path and
  the character count, one WARNING record for `../x` with the reason, one
  INFO record for the listing with the number of files; no record contains
  the marker string

### Client

#### AC-3.1-15 — The client functions return plain Python values

- **Origin:** lab
- **Verify:** integration — `tests/test_mcp_client.py::test_ac_3_1_15_client_functions`
- **Given** a session in memory and a workspace with `a.py`
- **When** the test calls `list_available_tools(session)`,
  `list_available_resources(session)`, `call_read_file(session, "a.py")`
  and `call_read_file(session, "nope.py")`
- **Then** they return `["read_file"]`,
  `[("file://project/listing", <name>)]`, the content of `a.py`, and a
  string starting with `ERROR:`

#### AC-3.1-16 — Over stdio the call crosses a process boundary

- **Origin:** lab, C3.5 (if MCP is chosen), DEC-127, DEC-132, DEC-133
- **Verify:** integration — `tests/test_mcp_client.py::test_ac_3_1_16_stdio_process_boundary`
- **Given** a temporary workspace with `a.py` whose content is a unique
  marker string, and a file that captures the server's stderr
- **When** `connect_and_run("a.py", workspace=..., errlog=...)` runs
- **Then** it returns `tools == ["read_file"]`, the listing resource and
  the content of `a.py`; the captured stderr has a start line with the
  workspace path and a `read_file` line for `a.py`, both carrying a PID
  different from `os.getpid()`; the marker string is not in the stderr

#### AC-3.1-17 — The demo runs from the command line

- **Origin:** lab
- **Verify:** manual — `python -m tools.mcp_client pkg/util.py`
- **Given** a workspace with a file (for example, one left by
  `python main.py`)
- **When** the user runs the demo
- **Then** it prints the tool, the listing resource and the file content,
  the stderr shows the server's lines with a PID other than the client's,
  and it exits with code 0; with a missing path it prints the `ERROR:`
  text and still exits 0

## Tasks

Each task covers at least one AC, is reviewable in ~15 minutes and ends in one commit.
Task status: todo | map | in progress | review | done

Every task ends with the whole suite green (`.venv/bin/python -m pytest`),
so no earlier criterion regresses.

### T1 — Server with `read_file` over MCP · done

- **Covers:** AC-3.1-1, AC-3.1-2, AC-3.1-3, AC-3.1-4, AC-3.1-5, AC-3.1-7,
  AC-3.1-14 (the `read_file` records)
- **Map:** to approve before writing code. Includes `requirements.txt`
  (`mcp`, `pytest-asyncio`), `pytest.ini` (`asyncio_mode = auto`), the
  in-memory session fixture, `tools/mcp_server.py` with the server, the
  tool registration and `read_file`, and its stderr logging.

### T2 — Exposure rules and the listing resource · todo

- **Covers:** AC-3.1-6, AC-3.1-8, AC-3.1-9, AC-3.1-10, AC-3.1-11,
  AC-3.1-12, AC-3.1-13, AC-3.1-14 (the listing record)
- **Map:** to approve before writing code. `_is_exposed` shared by
  `read_file` and the listing, relative error messages, the resource.

### T3 — Client, stdio test and demo · todo

- **Covers:** AC-3.1-15, AC-3.1-16, AC-3.1-17
- **Map:** to approve before writing code. `tools/mcp_client.py` with the
  lab's three functions, `connect_and_run` and the `__main__` demo.

### T4 — README · todo

- **Covers:** documentation of what Lab 3.1 adds — `manual`
- **Map:** to approve before writing. MCP server section: what it exposes,
  safety rules, how to run the demo and the tests, where the server log
  goes; note that the protocol route is chosen in Lab 3.3 (DEC-123).

## Independent review

- **Date:**
- **Findings and triage:**

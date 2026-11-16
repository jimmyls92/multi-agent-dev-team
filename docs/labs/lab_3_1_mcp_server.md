# Lab 3.1 — Custom MCP Server with File-System Access

**Module 3 · Section 4 · Lab 1**
Build Autonomous Multi-Agent Systems · Saras AI Institute

---

## Objective

Build a minimal MCP server that exposes one tool (`read_file`) and one
resource (project directory listing), then connect an agent client to it
via stdio transport and verify the tool resolves correctly **through the
protocol** — not via direct Python import.

This server becomes the shared file layer in the Week 3 pipeline. The
Coder agent writes files using its own direct tools; the QA agent reads
those files through this MCP server — neither agent imports the other's
code.

---

## What You Will Build

```
mcp_server.py          ← MCP server (you implement this)
mcp_client.py          ← MCP client (you implement this)
```

### Tool to expose on the server

| Tool | Input | Behaviour |
|------|-------|-----------|
| `read_file` | `{ "path": str }` | Reads a file from `project_files/`. Rejects path traversal. Returns `ERROR:` on any failure. |

### Resource to expose

| URI | Content |
|-----|---------|
| `file://project/listing` | Newline-separated list of files in `project_files/` |

### Client functions to implement

| Function | What it does |
|----------|-------------|
| `list_available_tools(session)` | Returns tool names via `session.list_tools()` |
| `list_available_resources(session)` | Returns `(uri, name)` tuples via `session.list_resources()` |
| `call_read_file(session, filename)` | Calls `read_file` tool, returns text content |
| `connect_and_run(server_script_path)` | Launches server, wires session, calls all three functions |

---

## Setup

```bash
pip install -r requirements.txt
```

---

## Files

```
lab3.1/
├── mcp_server.py       ← Implement this
├── mcp_client.py       ← Implement this
├── main.py             ← Entry point (do not modify)
├── requirements.txt
├── pytest.ini
├── README.md
├── utils.py        ← Sample file your server will expose
```

---

## Implementation Guide

### 1 — Build the server (`mcp_server.py`)

Work through the TODOs in order:

1. Create the `Server("lab3-mcp-server")` instance.
2. Register `list_tools` — return one `types.Tool` for `read_file` with a
   valid JSON Schema `inputSchema`.
3. Register `call_tool` — dispatch to `_read_file` or return an error for
   unknown tool names.
4. Register `list_resources` — return the directory listing resource.
5. Register `read_resource` — return the file listing when the URI matches.
6. Implement `_read_file(path)` with path traversal protection.

**Important:** `inputSchema` must use JSON Schema syntax, not Python types:

```python
# ✗ Wrong
"inputSchema": {"path": str}

# ✓ Correct
"inputSchema": {
    "type": "object",
    "properties": {"path": {"type": "string"}},
    "required": ["path"],
}
```

### 2 — Build the client (`mcp_client.py`)

The MCP client API:

```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

params = StdioServerParameters(command=sys.executable, args=["mcp_server.py"])

async with stdio_client(params) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()               # always first

        tools   = await session.list_tools()     # .tools → list[Tool]
        res     = await session.list_resources() # .resources → list[Resource]
        result  = await session.call_tool("read_file", {"path": "utils.py"})
                                                 # .content[0].text
```

### 3 — Run it

```bash
python main.py
```

You should see `read_file` listed as the available tool, the directory
listing resource, and the contents of `utils.py`.

---

## Tests

```bash
# Run the mocked test suite (fast, no network required)
pytest

# Run everything including the live end-to-end test
pytest --run-llm
```

All mocked tests must pass before you submit.

---

## Success Criteria

- [ ] `pytest` exits with 0 failures (mocked suite).
- [ ] The server log shows the `read_file` invocation going through the
      MCP protocol (not a direct Python import).
- [ ] `read_file` rejects `../` and absolute paths with an `ERROR:` response.
- [ ] `read_file` returns an `ERROR:` response for missing files.
- [ ] `python main.py` completes without errors.

---

## Key Concept

The whole point of MCP is that the agent **does not import your tools
directly**. It calls them through a protocol. This means:

- The server and client run as separate processes.
- Any agent that speaks MCP can call `read_file` — the Coder agent and
  the QA agent both connect to this same server in Labs 3.2–3.4.
- The QA agent can read files the Coder wrote without the two agents
  ever importing each other's code.

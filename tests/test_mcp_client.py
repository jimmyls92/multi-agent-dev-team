"""Tests of the MCP client (Lab 3.1, DEC-132, DEC-133).

The lab's client functions run against the real server in memory (the
``mcp_session`` fixture). One test starts the server over stdio as a
separate process, the only proof that a call crosses a process boundary.
"""

import os
import re
import sys

import pytest
from mcp import StdioServerParameters
from mcp.shared.exceptions import McpError

import tools.mcp_client
from tools.mcp_client import (
    call_read_file,
    connect_and_run,
    list_available_resources,
    list_available_tools,
    read_listing,
    read_multiple_files,
)

_PID = re.compile(r"pid=(\d+)")


async def test_ac_3_1_15_client_functions(mcp_session, workspace):
    (workspace / "a.py").write_text("x = 1\n")

    tools = await list_available_tools(mcp_session)
    resources = await list_available_resources(mcp_session)
    content = await call_read_file(mcp_session, "a.py")
    missing = await call_read_file(mcp_session, "nope.py")
    listing = await read_listing(mcp_session)

    assert tools == ["read_file"]
    assert len(resources) == 1
    uri, name = resources[0]
    assert uri == "file://project/listing"
    assert isinstance(name, str) and name
    assert content == "x = 1\n"
    assert missing.startswith("ERROR:")
    assert listing == ["a.py"]


async def test_read_listing_of_empty_workspace(mcp_session, workspace):
    assert await read_listing(mcp_session) == []


@pytest.mark.timeout(30)
async def test_ac_3_1_16_stdio_process_boundary(workspace, tmp_path):
    marker = "STDIO-MARKER-5b8c"
    (workspace / "a.py").write_text(marker)
    (workspace / os.fsdecode(b"bad\xffname.py")).write_text("x = 2\n")
    log_path = tmp_path / "server.log"

    with log_path.open("w") as errlog:
        result = await connect_and_run("a.py", workspace=workspace, errlog=errlog)

    assert result["tools"] == ["read_file"]
    assert [uri for uri, _ in result["resources"]] == ["file://project/listing"]
    assert result["listing"] == ["a.py"]
    assert result["file_content"] == marker

    lines = log_path.read_text().splitlines()
    start = [line for line in lines if "started" in line and str(workspace) in line]
    reads = [line for line in lines if "read_file 'a.py'" in line]
    assert len(start) == 1
    assert len(reads) == 1
    for line in start + reads:
        match = _PID.search(line)
        assert match, line
        assert int(match.group(1)) != os.getpid()
    assert marker not in log_path.read_text()


@pytest.mark.timeout(30)
async def test_read_multiple_files_skips_rejected(workspace, tmp_path):
    (workspace / "a.py").write_text("x = 1\n")
    (workspace / "b.py").write_text("ERROR: not an error\n")

    with (tmp_path / "server.log").open("w") as errlog:
        contents = await read_multiple_files(
            ["a.py", "missing.py", "b.py"], workspace=workspace, errlog=errlog
        )

    assert contents == {"a.py": "x = 1\n", "b.py": "ERROR: not an error\n"}


@pytest.mark.timeout(30)
async def test_ac_3_1_19_client_times_out(workspace, tmp_path, monkeypatch):
    silent = StdioServerParameters(
        command=sys.executable, args=["-c", "import time; time.sleep(60)"]
    )
    monkeypatch.setattr(tools.mcp_client, "_server_parameters", lambda workspace: silent)
    monkeypatch.setenv("MCP_TIMEOUT", "1")

    with (tmp_path / "server.log").open("w") as errlog:
        with pytest.raises(McpError, match="Timed out"):
            await connect_and_run("a.py", workspace=workspace, errlog=errlog)

"""Tests of the MCP client (Lab 3.1, DEC-132, DEC-133).

The lab's client functions run against the real server in memory (the
``mcp_session`` fixture). One test starts the server over stdio as a
separate process, the only proof that a call crosses a process boundary.
"""

import os
import re

import pytest

from tools.mcp_client import (
    call_read_file,
    connect_and_run,
    list_available_resources,
    list_available_tools,
    read_listing,
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
    log_path = tmp_path / "server.log"

    with log_path.open("w") as errlog:
        result = await connect_and_run("a.py", workspace=workspace, errlog=errlog)

    assert result["tools"] == ["read_file"]
    assert [uri for uri, _ in result["resources"]] == ["file://project/listing"]
    assert result["listing"] == ["a.py"]
    assert result["file_content"] == marker

    lines = log_path.read_text().splitlines()
    start = [line for line in lines if "started" in line and str(workspace) in line]
    reads = [line for line in lines if "read_file a.py" in line]
    assert len(start) == 1
    assert len(reads) == 1
    for line in start + reads:
        match = _PID.search(line)
        assert match, line
        assert int(match.group(1)) != os.getpid()
    assert marker not in log_path.read_text()

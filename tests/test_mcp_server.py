"""Tests of the MCP file server (Lab 3.1, DEC-124..DEC-133).

Every test talks to the real server through a real ``ClientSession``
connected in memory (the ``mcp_session`` fixture), so each call goes through
the full MCP protocol: tool listing, argument passing and result encoding.
"""

import logging
import os
from pathlib import Path

import pytest
from mcp.shared.exceptions import McpError
from pydantic import AnyUrl

import tools.handlers
from tools import file_io

LISTING = AnyUrl("file://project/listing")


def _text(result) -> str:
    """Returns the text of a tool result that holds exactly one text block.

    Args:
        result: The ``CallToolResult`` returned by the client.

    Returns:
        The text of its only content block.
    """
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    return result.content[0].text


async def _listing(session) -> str:
    """Returns the text of the ``file://project/listing`` resource.

    Args:
        session: Client session connected to the server.

    Returns:
        The listing text.
    """
    result = await session.read_resource(LISTING)
    assert len(result.contents) == 1
    return result.contents[0].text


async def test_ac_3_1_1_lists_read_file(mcp_session):
    listing = await mcp_session.list_tools()

    assert [tool.name for tool in listing.tools] == ["read_file"]
    schema = listing.tools[0].inputSchema
    assert schema["type"] == "object"
    assert schema["properties"]["path"]["type"] == "string"
    assert schema["required"] == ["path"]
    assert schema["additionalProperties"] is False


async def test_ac_3_1_2_unknown_tool(mcp_session, workspace):
    result = await mcp_session.call_tool("write_file", {"path": "a.py"})

    assert result.isError is True
    assert _text(result).startswith("ERROR:")
    assert "write_file" in _text(result)
    assert not (workspace / "a.py").exists()


async def test_ac_3_1_3_reads_file(mcp_session, workspace):
    content = "def add(a, b):\r\n    return a + b\n"
    (workspace / "pkg").mkdir()
    (workspace / "pkg" / "util.py").write_bytes(content.encode())

    result = await mcp_session.call_tool("read_file", {"path": "pkg/util.py"})

    assert result.isError is False
    assert _text(result) == content


async def test_ac_3_1_4_rejects_outside_paths(mcp_session, workspace):
    secret = workspace.parent / "secret.txt"
    secret.write_text("TOP-SECRET-4f1c")
    passwd = Path("/etc/passwd")
    passwd_head = passwd.read_text().splitlines()[0] if passwd.is_file() else None

    for path in ("../secret.txt", str(secret), "/etc/passwd"):
        result = await mcp_session.call_tool("read_file", {"path": path})

        assert result.isError is True, path
        assert _text(result).startswith("ERROR:"), path
        assert "TOP-SECRET-4f1c" not in _text(result)
        if passwd_head:
            assert passwd_head not in _text(result)


async def test_ac_3_1_5_missing_or_folder(mcp_session, workspace):
    (workspace / "pkg").mkdir()

    for path in ("nope.py", "pkg"):
        result = await mcp_session.call_tool("read_file", {"path": path})

        assert result.isError is True, path
        assert _text(result).startswith("ERROR:"), path
        assert path in _text(result)


async def test_ac_3_1_6_rejects_hidden_and_pycache(mcp_session, workspace):
    files = {
        ".env": "SECRET-ENV-71a0",
        ".git/config": "SECRET-GIT-71a0",
        "__pycache__/m.pyc": "SECRET-PYC-71a0",
        "pkg/__pycache__/n.pyc": "SECRET-PKG-PYC-71a0",
        "__PyCache__/z.txt": "SECRET-CASE-71a0",
    }
    for relative, content in files.items():
        (workspace / relative).parent.mkdir(parents=True, exist_ok=True)
        (workspace / relative).write_text(content)
    (workspace / ".git" / "hooks").mkdir()
    paths = list(files)
    try:
        os.symlink(workspace / ".env", workspace / "notes.txt")
        os.symlink(workspace / ".git" / "hooks", workspace / "d")
        paths += ["notes.txt", "d/../config"]
    except OSError:
        pass  # symlinks cannot be created here; those cases are skipped

    for path in paths:
        result = await mcp_session.call_tool("read_file", {"path": path})

        assert result.isError is True, path
        assert _text(result).startswith("ERROR:"), path
        assert all(secret not in _text(result) for secret in files.values()), path


async def test_ac_3_1_8_truncates_long_files(mcp_session, workspace, monkeypatch):
    monkeypatch.setattr(file_io, "READ_MAX_CHARS", 10)
    (workspace / "long.txt").write_text("abcdefghijklmnopqrstuvwxy")

    result = await mcp_session.call_tool("read_file", {"path": "long.txt"})

    assert result.isError is False
    assert _text(result).startswith("abcdefghij")
    assert "k" not in _text(result).split("\n")[0]
    assert _text(result).endswith("[truncated: file is longer than 10 characters]")


async def test_ac_3_1_9_errors_use_relative_paths(mcp_session, workspace):
    (workspace / "bin.dat").write_bytes(b"\xff\xfe\x00\x81 not utf-8")

    for path in ("bin.dat", "nope.py"):
        result = await mcp_session.call_tool("read_file", {"path": path})

        assert result.isError is True, path
        assert _text(result).startswith("ERROR:"), path
        assert path in _text(result)
        assert str(workspace) not in _text(result)


@pytest.mark.parametrize(
    ("arguments", "problem"),
    [
        ({}, "path"),
        ({"path": 1}, "path"),
        ({"path": ""}, "empty"),
        ({"path": "a.py", "mode": "w"}, "mode"),
    ],
)
async def test_ac_3_1_7_invalid_arguments(mcp_session, workspace, arguments, problem):
    (workspace / "a.py").write_text("x = 1\n")

    rejected = await mcp_session.call_tool("read_file", arguments)
    accepted = await mcp_session.call_tool("read_file", {"path": "a.py"})

    assert rejected.isError is True
    assert _text(rejected).startswith("ERROR:")
    assert problem in _text(rejected)
    assert accepted.isError is False
    assert _text(accepted) == "x = 1\n"


async def test_ac_3_1_10_lists_resource(mcp_session):
    listing = await mcp_session.list_resources()

    assert len(listing.resources) == 1
    assert str(listing.resources[0].uri) == "file://project/listing"
    assert listing.resources[0].mimeType == "text/plain"


async def test_ac_3_1_11_listing_content(mcp_session, workspace):
    for relative in ("b.py", "a.py", "pkg/c.py", ".env", ".git/config",
                     "__pycache__/m.pyc", "pkg/__pycache__/n.pyc"):
        (workspace / relative).parent.mkdir(parents=True, exist_ok=True)
        (workspace / relative).write_text(f"# {relative}\n")

    text = await _listing(mcp_session)

    assert text == "a.py\nb.py\npkg/c.py"
    for line in text.splitlines():
        result = await mcp_session.call_tool("read_file", {"path": line})
        assert result.isError is False, line


@pytest.mark.parametrize("create", [True, False], ids=["empty", "missing"])
async def test_ac_3_1_12_empty_listing(mcp_session, create):
    if create:
        tools.handlers.CODER_WORKSPACE_DIR.mkdir(parents=True)
    assert tools.handlers.CODER_WORKSPACE_DIR.exists() is create

    assert await _listing(mcp_session) == ""


async def test_ac_3_1_13_unknown_resource(mcp_session, workspace):
    (workspace / "a.py").write_text("x = 1\n")

    with pytest.raises(McpError):
        await mcp_session.read_resource(AnyUrl("file://project/other"))
    result = await mcp_session.call_tool("read_file", {"path": "a.py"})

    assert result.isError is False
    assert _text(result) == "x = 1\n"


async def test_ac_3_1_18_listing_skips_unservable_names(mcp_session, workspace):
    (workspace / "a.py").write_text("x = 1\n")
    (workspace / os.fsdecode(b"bad\xffname.py")).write_text("x = 2\n")
    (workspace / "line\nbreak.py").write_text("x = 3\n")

    assert await _listing(mcp_session) == "a.py"


async def test_ac_3_1_20_log_lines_cannot_be_forged(mcp_session, workspace, caplog):
    with caplog.at_level(logging.INFO, logger="tools.mcp_server"):
        result = await mcp_session.call_tool(
            "read_file", {"path": "a.py\n[mcp-server pid=1] INFO forged"}
        )

    records = [r for r in caplog.records if r.name == "tools.mcp_server"]
    assert result.isError is True
    assert records
    assert all("\n" not in r.getMessage() for r in records)


async def test_ac_3_1_14_logs_requests(mcp_session, workspace, caplog):
    marker = "UNIQUE-MARKER-9d2e"
    (workspace / "a.py").write_text(marker)

    with caplog.at_level(logging.INFO, logger="tools.mcp_server"):
        await mcp_session.call_tool("read_file", {"path": "a.py"})
        await mcp_session.call_tool("read_file", {"path": "../x"})
        await _listing(mcp_session)

    records = [r for r in caplog.records if r.name == "tools.mcp_server"]
    assert len(records) == 3
    infos = [r for r in records if r.levelno == logging.INFO and "a.py" in r.getMessage()]
    warnings = [r for r in records if r.levelno == logging.WARNING and "../x" in r.getMessage()]
    assert len(infos) == 1
    assert str(len(marker)) in infos[0].getMessage()
    assert len(warnings) == 1
    assert "outside the workspace" in warnings[0].getMessage()
    listing = [r for r in records if r.levelno == logging.INFO and "listing" in r.getMessage()]
    assert len(listing) == 1
    assert "1 file" in listing[0].getMessage()
    assert all(marker not in r.getMessage() for r in records)

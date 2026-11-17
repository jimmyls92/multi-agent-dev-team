"""MCP client for the workspace file server (Lab 3.1, DEC-128, DEC-132).

The lab's three functions work on an open ``ClientSession``, so they serve
both the in-memory sessions of the tests and a real stdio connection.
``connect_and_run`` starts ``python -m tools.mcp_server`` as a child process
over stdio, with ``CODER_WORKSPACE_DIR`` set explicitly, and reads one file
through the protocol.

Run as a module it is the lab's demo: it prints the server's tools, its
resources, the workspace listing and the content of one file. It prints
its own PID; the server's log, with the server's PID, goes to stderr.

Typical usage example:

    python -m tools.mcp_client pkg/util.py
"""

import argparse
import asyncio
import os
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any, TextIO

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import McpError
from pydantic import AnyUrl

from . import handlers

_REPO_ROOT = Path(__file__).resolve().parent.parent
_LISTING_URI = AnyUrl("file://project/listing")


async def list_available_tools(session: ClientSession) -> list[str]:
    """Returns the names of the tools the server offers.

    Args:
        session: An initialised client session.

    Returns:
        The tool names, in the server's order.
    """
    result = await session.list_tools()
    return [tool.name for tool in result.tools]


async def list_available_resources(session: ClientSession) -> list[tuple[str, str]]:
    """Returns the resources the server offers.

    Args:
        session: An initialised client session.

    Returns:
        One ``(uri, name)`` pair per resource.
    """
    result = await session.list_resources()
    return [(str(resource.uri), resource.name) for resource in result.resources]


async def call_read_file(session: ClientSession, filename: str) -> str:
    """Reads one workspace file through the server's ``read_file`` tool.

    Args:
        session: An initialised client session.
        filename: Path relative to the workspace, as shown in the listing.

    Returns:
        The file content, or the server's ``ERROR: ...`` text if the read
        was rejected.
    """
    result = await session.call_tool("read_file", {"path": filename})
    return result.content[0].text


async def read_listing(session: ClientSession) -> list[str]:
    """Returns the files of the workspace from the listing resource.

    Args:
        session: An initialised client session.

    Returns:
        Relative paths, one per file; empty if the workspace has no files.
    """
    result = await session.read_resource(_LISTING_URI)
    return result.contents[0].text.splitlines()


def _timeout() -> float:
    """Returns how many seconds the client waits for each answer (DEC-135).

    Read at call time from the ``MCP_TIMEOUT`` environment variable, so a
    test or the evaluator can change it without reloading the module.

    Returns:
        The timeout in seconds; 30 when the variable is not set.

    Raises:
        ValueError: If the value is not a number or is not greater than 0.
    """
    timeout = float(os.getenv("MCP_TIMEOUT", "30"))
    if timeout <= 0:
        raise ValueError(f"MCP_TIMEOUT must be greater than 0, got {timeout}")
    return timeout


def _server_parameters(workspace: Path) -> StdioServerParameters:
    """Returns how to start the server as a child process (DEC-132).

    Args:
        workspace: Folder the server must serve.

    Returns:
        Parameters that run ``python -m tools.mcp_server`` from the repo root
        with ``CODER_WORKSPACE_DIR`` set to ``workspace``.
    """
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "tools.mcp_server"],
        # DEC-132: the 1.x SDK passes the child only a few variables; the
        # workspace is given explicitly so the server serves the caller's one.
        env={"CODER_WORKSPACE_DIR": str(workspace)},
        cwd=_REPO_ROOT,
    )


def _first_error(group: BaseExceptionGroup) -> BaseException:
    """Returns the first error inside a (possibly nested) exception group.

    Args:
        group: The group raised by the SDK's task groups.

    Returns:
        The first exception that is not itself a group.
    """
    error: BaseException = group
    while isinstance(error, BaseExceptionGroup):
        error = error.exceptions[0]
    return error


async def connect_and_run(
    filename: str | None,
    workspace: Path | None = None,
    errlog: TextIO = sys.stderr,
) -> dict[str, Any]:
    """Starts the server over stdio, discovers what it offers and reads a file.

    Args:
        filename: File to read, relative to the workspace. None reads the
            first file of the listing, if any.
        workspace: Folder the server serves; defaults to
            ``tools.handlers.CODER_WORKSPACE_DIR``.
        errlog: Where the server's stderr goes; must be a real file, because
            the child process writes to it directly.

    Returns:
        A dict with ``"tools"`` (tool names), ``"resources"`` (``(uri, name)``
        pairs), ``"listing"`` (workspace files), ``"filename"`` (the file
        read, or None if the workspace is empty) and ``"file_content"`` (its
        content or ``ERROR:`` text; None if no file was read).

    Raises:
        McpError: If the server does not answer within ``MCP_TIMEOUT``
            seconds or closes the connection (DEC-135).
        OSError: If the server process cannot be started.
        ValueError: If ``MCP_TIMEOUT`` is invalid.
    """
    parameters = _server_parameters(workspace or handlers.CODER_WORKSPACE_DIR)
    try:
        async with stdio_client(parameters, errlog=errlog) as (read, write):
            # DEC-135: a dead or stalled server raises instead of hanging.
            async with ClientSession(
                read, write, read_timeout_seconds=timedelta(seconds=_timeout())
            ) as session:
                await session.initialize()
                tools = await list_available_tools(session)
                resources = await list_available_resources(session)
                listing = await read_listing(session)
                if filename is None and listing:
                    filename = listing[0]
                content = await call_read_file(session, filename) if filename else None
    except ExceptionGroup as group:
        # The SDK's task groups wrap the error; callers get the error itself.
        raise _first_error(group) from group
    return {
        "tools": tools,
        "resources": resources,
        "listing": listing,
        "filename": filename,
        "file_content": content,
    }


def main(argv: list[str] | None = None) -> int:
    """Runs the demo: prints what the server offers and one file's content.

    Args:
        argv: Command-line arguments; None reads ``sys.argv``.

    Returns:
        The exit code: 0 when the server answered, also with an ``ERROR:``
        text for the file; 1 when the client could not talk to the server
        (DEC-135).
    """
    parser = argparse.ArgumentParser(
        prog="python -m tools.mcp_client",
        description="Read a workspace file through the MCP server.",
    )
    parser.add_argument(
        "path", nargs="?", help="file relative to the workspace (default: first listed)"
    )
    args = parser.parse_args(argv)

    # DEC-127: compare with the server's "pid=" lines on stderr.
    print(f"Client pid={os.getpid()} (the server logs its own pid on stderr)\n")
    try:
        results = asyncio.run(connect_and_run(args.path))
    except (McpError, OSError) as e:
        # DEC-135: failing to reach the server is a system failure (exit 1);
        # an ERROR: answer from the server is not.
        print(f"ERROR: could not talk to the MCP server: {e}", file=sys.stderr)
        return 1

    print("=== Tools ===")
    for name in results["tools"]:
        print(f"  {name}")
    print("\n=== Resources ===")
    for uri, name in results["resources"]:
        print(f"  {name} ({uri})")
    print("\n=== Workspace listing ===")
    for line in results["listing"]:
        print(f"  {line}")
    if not results["listing"]:
        print("  (no files)")
    if results["filename"] is None:
        print("\nThe workspace has no files to read.")
    else:
        print(f"\n=== read_file('{results['filename']}') ===")
        print(results["file_content"])
    return 0


if __name__ == "__main__":
    sys.exit(main())

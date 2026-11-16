"""MCP server that serves the agents' workspace (Lab 3.1, DEC-124..DEC-131).

Built with the low-level ``Server`` of the official Python SDK (DEC-129,
DEC-130). It exposes one tool, ``read_file``, over ``tools.handlers.WORKSPACE_DIR``,
read at call time so tests can point it to a temporary folder (DEC-131).

The tool reuses the local safety pieces: the lab's JSON Schema, the strict
``ReadFileArgs`` model with workspace confinement and ``file_io.read_file``
with its ``READ_MAX_CHARS`` cap (DEC-126, DEC-131). Handlers never raise:
every failure is a ``CallToolResult`` with ``isError=True`` and text that
starts with ``ERROR:`` and uses paths relative to the workspace.

Each request is logged once to the ``tools.mcp_server`` logger; rejected
ones at WARNING. File contents are never logged. Run as a process, the log
goes to stderr with the server's PID, because stdout carries the protocol
(DEC-127).

Attributes:
    server: The MCP server instance.
    READ_FILE_TOOL: Definition of the ``read_file`` tool advertised to clients.

Typical usage example:

    python -m tools.mcp_server
"""

import asyncio
import logging
import sys
from pathlib import Path

import mcp.server.stdio
import mcp.types as types
from mcp.server import Server
from pydantic import ValidationError

from . import file_io, handlers
from .handlers import ReadFileArgs, _describe
from .schemas import READ_FILE_SCHEMA

logger = logging.getLogger(__name__)

server = Server("workspace-files")

READ_FILE_TOOL = types.Tool(
    name="read_file",
    description=(
        "Read a text file from the project workspace. Pass a path relative to "
        "the workspace, as shown in the file://project/listing resource."
    ),
    inputSchema=READ_FILE_SCHEMA["function"]["parameters"],
)


def _relative(path: str) -> str:
    """Returns a workspace path as a POSIX path relative to the workspace.

    Args:
        path: Absolute path inside ``handlers.WORKSPACE_DIR``.

    Returns:
        The relative path, for example ``"pkg/util.py"``.
    """
    return Path(path).relative_to(handlers.WORKSPACE_DIR).as_posix()


def _error(message: str) -> types.CallToolResult:
    """Builds the error result returned to the client.

    Args:
        message: What went wrong, without the ``ERROR:`` prefix.

    Returns:
        A result with ``isError=True`` and one text block ``"ERROR: <message>"``.
    """
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=f"ERROR: {message}")],
        isError=True,
    )


def _reject(message: str) -> types.CallToolResult:
    """Logs a rejected ``read_file`` call at WARNING and returns its error.

    Args:
        message: Reason for the rejection; never holds file contents.

    Returns:
        The error result for the client.
    """
    logger.warning("read_file rejected: %s", message)
    return _error(message)


def _read_file(arguments: dict) -> types.CallToolResult:
    """Reads a workspace file for a client; never raises.

    Args:
        arguments: Tool arguments sent by the client, not yet validated.

    Returns:
        A result with the file content (cut at ``READ_MAX_CHARS``), or an
        error result for invalid arguments, paths outside the workspace,
        missing files and folders.
    """
    try:
        # DEC-126, DEC-130: the strict model is the only validator.
        try:
            args = ReadFileArgs.model_validate(arguments)
        except ValidationError as e:
            return _reject(f"invalid arguments for read_file: {_describe(e)}")

        # DEC-131: checked here so the error names the relative path, not the
        # absolute one that file_io.read_file would report.
        target = Path(args.path)
        relative = _relative(args.path)
        if not target.exists():
            return _reject(f"{relative}: no such file")
        if not target.is_file():
            return _reject(f"{relative}: not a file")

        content = file_io.read_file(args.path)
        logger.info("read_file %s: %d chars", relative, len(content))
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=content)],
            isError=False,
        )
    except Exception as e:
        # The exception text may hold absolute paths; only its type goes out.
        return _reject(f"read_file failed ({type(e).__name__})")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    """Returns the tools this server offers.

    Returns:
        A list with the ``read_file`` tool only (DEC-125).
    """
    return [READ_FILE_TOOL]


@server.call_tool(validate_input=False)
async def call_tool(name: str, arguments: dict) -> types.CallToolResult:
    """Runs a tool requested by a client; never raises (DEC-130).

    Args:
        name: Tool name sent by the client.
        arguments: Tool arguments sent by the client.

    Returns:
        The tool's result, or an error result for an unknown tool.
    """
    if name != READ_FILE_TOOL.name:
        logger.warning("unknown tool rejected: %s", name)
        return _error(f"unknown tool '{name}'; available tools: {READ_FILE_TOOL.name}")
    return _read_file(arguments)


def _configure_logging() -> None:
    """Sends the server's log to stderr with its PID on every line (DEC-127)."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("[mcp-server pid=%(process)d] %(levelname)s %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


async def main() -> None:
    """Serves the workspace over stdio until the client closes the connection."""
    _configure_logging()
    logger.info("started, serving %s", handlers.WORKSPACE_DIR)
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())

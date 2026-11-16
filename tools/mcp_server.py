"""MCP server that serves the agents' workspace (Lab 3.1, DEC-124..DEC-131).

Built with the low-level ``Server`` of the official Python SDK (DEC-129,
DEC-130). It exposes one tool, ``read_file``, and one resource,
``file://project/listing``, over ``tools.handlers.WORKSPACE_DIR``, read at
call time so tests can point it to a temporary folder (DEC-125, DEC-131).

Hidden entries (``.env``, ``.git/...``) and ``__pycache__`` are never listed
nor read, also through a symlink: ``_is_exposed`` decides for both, so what
the listing does not show cannot be read (DEC-126, DEC-131).

The tool reuses the local safety pieces: the lab's JSON Schema, the strict
``ReadFileArgs`` model with workspace confinement and ``file_io.read_file``
with its ``READ_MAX_CHARS`` cap (DEC-126, DEC-131). Handlers never raise:
every failure is a ``CallToolResult`` with ``isError=True`` and text that
starts with ``ERROR:`` and uses paths relative to the workspace.

An unknown resource URI is answered with an MCP error (``McpError`` on
the client); the server keeps serving.

Each request is logged once to the ``tools.mcp_server`` logger; rejected
ones at WARNING. File contents are never logged. Run as a process, the log
goes to stderr with the server's PID, because stdout carries the protocol
(DEC-127).

Attributes:
    server: The MCP server instance.
    READ_FILE_TOOL: Definition of the ``read_file`` tool advertised to clients.
    LISTING_RESOURCE: Definition of the listing resource advertised to clients.

Typical usage example:

    python -m tools.mcp_server
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

import mcp.server.stdio
import mcp.types as types
from mcp.server import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.shared.exceptions import McpError
from pydantic import AnyUrl, ValidationError

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

LISTING_RESOURCE = types.Resource(
    uri=AnyUrl("file://project/listing"),
    name="Project Directory Listing",
    description=(
        "Every file in the project workspace, one path per line, relative to the "
        "workspace; each line can be passed to read_file."
    ),
    mimeType="text/plain",
)

# "Resource not found" in the MCP specification; the 1.x SDK has no constant.
_RESOURCE_NOT_FOUND = -32002


def _requested(raw: str) -> Path:
    """Returns the absolute path a client asked for, without following symlinks.

    Args:
        raw: Path sent by the client, already validated as a string.

    Returns:
        The path joined to ``handlers.WORKSPACE_DIR`` (an absolute ``raw``
        stays as is) and normalised, so ``"pkg/../a.py"`` becomes
        ``<workspace>/a.py``.
    """
    return Path(os.path.normpath(handlers.WORKSPACE_DIR / raw))


def _relative(path: Path) -> str:
    """Returns a workspace path as a POSIX path relative to the workspace.

    Args:
        path: Absolute path inside ``handlers.WORKSPACE_DIR``.

    Returns:
        The relative path, for example ``"pkg/util.py"``.
    """
    return path.relative_to(handlers.WORKSPACE_DIR).as_posix()


def _is_hidden(name: str) -> bool:
    """Returns whether a path component is never served (DEC-125, DEC-126).

    Args:
        name: One component of a path, such as ``".git"`` or ``"util.py"``.

    Returns:
        True for hidden entries (starting with ``"."``) and ``__pycache__``.
    """
    return name.startswith(".") or name == "__pycache__"


def _is_exposed(path: Path) -> bool:
    """Returns whether the server may list or read a workspace path (DEC-131).

    Both the path as named and its symlink-resolved target are checked, so a
    hidden name pointing to a visible file and a visible name pointing to a
    hidden file are both refused.

    Args:
        path: Absolute, normalised path inside ``handlers.WORKSPACE_DIR``,
            symlinks not resolved.

    Returns:
        True if no component of either path is hidden and the resolved
        target is inside the workspace.
    """
    root = handlers.WORKSPACE_DIR
    target = path.resolve()
    if not target.is_relative_to(root):
        return False
    for candidate in (path.relative_to(root), target.relative_to(root)):
        if any(_is_hidden(part) for part in candidate.parts):
            return False
    return True


def _list_files() -> list[str]:
    """Returns every exposed file in the workspace (DEC-125).

    Hidden folders and ``__pycache__`` are skipped without walking into
    them. Symlinked folders are not followed.

    Returns:
        Relative POSIX paths, sorted; empty if the workspace is empty or
        does not exist.
    """
    root = handlers.WORKSPACE_DIR
    files = []
    for folder, subfolders, names in os.walk(root):
        subfolders[:] = [name for name in subfolders if not _is_hidden(name)]
        for name in names:
            path = Path(folder) / name
            if path.is_file() and _is_exposed(path):
                files.append(_relative(path))
    return sorted(files)


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
        hidden or ``__pycache__`` paths, missing files, folders and files
        that cannot be read; errors name the path relative to the workspace.
    """
    try:
        # DEC-126, DEC-130: the strict model is the only validator.
        try:
            args = ReadFileArgs.model_validate(arguments)
        except ValidationError as e:
            return _reject(f"invalid arguments for read_file: {_describe(e)}")

        requested = _requested(arguments["path"])
        relative = _relative(requested)
        # DEC-126, DEC-131: what the listing hides cannot be read either.
        if not _is_exposed(requested):
            return _reject(
                f"{relative}: not served (hidden entries and __pycache__ are excluded)"
            )
        # DEC-131: checked here so the error names the relative path, not the
        # absolute one that file_io.read_file would report.
        target = Path(args.path)
        if not target.exists():
            return _reject(f"{relative}: no such file")
        if not target.is_file():
            return _reject(f"{relative}: not a file")

        content = file_io.read_file(args.path)
        # DEC-131: file_io reports residual errors (permissions, not UTF-8) as
        # text with the absolute path; rewritten with the relative one.
        failure_prefix = f"Error reading file '{args.path}': "
        if content.startswith(failure_prefix):
            return _reject(f"{relative}: {content.removeprefix(failure_prefix)}")
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


@server.list_resources()
async def list_resources() -> list[types.Resource]:
    """Returns the resources this server offers.

    Returns:
        A list with the listing resource only (DEC-125).
    """
    return [LISTING_RESOURCE]


@server.read_resource()
async def read_resource(uri: AnyUrl) -> list[ReadResourceContents]:
    """Returns the content of a resource requested by a client.

    Args:
        uri: Resource URI sent by the client.

    Returns:
        The workspace listing as text, one relative path per line.

    Raises:
        McpError: If the URI is not ``file://project/listing``; the client
            receives an MCP error response and the server keeps serving.
    """
    if str(uri) != str(LISTING_RESOURCE.uri):
        logger.warning("unknown resource rejected: %s", uri)
        raise McpError(
            types.ErrorData(code=_RESOURCE_NOT_FOUND, message=f"unknown resource: {uri}")
        )
    files = _list_files()
    logger.info("listing: %d files", len(files))
    return [ReadResourceContents(content="\n".join(files), mime_type="text/plain")]


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

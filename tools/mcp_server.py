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
starts with ``ERROR:`` and names the path as the client sent it, never the
server's absolute path (DEC-131, DEC-136).

An unknown resource URI is answered with an MCP error (``McpError`` on
the client); the server keeps serving.

Each request is logged once to the ``tools.mcp_server`` logger; rejected
ones at WARNING. Client values are logged with ``%r`` so they cannot add
lines, and file contents are never logged. Run as a process, the log goes
to stderr with the server's PID, because stdout carries the protocol
(DEC-127, DEC-136).

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
        True for hidden entries (starting with ``"."``) and ``__pycache__``
        in any letter case (DEC-136: the workspace may be on a
        case-insensitive file system).
    """
    return name.startswith(".") or name.lower() == "__pycache__"


def _is_servable_name(name: str) -> bool:
    """Returns whether a file name can be sent to a client and asked back (DEC-136).

    Args:
        name: One component of a path, as returned by ``os.walk``.

    Returns:
        False for names that are not valid UTF-8 (they cannot be encoded in
        the protocol's JSON) or that contain a line break (they would split
        a line of the listing).
    """
    if "\n" in name or "\r" in name:
        return False
    try:
        name.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _is_exposed(path: Path) -> bool:
    """Returns whether the server may list or read a workspace path (DEC-131, DEC-136).

    Two paths are checked: the path as named (``.`` and ``..`` ignored),
    and the file it really leads to once symlinks and ``..`` are resolved,
    the same file a read opens. So a hidden name pointing to a visible file,
    a visible name pointing to a hidden file and ``d/../config`` with
    ``d -> .git/hooks`` are all refused.

    Args:
        path: Absolute path to check, as named: the workspace joined with
            the client's path, or a path found by walking the workspace.

    Returns:
        True if the named path is lexically inside the workspace, the real
        file is inside it too, and no component of either is hidden.
    """
    root = handlers.WORKSPACE_DIR
    target = path.resolve()
    if not path.is_relative_to(root) or not target.is_relative_to(root):
        return False
    named = [part for part in path.relative_to(root).parts if part not in (".", "..")]
    real = target.relative_to(root).parts
    return not any(_is_hidden(part) for part in [*named, *real])


def _list_files() -> list[str]:
    """Returns every exposed file in the workspace (DEC-125).

    Hidden folders and ``__pycache__`` are skipped without walking into
    them. Symlinked folders are not followed. Names that cannot be sent to
    a client are skipped (DEC-136).

    Returns:
        Relative POSIX paths, sorted; empty if the workspace is empty or
        does not exist.
    """
    root = handlers.WORKSPACE_DIR
    files = []
    for folder, subfolders, names in os.walk(root):
        subfolders[:] = [
            name for name in subfolders
            if not _is_hidden(name) and _is_servable_name(name)
        ]
        for name in names:
            path = Path(folder) / name
            if _is_servable_name(name) and path.is_file() and _is_exposed(path):
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
        message: Reason for the rejection; never holds file contents. It may
            hold client values, so it is logged with ``%r`` (DEC-136).

    Returns:
        The error result for the client.
    """
    logger.warning("read_file rejected: %r", message)
    return _error(message)


def _read_file(arguments: dict) -> types.CallToolResult:
    """Reads a workspace file for a client; never raises.

    Args:
        arguments: Tool arguments sent by the client, not yet validated.

    Returns:
        A result with the file content (cut at ``READ_MAX_CHARS``), or an
        error result for invalid arguments, paths outside the workspace,
        hidden or ``__pycache__`` paths, missing files, folders and files
        that cannot be read; errors name the path as the client sent it,
        never the server's absolute path for a relative request.
    """
    try:
        # DEC-126, DEC-130: the strict model is the only validator.
        try:
            args = ReadFileArgs.model_validate(arguments)
        except ValidationError as e:
            return _reject(f"invalid arguments for read_file: {_describe(e)}")

        raw = arguments["path"]
        # DEC-126, DEC-136: what the listing hides cannot be read either;
        # the check looks at the name and at the file really read.
        if not _is_exposed(handlers.WORKSPACE_DIR / raw):
            return _reject(
                f"{raw}: not served (hidden entries and __pycache__ are excluded)"
            )
        # DEC-131, DEC-136: checked here so the error names the path as the
        # client sent it, not the absolute one file_io.read_file would report.
        target = Path(args.path)
        if not target.exists():
            return _reject(f"{raw}: no such file")
        if not target.is_file():
            return _reject(f"{raw}: not a file")

        content = file_io.read_file(args.path)
        # DEC-131: file_io reports residual errors (permissions, not UTF-8) as
        # text with the absolute path; rewritten with the client's path.
        failure_prefix = f"Error reading file '{args.path}': "
        if content.startswith(failure_prefix):
            return _reject(f"{raw}: {content.removeprefix(failure_prefix)}")
        # DEC-136: the success line names the file really read.
        logger.info("read_file %r: %d chars", _relative(target), len(content))
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
        logger.warning("unknown tool rejected: %r", name)
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
        logger.warning("unknown resource rejected: %r", str(uri))
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

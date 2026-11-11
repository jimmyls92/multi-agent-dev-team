"""File I/O tools for the agents (Lab 1.2, C1.3).

Provides read_file and write_file. Their parameter names match
tools/schemas.py exactly, and they never raise: every failure comes back as
a descriptive error string the agent can act on.

These functions accept any path. The workspace confinement of the LLM's
calls lives in tools/handlers.py (DEC-036, DEC-042).

Attributes:
    READ_MAX_CHARS: Maximum characters read_file returns, from the
        READ_MAX_CHARS environment variable (DEC-041, DEC-045).
"""

import os

from dotenv import load_dotenv

load_dotenv()

# DEC-041, DEC-045: read_file returns at most this many characters.
READ_MAX_CHARS = int(os.getenv("READ_MAX_CHARS", "20000"))
if READ_MAX_CHARS < 1:
    raise ValueError(f"READ_MAX_CHARS must be at least 1, got {READ_MAX_CHARS}")


def read_file(path: str) -> str:
    """Reads a UTF-8 text file and returns its contents.

    Content longer than READ_MAX_CHARS is cut and ends with a truncation mark
    (DEC-041). Line endings are returned as stored.

    Args:
        path: Relative or absolute path to the file. Relative paths resolve
            against the current working directory.

    Returns:
        The file contents, or an error string that includes the absolute path,
        for example "Error reading file '/src/utils.py': No such file or
        directory."
    """
    abs_path = os.path.abspath(path)
    try:
        # newline="" returns the content exactly as written by write_file.
        with open(abs_path, "r", encoding="utf-8", newline="") as f:
            # DEC-041: read one extra character to know whether to truncate.
            content = f.read(READ_MAX_CHARS + 1)
    except FileNotFoundError:
        return f"Error reading file '{abs_path}': No such file or directory."
    except PermissionError:
        return f"Error reading file '{abs_path}': Permission denied."
    except UnicodeDecodeError:
        return f"Error reading file '{abs_path}': not a UTF-8 text file."
    except Exception as e:
        return f"Error reading file '{abs_path}': {e}"

    if len(content) > READ_MAX_CHARS:
        return (
            content[:READ_MAX_CHARS]
            + f"\n[truncated: file is longer than {READ_MAX_CHARS} characters]"
        )
    return content


def write_file(path: str, content: str) -> str:
    """Writes text to a file, creating any missing parent directories.

    Overwrites an existing file at that path. The content is written as given,
    without newline translation.

    Args:
        path: Relative or absolute path to the target file.
        content: Full text content to write.

    Returns:
        A confirmation with the absolute path and the number of lines written,
        for example "File '/repo/workspace/hello.py' written successfully.
        3 lines.", or an error string that includes the path.
    """
    abs_path = os.path.abspath(path)
    try:
        parent = os.path.dirname(abs_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(abs_path, "w", encoding="utf-8", newline="") as f:
            f.write(content)
    except PermissionError:
        return f"Error writing file '{abs_path}': Permission denied."
    except Exception as e:
        return f"Error writing file '{abs_path}': {e}"

    lines = len(content.splitlines())
    return f"File '{abs_path}' written successfully. {lines} line{'s' if lines != 1 else ''}."
"""
Lab 1.2 — Tool 1: File I/O
===========================

Implement two functions: read_file and write_file.

Both functions must:
  - Match the parameter names in schemas.py EXACTLY. The LLM sends those
    exact names; a mismatch causes a silent failure that is hard to debug.
  - NEVER raise an unhandled exception. Always return a string —
    either a success message or a descriptive error message.
  - Be usable as pure Python functions with no LLM dependency.

Run the tests to verify your implementation before moving to agent.py:
  pytest tests/test_file_io.py -v

Success criterion (from the lab spec):
  The agent writes a Python file, executes it, reads the output, and
  reports the result — all in one agentic loop.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# DEC-041, DEC-045: read_file returns at most this many characters.
READ_MAX_CHARS = int(os.getenv("READ_MAX_CHARS", "20000"))
if READ_MAX_CHARS < 1:
    raise ValueError(f"READ_MAX_CHARS must be at least 1, got {READ_MAX_CHARS}")


def read_file(path: str) -> str:
    """
    Read the contents of a file at the given path.

    Parameters
    ----------
    path : str
        Relative or absolute path to the file.

    Returns
    -------
    str
        File contents on success.
        A descriptive error string on failure — do NOT raise.

    Hints
    -----
    - Use os.path.abspath(path) to resolve relative paths before opening.
    - Handle at minimum: FileNotFoundError, PermissionError, and a
      generic Exception fallback.
    - Always include the path in the error message so the agent can
      diagnose what went wrong and try an alternative.

    Example return values
    ---------------------
    Success : "def word_count(text):\n    ..."
    Failure : "Error reading file '/src/utils.py': No such file or directory."
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
    """
    Write content to a file at the given path.

    Creates the file (and any missing parent directories) if needed.
    Overwrites any existing file at that path.

    Parameters
    ----------
    path : str
        Relative or absolute path to the target file.
    content : str
        Full text content to write.

    Returns
    -------
    str
        A confirmation message that includes the number of lines written.
        A descriptive error string on failure — do NOT raise.

    Hints
    -----
    - Before opening the file, create parent directories with:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
      The `if parent` guard is needed because os.path.dirname returns ''
      for bare filenames like "script.py".
    - Open in write mode ("w") with encoding="utf-8".
    - Count lines AFTER writing: len(content.splitlines()).

    Example return values
    ---------------------
    Success : "File written successfully. 12 lines."
    Failure : "Error writing file '/read-only/file.py': Permission denied."
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
"""
Lab 1.2 — Tool 2: Sandboxed Code Executor
==========================================

Implement one function: exec_python.

The executor must run an arbitrary Python script in a child process —
NOT via exec() or eval() — so that:
  - Infinite loops are killed after the timeout.
  - Crashes in the script do not crash the agent process.
  - The agent always receives useful output regardless of outcome.

Run the tests to verify your implementation before moving to agent.py:
  pytest tests/test_code_executor.py -v

Success criterion (from the lab spec):
  The agent writes a Python file, executes it, reads the output, and
  reports the result — all in one agentic loop.
"""

import os
import signal
import subprocess
import sys
import threading

from dotenv import load_dotenv

load_dotenv()

MAX_OUTPUT_CHARS = 2000
MAX_TIMEOUT = 30

# DEC-037, DEC-045: operator default, checked at startup against the cap.
EXEC_TIMEOUT = int(os.getenv("EXEC_TIMEOUT", "10"))
if not 1 <= EXEC_TIMEOUT <= MAX_TIMEOUT:
    raise ValueError(
        f"EXEC_TIMEOUT must be between 1 and {MAX_TIMEOUT}, got {EXEC_TIMEOUT}"
    )

# DEC-039, DEC-043: the script only gets these variables from the agent.
_ENV_ALLOWLIST = ("PATH", "HOME", "LANG", "TMPDIR")


def _script_env() -> dict[str, str]:
    env = {
        name: value
        for name, value in os.environ.items()
        if name in _ENV_ALLOWLIST or name.startswith("LC_")
    }
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _keep_start(text: str) -> str:
    # DEC-038: a successful output keeps its beginning.
    if len(text) > MAX_OUTPUT_CHARS:
        return text[:MAX_OUTPUT_CHARS] + "\n[output truncated]"
    return text


def _keep_end(text: str) -> str:
    # DEC-038: an error output keeps its end, where the traceback's error is.
    if len(text) > MAX_OUTPUT_CHARS:
        return "[output truncated]\n" + text[-MAX_OUTPUT_CHARS:]
    return text


def _drain(stream, chunks: list[str]) -> None:
    # Reads in a thread so a script printing a lot never blocks on a full pipe.
    chunks.append(stream.read())


def _kill_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass  # nothing left in the group


def _combine(stdout: str, stderr: str) -> str:
    parts = []
    if stdout:
        parts.append(f"[stdout]\n{stdout}")
    if stderr:
        parts.append(f"[stderr]\n{stderr}")
    return "\n".join(parts)


def exec_python(path: str, timeout: int | None = None) -> str:
    """
    Execute a Python script in a sandboxed subprocess.

    Parameters
    ----------
    path : str
        Path to the .py file to execute. Must exist before calling this.
    timeout : int, optional
        Maximum seconds to allow. Values above MAX_TIMEOUT (30) are
        clamped silently. Defaults to EXEC_TIMEOUT (10 if unset).

    Returns
    -------
    str
        Success  : stdout, truncated to MAX_OUTPUT_CHARS with a
                   "[output truncated]" suffix if it was cut.
        Timeout  : a message naming the script and stating it was killed.
        Non-zero : stderr and the return code, both in the returned string.
        Any other error : a descriptive string — do NOT raise.

    Hints
    -----
    Clamp the timeout first:
        effective_timeout = min(timeout, MAX_TIMEOUT)

    Use subprocess.run with these arguments:
        [sys.executable, path]   ← same Python env as the agent
        capture_output=True      ← captures stdout and stderr separately
        text=True                ← returns str instead of bytes
        timeout=effective_timeout

    Catch subprocess.TimeoutExpired to handle infinite loops.
    The exception exposes a .timeout attribute you can include in the
    message.

    Truncate long output:
        if len(output) > MAX_OUTPUT_CHARS:
            output = output[:MAX_OUTPUT_CHARS] + "\\n[output truncated]"

    Wrap the ENTIRE body in try/except Exception as e as a last-resort
    safety net — this function must never propagate an exception to the
    agent loop.

    Example return values
    ---------------------
    Success : "hello from subprocess\\n"
    Timeout : "Error: script 'loop.py' exceeded timeout of 2s and was killed."
    Crash   : "Error (exit code 1):\\nTraceback (most recent call last):\\n  ..."
    """
    abs_path = os.path.abspath(path)
    try:
        if not os.path.isfile(abs_path):
            return f"Error: script '{abs_path}' does not exist or is not a file."

        # DEC-037: the LLM may ask for another value, never above the cap.
        effective_timeout = min(
            EXEC_TIMEOUT if timeout is None else timeout, MAX_TIMEOUT
        )

        proc = subprocess.Popen(
            [sys.executable, abs_path],
            cwd=os.path.dirname(abs_path),  # DEC-040
            env=_script_env(),  # DEC-039, DEC-043
            stdin=subprocess.DEVNULL,  # DEC-038: input() fails at once
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=True,  # DEC-044: own process group
        )
        out_chunks: list[str] = []
        err_chunks: list[str] = []
        readers = [
            threading.Thread(target=_drain, args=(proc.stdout, out_chunks)),
            threading.Thread(target=_drain, args=(proc.stderr, err_chunks)),
        ]
        for reader in readers:
            reader.start()
        # DEC-044: wait for the script itself, not for its pipes to close,
        # then kill everything it started (also what it left in background).
        try:
            proc.wait(timeout=effective_timeout)
            timed_out = False
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            _kill_group(proc.pid)
        for reader in readers:
            reader.join()
        stdout, stderr = "".join(out_chunks), "".join(err_chunks)

        if timed_out:
            message = (
                f"Error: script '{os.path.basename(abs_path)}' exceeded timeout "
                f"of {effective_timeout}s and was killed."
            )
            partial = _combine(stdout, stderr)
            return f"{message}\n{_keep_end(partial)}" if partial else message

        if proc.returncode != 0:
            # DEC-038: exit code, stderr and any stdout printed before failing.
            details = _combine(stdout, stderr) or "(no output)"
            return f"Error (exit code {proc.returncode}):\n{_keep_end(details)}"

        # DEC-038: stdout plus labeled stderr (e.g. warnings), never "".
        if not stdout and not stderr:
            return "Script ran successfully with no output."
        output = stdout if not stderr else f"{stdout}\n[stderr]\n{stderr}"
        return _keep_start(output)
    except Exception as e:
        return f"Error executing script '{abs_path}': {e}"

"""Sandboxed Python executor for the agents (Lab 1.2, C1.3).

exec_python runs a script in a child process, never with exec() or eval(),
so an infinite loop is killed by the timeout, a crash in the script does not
reach the agent, and the agent always gets a useful string back (DEC-038).
run_python does the work and returns an ExecutionResult, so the Coder can tell
a clean run from a failure without reading the text (DEC-063); exec_python
returns only that text. run_pytest runs a pytest file in the same sandbox
for the QA and returns a PytestResult (DEC-146).

Attributes:
    MAX_OUTPUT_CHARS: Characters of output returned to the agent.
    MAX_TIMEOUT: Hard cap in seconds for any execution (lab limit).
    EXEC_TIMEOUT: Default timeout in seconds, from the EXEC_TIMEOUT
        environment variable (DEC-037, DEC-045).
"""

import os
import signal
import subprocess
import sys
import threading
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Literal, NamedTuple

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

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
    """Builds the script's environment from the allowlist.

    Returns:
        The allowed variables of the agent's environment plus
        PYTHONIOENCODING=utf-8, so no credentials reach the script (DEC-039,
        DEC-043).
    """
    env = {
        name: value
        for name, value in os.environ.items()
        if name in _ENV_ALLOWLIST or name.startswith("LC_")
    }
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _keep_start(text: str) -> str:
    """Truncates a successful output, keeping its beginning (DEC-038).

    Args:
        text: Output to truncate.

    Returns:
        text unchanged if it fits in MAX_OUTPUT_CHARS; otherwise its first
        MAX_OUTPUT_CHARS characters followed by "[output truncated]".
    """
    if len(text) > MAX_OUTPUT_CHARS:
        return text[:MAX_OUTPUT_CHARS] + "\n[output truncated]"
    return text


def _keep_end(text: str) -> str:
    """Truncates an error output, keeping its end (DEC-038).

    The end is where a traceback shows the actual error.

    Args:
        text: Output to truncate.

    Returns:
        text unchanged if it fits in MAX_OUTPUT_CHARS; otherwise
        "[output truncated]" followed by its last MAX_OUTPUT_CHARS characters.
    """
    if len(text) > MAX_OUTPUT_CHARS:
        return "[output truncated]\n" + text[-MAX_OUTPUT_CHARS:]
    return text


def _drain(stream, chunks: list[str]) -> None:
    """Reads a pipe until it closes and stores the text.

    Runs in a thread so a script that prints a lot never blocks on a full pipe
    while exec_python waits for it.

    Args:
        stream: The script's stdout or stderr pipe.
        chunks: List that receives the text read.
    """
    chunks.append(stream.read())


def _kill_group(pid: int) -> None:
    """Kills the script's whole process group (DEC-044).

    Does nothing if no process is left in the group.

    Args:
        pid: Process id of the script, which leads its own group.
    """
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass  # nothing left in the group


def _combine(stdout: str, stderr: str) -> str:
    """Joins stdout and stderr under labels.

    Args:
        stdout: Text the script wrote to stdout.
        stderr: Text the script wrote to stderr.

    Returns:
        A "[stdout]" and a "[stderr]" section for each non-empty stream, or ""
        when both are empty.
    """
    parts = []
    if stdout:
        parts.append(f"[stdout]\n{stdout}")
    if stderr:
        parts.append(f"[stderr]\n{stderr}")
    return "\n".join(parts)


class _SandboxRun(NamedTuple):
    """What one sandboxed process left behind.

    Attributes:
        stdout: Text written to stdout.
        stderr: Text written to stderr.
        returncode: Exit code, or None on timeout.
        timed_out: Whether the timeout killed the process.
        timeout: Timeout applied, in seconds.
    """
    stdout: str
    stderr: str
    returncode: int | None
    timed_out: bool
    timeout: int


def _run_sandboxed(
    command: list[str],
    cwd: str,
    timeout: int | None,
    extra_env: dict[str, str] | None = None,
) -> _SandboxRun:
    """Runs a command in the agents' sandbox and waits for it (DEC-146).

    The process gets stdin closed, an environment without credentials
    (DEC-039, DEC-043) plus ``extra_env``, and its own process group, which
    is killed when the process exits or the timeout expires (DEC-044).

    Args:
        command: Program and arguments.
        cwd: Working directory.
        timeout: Maximum seconds to allow. None uses EXEC_TIMEOUT; values
            above MAX_TIMEOUT are clamped to it (DEC-037).
        extra_env: Variables added to the allowlisted environment.

    Returns:
        The process's output, exit code and whether it timed out.

    Raises:
        OSError: If the process cannot be started.
    """
    # DEC-037: the LLM may ask for another value, never above the cap.
    effective_timeout = min(EXEC_TIMEOUT if timeout is None else timeout, MAX_TIMEOUT)
    proc = subprocess.Popen(
        command,
        cwd=cwd,
        env={**_script_env(), **(extra_env or {})},  # DEC-039, DEC-043
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
    # DEC-044: wait for the process itself, not for its pipes to close,
    # then kill everything it started (also what it left in background).
    try:
        proc.wait(timeout=effective_timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        timed_out = True
    finally:
        _kill_group(proc.pid)
        proc.wait()  # reaps the killed process, so no zombie is left
    for reader in readers:
        reader.join()
    return _SandboxRun(
        stdout="".join(out_chunks),
        stderr="".join(err_chunks),
        returncode=None if timed_out else proc.returncode,
        timed_out=timed_out,
        timeout=effective_timeout,
    )


class ExecutionResult(BaseModel):
    """Structured outcome of one script execution (DEC-063).

    Attributes:
        output: Text for the agent, exactly what exec_python returns.
        exit_code: Exit code of the script, or None when it did not finish
            (timeout) or did not run (missing file, unexpected error).
        timed_out: Whether the script was killed by the timeout.
    """
    model_config = ConfigDict(frozen=True)

    output: str
    exit_code: int | None = None
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        """Returns whether the script ran to the end with exit code 0."""
        return self.exit_code == 0 and not self.timed_out


def exec_python(path: str, timeout: int | None = None) -> str:
    """Runs a Python script in a child process and reports the outcome.

    Wraps run_python and keeps only its text (DEC-063), so the agent and the
    Lab 1.2 contract always get a string.

    Args:
        path: Path to the .py file to execute.
        timeout: Maximum seconds to allow. Defaults to EXEC_TIMEOUT; values
            above MAX_TIMEOUT are clamped to it (DEC-037).

    Returns:
        The output text described in run_python, never empty.
    """
    return run_python(path, timeout).output


def run_python(path: str, timeout: int | None = None) -> ExecutionResult:
    """Runs a Python script in a child process and returns its outcome.

    The script runs with the agent's interpreter, its own directory as working
    directory (DEC-040), stdin closed and an environment without credentials
    (DEC-039, DEC-043). exec_python waits for the script itself; when it exits
    or the timeout expires, its whole process group is killed (DEC-044).
    The process handling is shared with run_pytest (DEC-146).

    Args:
        path: Path to the .py file to execute.
        timeout: Maximum seconds to allow. Defaults to EXEC_TIMEOUT; values
            above MAX_TIMEOUT are clamped to it (DEC-037).

    Returns:
        An ExecutionResult (DEC-063) whose output is a non-empty string for
        the agent (DEC-038):

        - Success: stdout, plus labeled stderr when it is not empty, or a
          message saying the script ran with no output. Long output keeps its
          beginning.
        - Non-zero exit: the exit code, stderr and any stdout printed before
          the failure. Long output keeps its end.
        - Timeout: a message naming the script and saying it was killed, for
          example "Error: script 'loop.py' exceeded timeout of 2s and was
          killed.", followed by any output produced until then.
        - Any other error: a descriptive error string; nothing is raised.

        exit_code is set only when the script finished; timed_out only on
        timeout.
    """
    abs_path = os.path.abspath(path)
    try:
        if not os.path.isfile(abs_path):
            return ExecutionResult(
                output=f"Error: script '{abs_path}' does not exist or is not a file."
            )

        run = _run_sandboxed(
            [sys.executable, abs_path],
            cwd=os.path.dirname(abs_path),  # DEC-040
            timeout=timeout,
        )
        stdout, stderr = run.stdout, run.stderr

        if run.timed_out:
            message = (
                f"Error: script '{os.path.basename(abs_path)}' exceeded timeout "
                f"of {run.timeout}s and was killed."
            )
            partial = _combine(stdout, stderr)
            return ExecutionResult(
                output=f"{message}\n{_keep_end(partial)}" if partial else message,
                timed_out=True,
            )

        if run.returncode != 0:
            # DEC-038: exit code, stderr and any stdout printed before failing.
            details = _combine(stdout, stderr) or "(no output)"
            return ExecutionResult(
                output=f"Error (exit code {run.returncode}):\n{_keep_end(details)}",
                exit_code=run.returncode,
            )

        # DEC-038: stdout plus labeled stderr (e.g. warnings), never "".
        if not stdout and not stderr:
            output = "Script ran successfully with no output."
        else:
            output = stdout if not stderr else f"{stdout}\n[stderr]\n{stderr}"
        return ExecutionResult(output=_keep_start(output), exit_code=0)
    except Exception as e:
        return ExecutionResult(output=f"Error executing script '{abs_path}': {e}")


class TestFailure(BaseModel):
    """One test that failed in a pytest run (DEC-147).

    Attributes:
        name: Name of the test function, e.g. ``test_add``.
        message: pytest's short message, e.g. ``assert -1 == 5``.
        details: The failure's traceback; long text keeps its end.
        timed_out: Whether pytest-timeout stopped the test (DEC-152).
    """
    __test__ = False  # not a test class for pytest

    model_config = ConfigDict(frozen=True)

    name: str
    message: str
    details: str
    timed_out: bool = False


class PytestResult(BaseModel):
    """Outcome of one pytest run (DEC-147, DEC-156).

    Attributes:
        status: ``passed`` (every test passed), ``failed`` (some test
            failed), ``collection_error`` (the tests could not be collected
            or none ran), ``timed_out`` (the whole run was killed) or
            ``error`` (pytest itself failed or its report is unreadable).
        passed: Tests that passed.
        failed: Tests that failed or errored.
        failures: Each failed test, from the JUnit report.
        output: pytest's output; long text keeps its end.
    """
    model_config = ConfigDict(frozen=True)

    status: Literal["passed", "failed", "collection_error", "timed_out", "error"]
    passed: int = 0
    failed: int = 0
    failures: list[TestFailure] = Field(default_factory=list)
    output: str = ""


# DEC-147: pytest's exit codes for interrupted collection, usage error and
# no tests collected.
_COLLECTION_EXIT_CODES = (2, 4, 5)
_TIMEOUT_MESSAGE = "Failed: Timeout"


def _read_junit(path: Path) -> tuple[int, int, list[TestFailure]]:
    """Reads the counts and failures from a pytest JUnit report (DEC-147).

    Args:
        path: The JUnit XML file.

    Returns:
        Tests passed, tests failed (failures plus errors) and one
        TestFailure per failed test.

    Raises:
        OSError: If the file cannot be read.
        ElementTree.ParseError: If the file is not valid XML.
    """
    passed = 0
    failures: list[TestFailure] = []
    for case in ElementTree.parse(path).getroot().iter("testcase"):
        problem = case.find("failure")
        if problem is None:
            problem = case.find("error")
        if problem is None:
            if case.find("skipped") is None:
                passed += 1
            continue
        message = problem.get("message", "")
        failures.append(
            TestFailure(
                name=case.get("name", ""),
                message=message,
                details=_keep_end(problem.text or ""),
                timed_out=message.startswith(_TIMEOUT_MESSAGE),
            )
        )
    return passed, len(failures), failures


def run_pytest(
    test_file: Path, code_dir: Path, test_timeout: int, timeout: int | None = None
) -> PytestResult:
    """Runs one pytest file against the Coder's code, in the sandbox.

    pytest runs with ``code_dir`` as working directory and on
    ``PYTHONPATH``, so the tests import the Coder's modules in place
    (DEC-145), without writing caches or bytecode there. It reads no
    configuration file and loads only the pytest-timeout plugin
    (DEC-155). The JUnit report is written next to the test file.

    Args:
        test_file: The pytest file, in the QA's folder.
        code_dir: The Coder's folder.
        test_timeout: Seconds each test function may run (DEC-152).
        timeout: Seconds the whole run may take. None uses EXEC_TIMEOUT;
            values above MAX_TIMEOUT are clamped to it.

    Returns:
        The run's PytestResult; nothing is raised.
    """
    test_file = Path(test_file).resolve()
    junit = test_file.parent / "junit.xml"
    try:
        junit.unlink(missing_ok=True)  # never read a previous run's report
        run = _run_sandboxed(
            [
                sys.executable, "-m", "pytest", str(test_file),
                # DEC-155: no project config, plugins or parent conftest.py;
                # the per-test timeout covers the test function only.
                "-c", os.devnull, "--rootdir", str(test_file.parent),
                "--confcutdir", str(test_file.parent),
                "-p", "no:cacheprovider", "-p", "pytest_timeout",
                f"--timeout={test_timeout}", "-o", "timeout_func_only=true",
                f"--junitxml={junit}", "-q",
            ],
            cwd=str(code_dir),  # DEC-145
            timeout=timeout,
            extra_env={
                "PYTHONPATH": str(code_dir),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            },
        )
    except OSError as e:
        return PytestResult(status="error", output=f"Error starting pytest: {e}")

    output = _keep_end(_combine(run.stdout, run.stderr))
    if run.timed_out:
        return PytestResult(
            status="timed_out",
            output=f"Error: the test run exceeded timeout of {run.timeout}s "
            f"and was killed.\n{output}",
        )
    if run.returncode in _COLLECTION_EXIT_CODES:
        return PytestResult(status="collection_error", output=output)
    if run.returncode not in (0, 1):
        return PytestResult(status="error", output=output)
    try:
        passed, failed, failures = _read_junit(junit)
    except (OSError, ElementTree.ParseError) as e:
        return PytestResult(status="error", output=f"Unreadable JUnit report: {e}\n{output}")
    status = "passed" if run.returncode == 0 else "failed"
    return PytestResult(
        status=status, passed=passed, failed=failed, failures=failures, output=output
    )

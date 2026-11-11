"""Request fixture of the graded API demo: GET /health and POST /echo (C2.5).

The generated API is checked twice: in-process with Flask's test client,
and as a real server started with ``python <file>`` (DEC-112). Both send the
same three requests: ``GET /health`` → 200 ``{"status": "ok"}``; ``POST
/echo`` with a JSON body → 200 and the same body; ``POST /echo`` with a
body that is not JSON → 400.

Typical usage example:

    api_file = workspace / find_api(state.code)
    assert check_in_process(api_file).returncode == 0
    check_real_server(api_file)
"""

import json
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ECHO_BODY = {"a": 1, "b": [2, 3]}
SERVER_START_SECONDS = 15

# Runs in a subprocess: imports the file without running its __main__ block.
_IN_PROCESS_CHECK = """
import importlib.util, sys
from pathlib import Path
from flask import Flask

path = Path(sys.argv[1])
sys.path.insert(0, str(path.parent))
spec = importlib.util.spec_from_file_location(path.stem, path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
apps = [value for value in vars(module).values() if isinstance(value, Flask)]
assert len(apps) == 1, f"expected one Flask app, found {apps}"
client = apps[0].test_client()
health = client.get("/health")
assert health.status_code == 200 and health.get_json() == {"status": "ok"}, health.data
echo = client.post("/echo", json=%(body)r)
assert echo.status_code == 200 and echo.get_json() == %(body)r, echo.data
bad = client.post("/echo", data="not json", content_type="application/json")
assert bad.status_code == 400, (bad.status_code, bad.data)
print("FIXTURE OK")
""" % {"body": ECHO_BODY}

_CREATES_APP = re.compile(r"\bFlask\(")
_URL_PATTERN = re.compile(r"Running on (http://[\w.\-]+:\d+)")


def find_api(code: dict[str, str]) -> str:
    """Returns the only file of the accumulated code that creates the Flask app.

    Check scripts mention the routes too (DEC-112), so the API file is the
    one that both creates a ``Flask(...)`` object and names both routes.

    Args:
        code: The run's accumulated code, path to content.

    Returns:
        The path, relative to the workspace, of the API file.

    Raises:
        AssertionError: If no file or more than one file qualifies.
    """
    files = [
        path
        for path, content in code.items()
        if _CREATES_APP.search(content) and "/health" in content and "/echo" in content
    ]
    assert len(files) == 1, f"expected one API file, found {files} in {list(code)}"
    return files[0]


def check_in_process(api_file: Path) -> subprocess.CompletedProcess:
    """Returns the result of the three requests sent through Flask's test client.

    Args:
        api_file: Absolute path of the generated API.

    Returns:
        The finished subprocess; return code 0 and ``FIXTURE OK`` in its
        output when every request passed.
    """
    return subprocess.run(
        [sys.executable, "-c", _IN_PROCESS_CHECK, str(api_file)],
        cwd=api_file.parent,
        capture_output=True,
        text=True,
        timeout=10,
    )


def _wait_for_url(process: subprocess.Popen) -> str:
    """Returns the URL the server prints when it starts listening.

    Args:
        process: The server process, with stdout and stderr merged.

    Returns:
        The base URL, e.g. ``http://127.0.0.1:5000``.

    Raises:
        AssertionError: If the server exits or prints no URL in time.
    """
    lines: queue.Queue[str] = queue.Queue()

    def read() -> None:
        """Copies the server's output lines to the queue until it closes."""
        for line in process.stdout:
            lines.put(line)

    threading.Thread(target=read, daemon=True).start()
    seen = []
    deadline = time.monotonic() + SERVER_START_SECONDS
    while time.monotonic() < deadline:
        try:
            line = lines.get(timeout=0.5)
        except queue.Empty:
            assert process.poll() is None, f"server exited: {''.join(seen)}"
            continue
        seen.append(line)
        match = _URL_PATTERN.search(line)
        if match:
            return match.group(1)
    raise AssertionError(f"no 'Running on' URL within {SERVER_START_SECONDS}s: {''.join(seen)}")


def _request(url: str, data: bytes | None = None) -> tuple[int, bytes]:
    """Returns the status code and body of one HTTP request.

    Args:
        url: Full URL of the request.
        data: JSON-typed body for a POST; None sends a GET.

    Returns:
        The status code (also for 4xx and 5xx answers) and the body.
    """
    headers = {"Content-Type": "application/json"} if data is not None else {}
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def check_real_server(api_file: Path) -> None:
    """Starts the API with ``python <file>`` and sends the three requests over HTTP.

    The server runs in its own process group, which is killed at the end,
    so a reloader child (``debug=True``) does not outlive the check.

    Args:
        api_file: Absolute path of the generated API.

    Raises:
        AssertionError: If the server does not start or a request fails.
    """
    process = subprocess.Popen(
        [sys.executable, str(api_file)],
        cwd=api_file.parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
        start_new_session=True,
    )
    try:
        url = _wait_for_url(process)
        status, body = _request(f"{url}/health")
        assert status == 200 and json.loads(body) == {"status": "ok"}, (status, body)
        status, body = _request(f"{url}/echo", json.dumps(ECHO_BODY).encode())
        assert status == 200 and json.loads(body) == ECHO_BODY, (status, body)
        status, body = _request(f"{url}/echo", b"not json")
        assert status == 400, (status, body)
    finally:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:  # the server already exited
            pass
        process.wait(timeout=5)

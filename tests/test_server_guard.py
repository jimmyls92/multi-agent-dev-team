"""Tests of the server guard of ``exec_python`` (spec `lab_2_3_pipeline`, AC-2.3-17).

A file that starts a web server is never run (DEC-116); every other file
runs as before. Each file writes a marker when it runs, so the tests see
whether it ran.
"""

import pytest

import tools.handlers
from tools import dispatch_tool

MARKER = 'open("ran.txt", "w").write("ran")\n'

FLASK_SERVER = MARKER + '''from flask import Flask
app = Flask(__name__)

@app.get("/health")
def health():
    return {"status": "ok"}

if __name__ == "__main__":
    app.run(debug=True)
'''

UVICORN_SERVER = MARKER + '''import uvicorn
from fastapi import FastAPI
api = FastAPI()

if __name__ == "__main__":
    uvicorn.run(api, port=8000)
'''

STDLIB_SERVER = MARKER + '''from http.server import HTTPServer, BaseHTTPRequestHandler
HTTPServer(("127.0.0.1", 8000), BaseHTTPRequestHandler).serve_forever()
'''

CHECK_SCRIPT = MARKER + '''import subprocess, sys
from flask import Flask
from app import app
client = app.test_client()
subprocess.run([sys.executable, "-c", "print(1)"], check=True)
print("checked", client.get("/health").status_code)
'''


@pytest.fixture
def workspace():
    """Returns the test's workspace, created, with a small Flask app in ``app.py``.

    Returns:
        The workspace directory.
    """
    root = tools.handlers.WORKSPACE_DIR
    root.mkdir(parents=True, exist_ok=True)
    (root / "app.py").write_text(FLASK_SERVER.replace(MARKER, ""), encoding="utf-8")
    return root


@pytest.mark.parametrize("content", [FLASK_SERVER, UVICORN_SERVER, STDLIB_SERVER])
def test_ac_2_3_17_server_file_not_run(workspace, content):
    (workspace / "server.py").write_text(content, encoding="utf-8")

    outcome = dispatch_tool("exec_python", {"path": "server.py"})

    assert outcome.execution is None
    assert outcome.observation.startswith("Error:")
    assert "check script" in outcome.observation
    assert not (workspace / "ran.txt").exists()


def test_ac_2_3_17_check_script_runs(workspace):
    (workspace / "check_app.py").write_text(CHECK_SCRIPT, encoding="utf-8")

    outcome = dispatch_tool("exec_python", {"path": "check_app.py"})

    assert outcome.execution is not None
    assert "checked 200" in outcome.observation
    assert (workspace / "ran.txt").exists()

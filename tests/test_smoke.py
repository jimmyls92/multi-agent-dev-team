"""Smoke test of the Coder Agent with the real LLM (C1.6, DEC-054, DEC-066).

Gives the Coder a short coding task, checks the structured output (C1.5) and
runs the generated code in a subprocess to check its behavior.

Run with:
    pytest tests/test_smoke.py --run-llm
"""

import subprocess
import sys
from pathlib import Path

import chromadb
import pytest

import memory
import tools.handlers
from agents.coder_agent import MAX_ITERATIONS, CoderResult, run_agent
from memory import SlidingWindowBuffer

TASK = (
    "Write a function word_frequency(text) in word_frequency.py that returns a "
    "dict mapping each lowercase word to its count, ignoring punctuation. Add a "
    "__main__ block with a few asserts that prints OK when they pass."
)

# Runs inside a subprocess with the workspace as working directory.
BEHAVIOR_CHECK = """
from word_frequency import word_frequency
assert word_frequency("Hello, hello world!") == {"hello": 2, "world": 1}, word_frequency("Hello, hello world!")
assert word_frequency("") == {}, word_frequency("")
print("BEHAVIOR OK")
"""


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Points the agent at a temporary workspace and Chroma collection.

    The real .chroma store is not touched and old memories cannot influence
    the run.

    Args:
        tmp_path: Pytest's per-test temporary directory.
        monkeypatch: Pytest's monkeypatch fixture.

    Returns:
        The temporary workspace directory.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(tools.handlers, "WORKSPACE_DIR", workspace.resolve())
    client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
    monkeypatch.setattr(memory, "_collection", client.get_or_create_collection("smoke_test"))
    return workspace.resolve()


@pytest.mark.llm
def test_coder_writes_and_runs_working_code(isolated):
    result = run_agent(TASK, SlidingWindowBuffer())

    # C1.5: the output goes through the Pydantic model.
    result = CoderResult.model_validate(result.model_dump())
    assert result.status == "success", result.model_dump_json(indent=2)

    # C1.6: the required structured-output fields are filled.
    assert result.plan.strip()
    assert result.code.strip()
    assert result.explanation.strip()
    assert result.result.strip()

    # C1.5: code is the artifact written by the tools.
    assert Path(result.main_file).name == "word_frequency.py"
    written = isolated / "word_frequency.py"
    assert written.read_text(encoding="utf-8") == result.code

    # C1.4/C1.5: the code was actually run, within the iteration limit.
    assert any(step.action == "exec_python" for step in result.steps)
    assert result.iterations <= MAX_ITERATIONS

    # The generated code behaves as the task asked (subprocess, never exec).
    check = subprocess.run(
        [sys.executable, "-c", BEHAVIOR_CHECK],
        cwd=isolated,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert check.returncode == 0, check.stderr
    assert "BEHAVIOR OK" in check.stdout

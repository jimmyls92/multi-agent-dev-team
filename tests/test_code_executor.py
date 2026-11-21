"""Tests for tools/code_executor.py (Lab 1.2).

These tests come from the lab and define the contract of exec_python. The
run_pytest tests cover spec `lab_3_2_qa_agent` AC-3.2-7 to AC-3.2-11.

Run with:
    pytest tests/test_code_executor.py -v

The timeout test needs a few seconds to verify the kill signal. Run with
--timeout=60 in slow environments if needed.
"""

import os
import time
from pathlib import Path

import pytest
from tools.file_io import write_file
from tools.code_executor import exec_python, run_pytest


@pytest.fixture
def py_file(tmp_path):
    """Provides a helper that writes a .py file into tmp_path.

    Args:
        tmp_path: Pytest's per-test temporary directory.

    Returns:
        A function that takes the script content and an optional file name and
        returns the absolute path of the written file.
    """
    def _write(content: str, name: str = "script.py") -> str:
        """Writes a script into tmp_path.

        Args:
            content: Python source to write.
            name: File name of the script.

        Returns:
            Absolute path of the written file.
        """
        path = str(tmp_path / name)
        write_file(path, content)
        return path
    return _write


# ── happy path ────────────────────────────────────────────────────────────────

class TestExecPythonSuccess:
    """Tests for successful runs: stdout capture and the return type."""

    def test_captures_stdout(self, py_file):
        path = py_file("print('hello from subprocess')\n")
        result = exec_python(path)
        assert "hello from subprocess" in result

    def test_captures_multiline_output(self, py_file):
        path = py_file("for i in range(5):\n    print(i)\n")
        result = exec_python(path)
        for i in range(5):
            assert str(i) in result

    def test_always_returns_string(self, py_file):
        path = py_file("x = 1 + 1\n")
        result = exec_python(path)
        assert isinstance(result, str)


# ── error handling ────────────────────────────────────────────────────────────

class TestExecPythonErrors:
    """Tests for failing scripts and invalid paths: errors come as strings."""

    def test_captures_stderr_on_exception(self, py_file):
        path = py_file("raise ValueError('intentional crash')\n")
        result = exec_python(path)
        assert isinstance(result, str), "Must return a string, not raise"
        assert "ValueError" in result or "error" in result.lower()

    def test_includes_return_code_on_nonzero_exit(self, py_file):
        path = py_file("import sys\nsys.exit(42)\n")
        result = exec_python(path)
        assert "42" in result

    def test_missing_file_returns_error_string(self):
        result = exec_python("/nonexistent/path/missing.py")
        assert isinstance(result, str)
        assert "error" in result.lower()

    def test_does_not_raise_on_empty_path(self):
        try:
            result = exec_python("")
            assert isinstance(result, str)
        except Exception as e:
            pytest.fail(f"exec_python raised instead of returning an error string: {e}")

    def test_does_not_raise_on_any_failure(self):
        try:
            result = exec_python("/dev/null")
            assert isinstance(result, str)
        except Exception as e:
            pytest.fail(f"exec_python raised instead of returning an error string: {e}")


# ── timeout and sandboxing ────────────────────────────────────────────────────

class TestExecPythonTimeout:
    """Tests for the timeout, its cap and output truncation."""

    @pytest.mark.timeout(15)
    def test_kills_infinite_loop(self, py_file):
        path = py_file("while True:\n    pass\n")
        result = exec_python(path, timeout=2)
        assert isinstance(result, str)
        lower = result.lower()
        assert "timeout" in lower or "killed" in lower or "timed out" in lower, (
            f"Expected a timeout message, got: {result!r}"
        )

    def test_timeout_clamped_to_max(self, py_file):
        # Passing 999 must not actually wait 999 seconds.
        # Verify it accepts the value and runs fast script normally.
        path = py_file("print('fast')\n")
        result = exec_python(path, timeout=999)
        assert "fast" in result

    def test_truncates_long_output(self, py_file):
        path = py_file("print('x' * 3000)\n")
        result = exec_python(path)
        # Allow a small buffer for the truncation message itself.
        assert len(result) <= 2100, (
            f"Output should be truncated to ~2000 chars, got {len(result)}"
        )
        assert "truncated" in result.lower() or len(result) <= 2000


# ── integration: write → exec → read ─────────────────────────────────────────

class TestWriteExecReadRoundtrip:
    """Tests the lab's success criterion end to end, without the LLM.

    Writes a script, executes it and checks the side-effect file it produced.
    """

    def test_full_roundtrip(self, tmp_path):
        from tools.file_io import read_file

        script_path = str(tmp_path / "word_count.py")
        output_path = str(tmp_path / "result.txt")

        script = (
            "from collections import Counter\n"
            "words = 'the quick brown fox jumps over the lazy dog'.split()\n"
            "counts = Counter(words)\n"
            f"with open('{output_path}', 'w') as f:\n"
            "    for word, count in sorted(counts.items()):\n"
            "        f.write(f'{word}: {count}\\n')\n"
            "print('Word count written.')\n"
        )

        write_file(script_path, script)
        exec_result = exec_python(script_path)
        assert "written" in exec_result.lower(), (
            f"Expected success message from script, got: {exec_result!r}"
        )

        file_result = read_file(output_path)
        assert "fox: 1" in file_result
        assert "the: 2" in file_result

# ── run_pytest (Lab 3.2) ──────────────────────────────────────────────────────

@pytest.fixture
def folders(tmp_path):
    """Creates a Coder folder and a QA task folder, with a writer for each.

    Args:
        tmp_path: Pytest's per-test temporary directory.

    Returns:
        A namespace-like dict with ``coder`` and ``qa`` (the folders) and
        ``write``, a function taking a folder, a file name and its content.
    """
    coder = tmp_path / "coder"
    qa = tmp_path / "qa" / "task_1"
    coder.mkdir()
    qa.mkdir(parents=True)

    def write(folder: Path, name: str, content: str) -> Path:
        """Writes a file into a folder.

        Args:
            folder: Where to write.
            name: File name.
            content: Text to write.

        Returns:
            The file's path.
        """
        path = folder / name
        path.write_text(content)
        return path

    return {"coder": coder, "qa": qa, "write": write}


def _run(folders, test_code: str, test_timeout: int = 2, timeout: int | None = None):
    """Writes ``test_task_1.py`` in the QA folder and runs it.

    Args:
        folders: The ``folders`` fixture.
        test_code: Content of the test file.
        test_timeout: Seconds each test may run.
        timeout: Seconds the whole run may take; None uses EXEC_TIMEOUT.

    Returns:
        The PytestResult of the run.
    """
    test_file = folders["write"](folders["qa"], "test_task_1.py", test_code)
    return run_pytest(test_file, folders["coder"], test_timeout, timeout)


def test_parent_conftest_is_not_loaded(folders):
    folders["write"](folders["qa"].parent, "conftest.py", "raise RuntimeError('parent conftest')\n")
    folders["write"](folders["coder"], "calc.py", "def add(a, b):\n    return a + b\n")

    result = _run(folders, "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n")

    assert (result.status, result.passed) == ("passed", 1), result.output


def test_ac_3_2_7_pytest_passes(folders):
    folders["write"](folders["coder"], "calc.py", "def add(a, b):\n    return a + b\n")
    result = _run(
        folders,
        "from calc import add\n\n"
        "def test_small():\n    assert add(2, 3) == 5\n\n"
        "def test_negative():\n    assert add(-1, 1) == 0\n",
    )
    assert (result.status, result.passed, result.failed, result.failures) == ("passed", 2, 0, [])


def test_ac_3_2_8_pytest_failure(folders):
    folders["write"](folders["coder"], "calc.py", "def add(a, b):\n    return a - b\n")
    result = _run(folders, "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n")
    assert result.status == "failed"
    assert [failure.name for failure in result.failures] == ["test_add"]
    assert "assert" in result.failures[0].message
    assert "-1" in result.failures[0].message
    assert not result.failures[0].timed_out


@pytest.mark.parametrize(
    ("test_code", "error_text"),
    [
        ("undefined_name\n\ndef test_x():\n    assert True\n", "NameError"),
        ("x = 1\n", "no tests ran"),
    ],
    ids=["name-error", "no-tests"],
)
def test_ac_3_2_9_pytest_collection_error(folders, test_code, error_text):
    result = _run(folders, test_code)
    assert result.status == "collection_error"
    assert error_text in result.output


def test_ac_3_2_10_pytest_timeout_one_test(folders):
    folders["write"](
        folders["coder"], "slow.py",
        "def spin():\n    while True:\n        pass\n\ndef one():\n    return 1\n",
    )
    result = _run(
        folders,
        "from slow import one, spin\n\n"
        "def test_spin():\n    spin()\n\n"
        "def test_one():\n    assert one() == 1\n",
        test_timeout=1,
        timeout=15,
    )
    assert (result.status, result.passed, result.failed) == ("failed", 1, 1)
    [failure] = result.failures
    assert failure.name == "test_spin"
    assert failure.timed_out
    assert "slow.py" in failure.details


def test_ac_3_2_10_pytest_timeout_whole_run(folders, tmp_path):
    pid_file = tmp_path / "pid.txt"
    folders["write"](
        folders["coder"], "hang.py",
        f"import os\nopen({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
        "while True:\n    pass\n",
    )
    start = time.monotonic()
    result = _run(folders, "import hang\n\ndef test_x():\n    assert True\n", timeout=2)
    assert time.monotonic() - start < 5
    assert result.status == "timed_out"
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)


def test_ac_3_2_11_pytest_sandbox(folders, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "secret")
    folders["write"](folders["coder"], "data.txt", "hello")
    folders["write"](
        folders["coder"], "reader.py",
        "def read():\n    with open('data.txt') as f:\n        return f.read()\n",
    )
    result = _run(
        folders,
        "import os\n\nfrom reader import read\n\n"
        "def test_no_key():\n    assert 'OPENROUTER_API_KEY' not in os.environ\n\n"
        "def test_read():\n    assert read() == 'hello'\n",
    )
    assert (result.status, result.passed) == ("passed", 2)
    assert sorted(os.listdir(folders["coder"])) == ["data.txt", "reader.py"]
    assert (folders["qa"] / "junit.xml").is_file()

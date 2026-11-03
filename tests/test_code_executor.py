"""
Tests for tools/code_executor.py

Run with:
    pytest tests/test_code_executor.py -v

The timeout test needs a few seconds to verify the kill signal.
Run with --timeout=60 in slow Codespaces environments if needed.
"""

import pytest
from tools.file_io import write_file
from tools.code_executor import exec_python


@pytest.fixture
def py_file(tmp_path):
    """Write a .py file into tmp_path and return its absolute path."""
    def _write(content: str, name: str = "script.py") -> str:
        path = str(tmp_path / name)
        write_file(path, content)
        return path
    return _write


# ── happy path ────────────────────────────────────────────────────────────────

class TestExecPythonSuccess:

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
    """
    Mirrors the lab success criterion end-to-end without the LLM:
    write a script, execute it, verify a side-effect file was produced.
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
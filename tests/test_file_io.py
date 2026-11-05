"""Tests for tools/file_io.py (Lab 1.2).

These tests come from the lab and define the contract of read_file and
write_file.

Run with:
    pytest tests/test_file_io.py -v
"""

import os
import pytest
from tools.file_io import read_file, write_file


# ── write_file ────────────────────────────────────────────────────────────────

class TestWriteFile:
    """Tests for write_file: file creation, return message and failures."""

    def test_creates_file(self, tmp_path):
        path = str(tmp_path / "hello.py")
        result = write_file(path, "print('hello')\n")
        assert os.path.exists(path)

    def test_returns_success_string(self, tmp_path):
        path = str(tmp_path / "hello.py")
        result = write_file(path, "print('hello')\n")
        assert isinstance(result, str)
        assert "written successfully" in result.lower()

    def test_reports_line_count(self, tmp_path):
        path = str(tmp_path / "multi.py")
        content = "a = 1\nb = 2\nc = 3\n"
        result = write_file(path, content)
        assert "3" in result

    def test_creates_nested_parent_directories(self, tmp_path):
        path = str(tmp_path / "src" / "utils" / "helpers.py")
        result = write_file(path, "x = 42\n")
        assert os.path.exists(path), (
            "write_file must create missing parent directories automatically"
        )

    def test_overwrites_existing_file(self, tmp_path):
        path = str(tmp_path / "overwrite.py")
        write_file(path, "old content\n")
        write_file(path, "new content\n")
        assert open(path).read() == "new content\n"

    def test_returns_error_string_on_invalid_path(self):
        # Writing to a path under /dev/null is impossible on all platforms.
        result = write_file("/dev/null/impossible/path/file.py", "x = 1")
        assert isinstance(result, str), "Must return a string, not raise"
        assert "error" in result.lower()

    def test_does_not_raise_on_any_failure(self):
        # This must not propagate any exception.
        try:
            result = write_file("/dev/null/impossible/path/file.py", "x = 1")
            assert isinstance(result, str)
        except Exception as e:
            pytest.fail(f"write_file raised an exception instead of returning an error string: {e}")


# ── read_file ─────────────────────────────────────────────────────────────────

class TestReadFile:
    """Tests for read_file: contents, missing files and the roundtrip."""

    def test_returns_file_contents(self, tmp_path):
        path = str(tmp_path / "sample.py")
        open(path, "w").write("x = 1\ny = 2\n")
        result = read_file(path)
        assert "x = 1" in result
        assert "y = 2" in result

    def test_missing_file_returns_error_string(self):
        result = read_file("/nonexistent/path/file.py")
        assert isinstance(result, str), "Must return a string, not raise"
        assert "error" in result.lower() or "not found" in result.lower()

    def test_error_message_includes_path(self):
        target = "/nonexistent/path/file.py"
        result = read_file(target)
        # The agent uses the path in the error to diagnose and self-correct.
        assert "nonexistent" in result or target in result

    def test_does_not_raise_on_missing_file(self):
        try:
            result = read_file("/nonexistent/path/file.py")
            assert isinstance(result, str)
        except Exception as e:
            pytest.fail(f"read_file raised an exception instead of returning an error string: {e}")

    def test_roundtrip_with_write_file(self, tmp_path):
        path = str(tmp_path / "roundtrip.txt")
        original = "line one\nline two\nline three\n"
        write_file(path, original)
        result = read_file(path)
        assert result == original
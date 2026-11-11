"""Tests of the workspace archive (spec `lab_2_3_pipeline`, AC-2.3-1..AC-2.3-4).

Every test works in ``tmp_path``: the real workspace and repo are never
touched.
"""

from pathlib import Path

import pytest

from orchestration.workspace import archive_workspace


def _write(path: Path, content: str) -> None:
    """Writes a text file, creating its parent folders.

    Args:
        path: File to write.
        content: Text content.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture
def protected(tmp_path) -> Path:
    """Returns a protected folder next to the workspaces of the test.

    Args:
        tmp_path: Pytest's per-test temporary directory.

    Returns:
        ``tmp_path / "repo"``, created.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    return repo


def test_ac_2_3_1_archives_previous_files(tmp_path, protected):
    workspace = tmp_path / "workspace"
    _write(workspace / "app.py", "print('old app')\n")
    _write(workspace / "lib" / "util.py", "X = 1\n")

    archive = archive_workspace(workspace, protected)

    assert workspace.is_dir()
    assert list(workspace.iterdir()) == []
    assert archive.parent == tmp_path / "workspace_history"
    assert (archive / "app.py").read_text(encoding="utf-8") == "print('old app')\n"
    assert (archive / "lib" / "util.py").read_text(encoding="utf-8") == "X = 1\n"


@pytest.mark.parametrize("exists", [True, False])
def test_ac_2_3_2_empty_workspace(tmp_path, protected, exists):
    workspace = tmp_path / "workspace"
    if exists:
        workspace.mkdir()

    archive = archive_workspace(workspace, protected)

    assert archive is None
    assert workspace.is_dir()
    assert not (tmp_path / "workspace_history").exists()


def test_ac_2_3_3_archives_do_not_collide(tmp_path, protected):
    workspace = tmp_path / "workspace"
    _write(workspace / "first.py", "1\n")
    first = archive_workspace(workspace, protected)
    _write(workspace / "second.py", "2\n")

    second = archive_workspace(workspace, protected)

    assert first != second
    assert [p.name for p in first.iterdir()] == ["first.py"]
    assert [p.name for p in second.iterdir()] == ["second.py"]


def test_ac_2_3_4_refuses_protected_root(tmp_path, protected):
    _write(protected / "keep.py", "keep\n")

    for workspace in (protected, tmp_path):
        with pytest.raises(ValueError):
            archive_workspace(workspace, protected)

    assert (protected / "keep.py").read_text(encoding="utf-8") == "keep\n"
    assert not (tmp_path / "repo_history").exists()
    assert not (tmp_path.parent / f"{tmp_path.name}_history").exists()

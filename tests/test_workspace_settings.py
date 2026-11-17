"""Tests of the Coder's workspace setting (Lab 3.2, DEC-140, DEC-151).

The rule that turns the environment into the Coder's folder is a pure
function, so each case passes its own variables instead of reloading
``tools.handlers`` or depending on the local ``.env``.
"""

from pathlib import Path

import pytest

import tools.handlers
from tools.handlers import _coder_workspace_dir, resolve_in_workspace
from tools.mcp_client import _server_parameters

_REPO_ROOT = Path(tools.handlers.__file__).resolve().parent.parent


def test_ac_3_2_1_coder_workspace_dir(tmp_path, monkeypatch):
    assert _coder_workspace_dir({}) == _REPO_ROOT / "workspace_coder"
    assert _coder_workspace_dir({"CODER_WORKSPACE_DIR": "other"}) == _REPO_ROOT / "other"

    coder_dir = (tmp_path / "coder").resolve()
    monkeypatch.setattr(tools.handlers, "CODER_WORKSPACE_DIR", coder_dir)
    assert Path(resolve_in_workspace("a.py")) == coder_dir / "a.py"
    with pytest.raises(ValueError, match="outside the workspace"):
        resolve_in_workspace(str(tmp_path / "a.py"))
    assert _server_parameters(coder_dir).env == {"CODER_WORKSPACE_DIR": str(coder_dir)}


def test_ac_3_2_2_old_variable_rejected():
    with pytest.raises(ValueError, match="CODER_WORKSPACE_DIR"):
        _coder_workspace_dir({"WORKSPACE_DIR": "workspace"})


def test_empty_coder_workspace_dir_rejected():
    with pytest.raises(ValueError, match="CODER_WORKSPACE_DIR"):
        _coder_workspace_dir({"CODER_WORKSPACE_DIR": "  "})

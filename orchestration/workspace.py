"""Archive of the agent's workspace before each run (DEC-114).

Each run starts with an empty workspace: whatever an earlier run left there
is moved, never deleted, to ``<workspace>_history/<timestamp>/`` next to
the workspace, outside the tools' boundary (DEC-036).

Typical usage example:

    archive = archive_workspace(tools.handlers.WORKSPACE_DIR, REPO_ROOT)
    if archive is not None:
        print(f"Previous files moved to {archive}")

Attributes:
    REPO_ROOT: Root of the repository; a workspace that is or contains it
        is never archived.
    HISTORY_SUFFIX: Suffix of the history folder's name.
"""

import shutil
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HISTORY_SUFFIX = "_history"


def _free_folder(parent: Path, name: str) -> Path:
    """Returns a folder path under parent that does not exist yet.

    Args:
        parent: Folder that will hold the new folder.
        name: Preferred name; ``-2``, ``-3``... is appended when taken.

    Returns:
        ``parent / name``, or the first free ``parent / f"{name}-<n>"``.
    """
    candidate = parent / name
    suffix = 2
    while candidate.exists():
        candidate = parent / f"{name}-{suffix}"
        suffix += 1
    return candidate


def archive_workspace(workspace: Path, protected: Path) -> Path | None:
    """Moves everything in the workspace to a new history folder.

    Items are moved one by one, so a failure leaves the items not yet moved
    where they were: nothing is ever lost.

    Args:
        workspace: The agent's working directory; created if missing.
        protected: Folder that must never be moved, e.g. the repo root.

    Returns:
        The folder that now holds the earlier files, or None when the
        workspace was empty.

    Raises:
        ValueError: If the workspace is the protected folder or contains it.
        OSError: If an item cannot be moved.
    """
    workspace = workspace.resolve()
    protected = protected.resolve()
    # DEC-114: a misconfigured WORKSPACE_DIR (e.g. ".") must never move the repo.
    if protected.is_relative_to(workspace):
        raise ValueError(
            f"workspace {workspace} is or contains {protected}; set WORKSPACE_DIR "
            "to a dedicated folder"
        )
    workspace.mkdir(parents=True, exist_ok=True)
    items = sorted(workspace.iterdir())
    if not items:
        return None
    history = workspace.parent / f"{workspace.name}{HISTORY_SUFFIX}"
    archive = _free_folder(history, datetime.now().strftime("%Y%m%d-%H%M%S"))
    archive.mkdir(parents=True)
    for item in items:
        shutil.move(str(item), str(archive / item.name))
    return archive

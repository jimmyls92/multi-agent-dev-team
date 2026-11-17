"""QA & Debugger agent (Lab 3.2).

Reviews one task of the PM's handoff: it reads the Coder's files through the
MCP server, writes pytest tests for the task's acceptance criteria and
returns a ``QAReport`` (``orchestration.state``) whose verdict comes from
the executed tests (DEC-137, DEC-139).

Its settings come from environment variables and are checked when the
module is imported, so a wrong value stops the program at startup
(DEC-151).

Attributes:
    DEFAULT_QA_MODEL: Small, fast model used when ``QA_MODEL`` is unset
        (C4.5, DEC-150).
    QA_SETTINGS: Settings read at import time from the environment.

Typical usage example:

    settings = load_qa_settings(os.environ, EXEC_TIMEOUT, CODER_WORKSPACE_DIR)
    print(settings.workspace_dir)
"""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import get_args

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict

from orchestration.state import Severity
from tools import handlers
from tools.code_executor import EXEC_TIMEOUT

load_dotenv()

DEFAULT_QA_MODEL = "openai/gpt-4.1-mini"  # DEC-150

_REPO_ROOT = Path(__file__).resolve().parent.parent


class QASettings(BaseModel):
    """The QA's validated settings (DEC-151).

    Attributes:
        workspace_dir: Absolute path of the QA's folder for its tests
            (DEC-140).
        model: Model the QA calls (DEC-150).
        max_attempts: Attempts the QA has to produce runnable tests
            (DEC-141).
        blocking_severity: Lowest severity that blocks approval (DEC-139).
        test_timeout: Seconds each test may run (DEC-152).
    """
    model_config = ConfigDict(frozen=True)

    workspace_dir: Path
    model: str
    max_attempts: int
    blocking_severity: Severity
    test_timeout: int


def _int_setting(env: Mapping[str, str], name: str, default: int, minimum: int) -> int:
    """Returns an integer setting, checked against its minimum.

    Args:
        env: Environment variables.
        name: Variable to read.
        default: Value when the variable is unset.
        minimum: Lowest value allowed.

    Returns:
        The variable's value as an integer, or ``default``.

    Raises:
        ValueError: If the value is not an integer or is below ``minimum``;
            the message names the variable.
    """
    raw = env.get(name, str(default))
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from None
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}, got {value}")
    return value


def load_qa_settings(
    env: Mapping[str, str], exec_timeout: int, coder_dir: Path
) -> QASettings:
    """Returns the QA's settings from the environment, with defaults.

    Args:
        env: Environment variables, usually ``os.environ``.
        exec_timeout: The whole run's timeout (``EXEC_TIMEOUT``); each test's
            timeout must be lower.
        coder_dir: The Coder's folder, which the QA's folder must not
            overlap.

    Returns:
        The validated settings.

    Raises:
        ValueError: If any value is invalid; the message names its variable.
    """
    folder = env.get("QA_WORKSPACE_DIR", "workspace_qa")
    if not folder.strip():
        raise ValueError("QA_WORKSPACE_DIR must not be empty")
    workspace_dir = (_REPO_ROOT / folder).resolve()
    # DEC-154: the Coder's tools must never reach the QA's tests (DEC-140).
    if workspace_dir.is_relative_to(coder_dir) or coder_dir.is_relative_to(workspace_dir):
        raise ValueError(
            f"QA_WORKSPACE_DIR {workspace_dir} must not overlap the Coder's "
            f"folder {coder_dir}"
        )

    model = env.get("QA_MODEL", DEFAULT_QA_MODEL)
    if not model.strip():
        raise ValueError("QA_MODEL must not be empty")

    severity = env.get("QA_BLOCKING_SEVERITY", "High")
    if severity not in get_args(Severity):
        raise ValueError(
            f"QA_BLOCKING_SEVERITY must be one of {', '.join(get_args(Severity))}, "
            f"got {severity!r}"
        )

    test_timeout = _int_setting(env, "QA_TEST_TIMEOUT", default=2, minimum=1)
    # DEC-152: a single test must time out before the whole run does.
    if test_timeout >= exec_timeout:
        raise ValueError(
            f"QA_TEST_TIMEOUT must be lower than EXEC_TIMEOUT ({exec_timeout}), "
            f"got {test_timeout}"
        )

    return QASettings(
        workspace_dir=workspace_dir,
        model=model,
        max_attempts=_int_setting(env, "QA_MAX_ATTEMPTS", default=2, minimum=1),
        blocking_severity=severity,
        test_timeout=test_timeout,
    )


QA_SETTINGS = load_qa_settings(os.environ, EXEC_TIMEOUT, handlers.CODER_WORKSPACE_DIR)

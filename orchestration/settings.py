"""Settings of the Coder-QA loop, read from the environment when a run starts (DEC-180).

Every value is an integer with a minimum of 1; timeouts are in seconds
(DEC-190). ``int_setting`` is the shared reader, also used by the QA.

Typical usage example:

    settings = load_loop_settings(os.environ)
    limit = settings.qa_max_iterations
"""

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict


class LoopSettings(BaseModel):
    """The validated settings of the Coder-QA loop.

    Attributes:
        qa_max_iterations: QA reviews allowed per task (C3.3, DEC-163).
        run_timeout: Seconds a whole run may take, checked between steps
            (DEC-168).
        llm_timeout: Seconds each LLM request may take (DEC-166).
        reflection_max_rounds: Improvement passes per submission to the QA
            (DEC-172).
    """
    model_config = ConfigDict(frozen=True)

    qa_max_iterations: int
    run_timeout: int
    llm_timeout: int
    reflection_max_rounds: int


def int_setting(env: Mapping[str, str], name: str, default: int, minimum: int) -> int:
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


def load_llm_timeout(env: Mapping[str, str]) -> int:
    """Returns ``LLM_TIMEOUT``, the seconds each LLM request may take (DEC-166).

    Args:
        env: Environment variables, usually ``os.environ``.

    Returns:
        The timeout; 60 when unset.

    Raises:
        ValueError: If the value is not an integer of at least 1.
    """
    return int_setting(env, "LLM_TIMEOUT", default=60, minimum=1)


def load_loop_settings(env: Mapping[str, str]) -> LoopSettings:
    """Returns the loop's settings from the environment, with defaults.

    Args:
        env: Environment variables, usually ``os.environ``.

    Returns:
        The validated settings.

    Raises:
        ValueError: If any value is invalid; the message names its variable.
    """
    return LoopSettings(
        qa_max_iterations=int_setting(env, "QA_MAX_ITERATIONS", default=5, minimum=1),
        run_timeout=int_setting(env, "RUN_TIMEOUT", default=1800, minimum=1),
        llm_timeout=load_llm_timeout(env),
        reflection_max_rounds=int_setting(env, "REFLECTION_MAX_ROUNDS", default=1, minimum=1),
    )

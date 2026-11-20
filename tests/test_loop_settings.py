"""Tests of the Coder-QA loop settings (Lab 3.3, T2).

Covers spec `lab_3_3_a2a_loop` AC-3.3-5 (DEC-163, DEC-166, DEC-168,
DEC-172, DEC-180, DEC-190).
"""

import pytest

from orchestration.settings import load_loop_settings

_VARIABLES = ("QA_MAX_ITERATIONS", "RUN_TIMEOUT", "LLM_TIMEOUT", "REFLECTION_MAX_ROUNDS")


def test_ac_3_3_5_loop_settings_defaults():
    settings = load_loop_settings({})

    assert settings.qa_max_iterations == 5
    assert settings.run_timeout == 1800
    assert settings.llm_timeout == 60
    assert settings.reflection_max_rounds == 1


def test_ac_3_3_5_loop_settings_from_env():
    env = {"QA_MAX_ITERATIONS": "3", "RUN_TIMEOUT": "90", "LLM_TIMEOUT": "12", "REFLECTION_MAX_ROUNDS": "2"}

    settings = load_loop_settings(env)

    assert (settings.qa_max_iterations, settings.run_timeout) == (3, 90)
    assert (settings.llm_timeout, settings.reflection_max_rounds) == (12, 2)


@pytest.mark.parametrize("name", _VARIABLES)
@pytest.mark.parametrize("value", ["0", "x"])
def test_ac_3_3_5_loop_settings_invalid(name, value):
    with pytest.raises(ValueError, match=name):
        load_loop_settings({name: value})

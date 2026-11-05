"""Shared pytest configuration: the opt-in flag for real-LLM tests (DEC-066).

Tests marked with @pytest.mark.llm call the real LLM, which costs tokens and
needs OPENROUTER_API_KEY. They are skipped unless pytest runs with --run-llm,
so `pytest tests/` stays free and fast; with --run-llm and no key they fail.
"""

import os

import pytest
from dotenv import load_dotenv


def pytest_addoption(parser):
    """Registers the --run-llm command-line flag.

    Args:
        parser: Pytest's command-line parser.
    """
    parser.addoption(
        "--run-llm",
        action="store_true",
        default=False,
        help="run tests marked 'llm', which call the real LLM and cost tokens",
    )


def pytest_configure(config):
    """Registers the 'llm' marker.

    Args:
        config: Pytest's configuration object.
    """
    config.addinivalue_line("markers", "llm: calls the real LLM; runs only with --run-llm")


def pytest_collection_modifyitems(config, items):
    """Skips 'llm' tests unless pytest runs with --run-llm.

    Args:
        config: Pytest's configuration object.
        items: Collected test items.
    """
    if config.getoption("--run-llm"):
        return
    skip = pytest.mark.skip(reason="calls the real LLM; run with --run-llm")
    for item in items:
        if "llm" in item.keywords:
            item.add_marker(skip)


def pytest_runtest_setup(item):
    """Fails an 'llm' test early when --run-llm is given without an API key.

    The run was asked for, so a silent skip would hide the problem.

    Args:
        item: The test about to run.
    """
    if "llm" in item.keywords and item.config.getoption("--run-llm"):
        load_dotenv()
        if not os.getenv("OPENROUTER_API_KEY"):
            pytest.fail("--run-llm needs OPENROUTER_API_KEY in the environment or .env")

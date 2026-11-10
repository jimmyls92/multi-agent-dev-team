"""Shared pytest configuration: the real-LLM flag and an isolated workspace.

Tests marked with @pytest.mark.llm call the real LLM, which costs tokens and
needs OPENROUTER_API_KEY. They are skipped unless pytest runs with --run-llm,
so `pytest tests/` stays free and fast; with --run-llm and no key they fail
(DEC-066).

The ``isolated_run`` fixture gives the Coder a temporary workspace and an
in-memory Chroma collection with a fake embedding, so tests never touch
``workspace/`` or ``.chroma/`` and need no network.
"""

import hashlib
import os
import uuid

import chromadb
import pytest
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from dotenv import load_dotenv

import memory
import tools.handlers


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


class HashEmbedding(EmbeddingFunction[Documents]):
    """Deterministic fake embedding: a vector from the SHA-256 of each text.

    Equal texts get equal vectors; nothing is downloaded or computed by a
    model, so retrieval works offline and fast.
    """

    def __init__(self) -> None:
        """Initialises the embedding; it has no settings."""

    def __call__(self, input: Documents) -> Embeddings:
        """Returns one 16-dimension vector per text.

        Args:
            input: Texts to embed.

        Returns:
            The vectors, in the order of the texts.
        """
        return [[byte / 255 for byte in hashlib.sha256(text.encode()).digest()[:16]] for text in input]

    @staticmethod
    def name() -> str:
        """Returns the name Chroma records for this embedding."""
        return "hash-embedding"

    def get_config(self) -> dict:
        """Returns the embedding's configuration, which is empty."""
        return {}

    @staticmethod
    def build_from_config(config: dict) -> "HashEmbedding":
        """Returns a new embedding; the configuration is ignored.

        Args:
            config: Configuration saved by Chroma.
        """
        return HashEmbedding()


@pytest.fixture
def isolated_run(tmp_path, monkeypatch):
    """Points the Coder at a temporary workspace and a fresh in-memory memory.

    Args:
        tmp_path: Pytest's per-test temporary directory.
        monkeypatch: Pytest's monkeypatch fixture.

    Returns:
        The temporary workspace directory, resolved.
    """
    workspace = (tmp_path / "workspace").resolve()
    workspace.mkdir()
    monkeypatch.setattr(tools.handlers, "WORKSPACE_DIR", workspace)
    # The in-memory client is shared in the process: one collection per test.
    collection = chromadb.EphemeralClient().get_or_create_collection(
        f"test-{uuid.uuid4().hex}", embedding_function=HashEmbedding()
    )
    monkeypatch.setattr(memory, "_collection", collection)
    return workspace

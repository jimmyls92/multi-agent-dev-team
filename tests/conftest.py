"""Shared pytest configuration: the real-LLM flag and an isolated workspace.

Tests marked with @pytest.mark.llm call the real LLM, which costs tokens and
needs OPENROUTER_API_KEY. They are skipped unless pytest runs with --run-llm,
so `pytest tests/` stays free and fast; with --run-llm and no key they fail
(DEC-066).

The ``isolated_run`` fixture gives the Coder a temporary workspace and an
in-memory Chroma collection with a fake embedding, so tests never touch
``workspace/`` or ``.chroma/`` and need no network.

The ``workspace`` and ``mcp_session`` fixtures give the MCP tests a real
client session connected in memory to ``tools.mcp_server.server`` over a
temporary workspace (DEC-133).

Two safety nets apply to every test: the workspace always points to a
temporary folder, so ``run()`` never archives the real ``workspace/``
(DEC-114); and outside ``llm`` tests the PM and Coder cannot build a real
model, so a test that forgets its fake fails instead of spending tokens.
"""

import asyncio
import hashlib
import os
import uuid

import chromadb
import pytest
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from dotenv import load_dotenv
from mcp.shared.memory import create_connected_server_and_client_session

import agents.coder_agent
import agents.pm_agent
import memory
import tools.handlers
from tools.mcp_server import server


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


@pytest.fixture(autouse=True)
def _temporary_workspace(tmp_path, monkeypatch):
    """Points the workspace of every test to ``tmp_path / "workspace"``.

    Args:
        tmp_path: Pytest's per-test temporary directory.
        monkeypatch: Pytest's monkeypatch fixture.
    """
    monkeypatch.setattr(tools.handlers, "WORKSPACE_DIR", (tmp_path / "workspace").resolve())


@pytest.fixture(autouse=True)
def _fresh_coder_agent():
    """Clears the Coder's cached default agent before and after every test.

    The agent is compiled once per process with the model of the first
    caller; clearing it keeps a test from reusing another test's model.

    Yields:
        Control to the test.
    """
    agents.coder_agent._default_agent.cache_clear()
    yield
    agents.coder_agent._default_agent.cache_clear()


@pytest.fixture(autouse=True)
def _refuse_real_models(request, monkeypatch):
    """Makes ``get_chat_model`` raise in the PM and the Coder outside ``llm`` tests.

    A test that sets its own fake through ``monkeypatch`` overrides this,
    because its patch is applied later.

    Args:
        request: Pytest's request for the running test.
        monkeypatch: Pytest's monkeypatch fixture.
    """
    if request.node.get_closest_marker("llm"):
        return

    def refuse(model_id: str):
        """Raises instead of building a real chat model.

        Args:
            model_id: The model the code asked for.

        Raises:
            RuntimeError: Always.
        """
        raise RuntimeError(f"real model {model_id!r} requested in a non-llm test")

    monkeypatch.setattr(agents.pm_agent, "get_chat_model", refuse)
    monkeypatch.setattr(agents.coder_agent, "get_chat_model", refuse)


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


@pytest.fixture
def workspace():
    """Creates the temporary workspace set by ``_temporary_workspace``.

    Returns:
        The workspace directory, resolved and existing.
    """
    tools.handlers.WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    return tools.handlers.WORKSPACE_DIR


@pytest.fixture
async def mcp_session():
    """Connects a real MCP client session to the server in memory (DEC-133).

    The SDK's session uses an anyio cancel scope, which must be entered and
    exited in the same task. Pytest-asyncio runs fixture setup and teardown
    in different tasks, so the session lives in a task of its own that stays
    open until the test ends.

    Yields:
        An initialised ``ClientSession`` talking to ``tools.mcp_server.server``.
    """
    opened: asyncio.Future = asyncio.get_running_loop().create_future()
    finished = asyncio.Event()

    async def hold_session() -> None:
        """Opens the session, hands it to the fixture and waits for the test to end."""
        async with create_connected_server_and_client_session(server) as session:
            opened.set_result(session)
            await finished.wait()

    holder = asyncio.create_task(hold_session())
    await asyncio.wait({holder, opened}, return_when=asyncio.FIRST_COMPLETED)
    if not opened.done():
        await holder  # the session failed to open: re-raise its error
    yield opened.result()
    finished.set()
    await holder

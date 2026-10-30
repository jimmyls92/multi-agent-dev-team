# test_memory.py
# Lab 1.1 — Automated verification of the two-tier memory system (C1.2)
#
# Run from the repo root:  pytest tests/test_memory.py -v
# No API key or network LLM call is needed: Chroma runs in memory and the
# LLM client is replaced by a fake.

import os
import uuid
from types import SimpleNamespace

os.environ.setdefault("OPENROUTER_API_KEY", "test-key")  # never a real key in tests

import chromadb
import pytest

import tools.memory as memory
from tools.memory import SLIDING_WINDOW_SIZE, SlidingWindowBuffer, build_context, store_memory


@pytest.fixture
def collection():
    """Fresh in-memory Chroma collection per test."""
    return chromadb.EphemeralClient().get_or_create_collection(f"test_{uuid.uuid4().hex}")


def add_turn(window, user, assistant):
    window.add("user", user)
    window.add("assistant", assistant)


# --- TODO 1: SlidingWindowBuffer ---------------------------------------------


def test_window_default_size_comes_from_config():
    assert SlidingWindowBuffer().max_turns == SLIDING_WINDOW_SIZE


def test_window_messages_use_chat_format():
    window = SlidingWindowBuffer(max_turns=2)
    add_turn(window, "hi", "hello")
    assert window.get_messages() == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]


def test_window_keeps_only_last_n_turns():
    window = SlidingWindowBuffer(max_turns=2)
    for i in range(1, 4):
        add_turn(window, f"question {i}", f"answer {i}")

    contents = [m["content"] for m in window.get_messages()]
    assert contents == ["question 2", "answer 2", "question 3", "answer 3"]


def test_window_get_messages_returns_a_copy():
    window = SlidingWindowBuffer(max_turns=2)
    add_turn(window, "hi", "hello")

    window.get_messages().clear()  # a caller mutating the result...

    assert len(window.get_messages()) == 2  # ...must not empty the window


# --- TODO 2: store_memory ----------------------------------------------------


def test_store_memory_saves_text(collection):
    memory_id = store_memory("I prefer the requests library for HTTP calls", collection)

    stored = collection.get(ids=[memory_id])
    assert stored["documents"] == ["I prefer the requests library for HTTP calls"]


def test_store_memory_uses_unique_ids(collection):
    first = store_memory("same text", collection)
    second = store_memory("same text", collection)

    assert first != second
    assert collection.count() == 2


# --- TODO 3: build_context ---------------------------------------------------


def test_build_context_works_on_empty_store(collection):
    window = SlidingWindowBuffer()
    window.add("user", "Write a hello world script")

    messages = build_context("Write a hello world script", window, collection)

    assert messages[0]["role"] == "system"
    assert messages[1:] == window.get_messages()


def test_build_context_injects_related_memory(collection):
    store_memory("I always use the requests library for HTTP calls", collection)
    store_memory("The capital of France is Paris", collection)

    question = "Which HTTP library should the script use?"
    store_memory(question, collection)  # chat() stores the input before building context
    window = SlidingWindowBuffer()
    window.add("user", question)

    system = build_context(question, window, collection)[0]
    assert system["role"] == "system"
    assert "requests library" in system["content"]


def test_build_context_does_not_retrieve_current_input(collection):
    question = "Write a function that reverses a string"
    store_memory(question, collection)
    window = SlidingWindowBuffer()
    window.add("user", question)

    messages = build_context(question, window, collection)

    assert question not in messages[0]["content"]
    assert sum(m["content"] == question for m in messages) == 1


# --- TODO 4: chat() in agents/coder_agent.py ---------------------------------


class FakeLLM:
    """Records the messages sent to the LLM and returns a fixed reply."""

    def __init__(self, reply="ok"):
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self._reply = reply

    def _create(self, model, messages, **kwargs):
        self.calls.append(messages)
        message = SimpleNamespace(content=self._reply)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


@pytest.fixture
def agent(monkeypatch, collection):
    import agents.coder_agent as coder_agent

    fake = FakeLLM(reply="Here is your code")
    monkeypatch.setattr(coder_agent, "client", fake)
    monkeypatch.setattr(memory, "_collection", collection)
    return coder_agent, fake


def test_chat_updates_window_and_returns_reply(agent):
    coder_agent, fake = agent
    window = SlidingWindowBuffer()

    reply = coder_agent.chat("Write a fizzbuzz function", window)

    assert reply == "Here is your code"
    assert window.get_messages() == [
        {"role": "user", "content": "Write a fizzbuzz function"},
        {"role": "assistant", "content": "Here is your code"},
    ]
    sent = fake.calls[0]
    assert sent[0]["role"] == "system"
    assert sent[-1] == {"role": "user", "content": "Write a fizzbuzz function"}


def test_chat_recalls_previous_session_through_chroma(agent):
    coder_agent, fake = agent
    coder_agent.chat("For HTTP calls I always use the requests library", SlidingWindowBuffer())

    # New window = new session: only long-term memory can supply the fact.
    coder_agent.chat("Which HTTP library do I use?", SlidingWindowBuffer())

    assert "requests library" in fake.calls[-1][0]["content"]

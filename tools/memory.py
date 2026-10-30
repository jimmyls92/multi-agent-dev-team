# memory.py
# Lab 1.1 — Two-tier memory system
#
#   Short-term: SlidingWindowBuffer keeps the last N conversation turns.
#   Long-term:  Chroma semantic store, queried before every LLM call.
#
# The configuration, LLM client and Chroma setup are already written.
# TODO: implement the 3 TODOs below.

import hashlib
import logging
import os
import uuid
from collections import deque
from datetime import datetime, timezone

import chromadb
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

logger = logging.getLogger(__name__)

# --- Configuration (all overridable through .env) ---------------------------

SLIDING_WINDOW_SIZE = int(os.getenv("SLIDING_WINDOW_SIZE", "5"))  # N turns
MEMORY_TOP_K = int(os.getenv("MEMORY_TOP_K", "3"))  # memories retrieved per call
CHROMA_PATH = os.getenv("CHROMA_PATH", ".chroma")  # local persistent store
CHROMA_HOST = os.getenv("CHROMA_HOST")  # set in Docker to use the Chroma service
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
COLLECTION_NAME = os.getenv("CHROMA_COLLECTION", "coder_memory")

SYSTEM_PROMPT = (
    "You are an expert Python coding assistant. "
    "Use the relevant past context when it helps answer the user."
)

# --- LLM client --------------------------------------------------------------

# DEC-002: OpenRouter exposes an OpenAI-compatible API, so the official OpenAI SDK works
# by pointing base_url at it. The key is read from the environment, never
# hard-coded.
llm_client = OpenAI(
    base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
    api_key=os.getenv("OPENROUTER_API_KEY"),
)

# --- Chroma ------------------------------------------------------------------

_collection = None


def get_collection():
    """Return the shared Chroma collection, creating it on first use (DEC-003).

    Uses the Chroma server when CHROMA_HOST is set (Docker), otherwise a local
    on-disk store so memories survive between runs. Embeddings use Chroma's
    default local model (all-MiniLM-L6-v2), so no extra API key is needed.
    """
    global _collection
    if _collection is None:
        if CHROMA_HOST:
            client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
        else:
            client = chromadb.PersistentClient(path=CHROMA_PATH)
        _collection = client.get_or_create_collection(COLLECTION_NAME)
    return _collection


# --- TODO 1: short-term memory -----------------------------------------------


class SlidingWindowBuffer:
    """Keeps only the most recent conversation turns (DEC-004, DEC-005)."""

    def __init__(self, max_turns: int = SLIDING_WINDOW_SIZE):
        if max_turns < 1:
            raise ValueError("max_turns must be at least 1")
        self.max_turns = max_turns
        self._turns = deque(maxlen=max_turns)  # each item is one turn: a list of messages

    def add(self, role: str, content: str) -> None:
        """Append one message ({"role": ..., "content": ...}).

        A "user" message opens a new turn; any other role joins the current one.
        """
        message = {"role": role, "content": content}
        if role == "user":
            self._turns.append([message])  # the oldest turn falls out when full
        elif self._turns:
            self._turns[-1].append(message)
        else:
            raise ValueError("A conversation turn must start with a 'user' message")

    def get_messages(self) -> list[dict]:
        """Return the messages currently in the window, oldest first, as a flat list."""
        return [dict(message) for turn in self._turns for message in turn]


# --- TODO 2: long-term memory (write) ----------------------------------------

# DEC-014: one id per process run; every memory stored in this run carries it.
RUN_ID = uuid.uuid4().hex


def _memory_id(text: str) -> str:
    """Same normalized text -> same id, so repeats are deduplicated (DEC-011, DEC-012)."""
    normalized = " ".join(text.split()).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def store_memory(text: str, collection=None, role: str = "user") -> str:
    """Embed and store a message in Chroma. Returns its id.

    Only user messages are stored today (DEC-008), hence the default role.
    Exact repeats update the existing memory instead of adding a new one
    (DEC-011..DEC-013).
    """
    if not text or not text.strip():
        raise ValueError("Cannot store an empty memory")  # DEC-010
    if collection is None:
        collection = get_collection()

    memory_id = _memory_id(text)
    now = datetime.now(timezone.utc).isoformat()

    # Keep the original creation date when the memory already exists (DEC-013).
    existing = collection.get(ids=[memory_id], include=["metadatas"])
    previous = (existing["metadatas"][0] or {}) if existing["ids"] else {}

    collection.upsert(
        ids=[memory_id],
        documents=[text.strip()],
        metadatas=[{
            "role": role,
            "run_id": RUN_ID,
            "created_at": previous.get("created_at", now),
            "last_seen_at": now,
        }],
    )
    logger.debug("Stored memory %s (run %s)", memory_id[:8], RUN_ID)
    return memory_id


# --- TODO 3: long-term memory (read) + context assembly ----------------------


def build_context(user_input: str, window: SlidingWindowBuffer, collection=None) -> list[dict]:
    """Assemble the message list sent to the LLM.

    Order: system prompt (with retrieved memories) -> sliding window.
    The current user_input is already the last message of the window.
    """
    if collection is None:
        collection = get_collection()
    # TODO 3: query Chroma for memories relevant to user_input, build the
    # system message with them, and return it followed by the window messages.
    raise NotImplementedError

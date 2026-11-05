"""Two-tier memory for the Coder Agent (Lab 1.1, C1.2).

Short-term: SlidingWindowBuffer keeps the last N conversation turns; in the
ReACT loop a turn is one task with all its iterations (DEC-048, DEC-057).
Long-term: a Chroma semantic store, queried before every LLM call, whose
retrieved memories are injected into the system prompt. It holds the user's
tasks and, for each finished task, one outcome memory (DEC-049, DEC-059).

The LLM client lives in llm_client.py (DEC-034); memory is shared
infrastructure, not a tool (DEC-035). Every setting below can be overridden
through .env.

Attributes:
    SLIDING_WINDOW_SIZE: Turns kept in the short-term window.
    MEMORY_TOP_K: Memories retrieved per LLM call.
    CHROMA_PATH: Directory of the local persistent Chroma store.
    CHROMA_HOST: Chroma server host; when set (Docker), it replaces the
        local store.
    CHROMA_PORT: Chroma server port.
    COLLECTION_NAME: Chroma collection that holds the memories.
    RUN_ID: Id of this process run, stored with every memory (DEC-014).
"""

import hashlib
import json
import logging
import os
import uuid
from collections import deque
from datetime import datetime, timezone

import chromadb
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# --- Configuration (all overridable through .env) ----------------------------

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

# --- Chroma ------------------------------------------------------------------

_collection = None


def get_collection():
    """Returns the shared Chroma collection, creating it on first use (DEC-003).

    Uses the Chroma server when CHROMA_HOST is set (Docker), otherwise a local
    on-disk store so memories survive between runs. Embeddings use Chroma's
    default local model (all-MiniLM-L6-v2), so no extra API key is needed.

    Returns:
        The Chroma collection named COLLECTION_NAME.
    """
    global _collection
    if _collection is None:
        if CHROMA_HOST:
            client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
        else:
            client = chromadb.PersistentClient(path=CHROMA_PATH)
        _collection = client.get_or_create_collection(COLLECTION_NAME)
    return _collection


# --- Short-term memory -------------------------------------------------------


class SlidingWindowBuffer:
    """Keeps only the most recent conversation turns (DEC-004, DEC-005).

    A turn starts with a "user" message and holds every message after it until
    the next "user" message. When the window is full, a new turn drops the
    oldest one.

    Attributes:
        max_turns: Maximum number of turns kept.
    """

    def __init__(self, max_turns: int = SLIDING_WINDOW_SIZE):
        """Creates an empty window.

        Args:
            max_turns: Maximum number of turns kept. Defaults to
                SLIDING_WINDOW_SIZE.

        Raises:
            ValueError: If max_turns is less than 1.
        """
        if max_turns < 1:
            raise ValueError("max_turns must be at least 1")
        self.max_turns = max_turns
        self._turns = deque(maxlen=max_turns)  # each item is one turn: a list of messages

    def add(self, role: str, content: str) -> None:
        """Appends one message to the window.

        A "user" message opens a new turn; any other role joins the current one.

        Args:
            role: Message role, for example "user" or "assistant".
            content: Message text.

        Raises:
            ValueError: If a non-"user" message arrives before any turn exists.
        """
        message = {"role": role, "content": content}
        if role == "user":
            self._turns.append([message])  # the oldest turn falls out when full
        elif self._turns:
            self._turns[-1].append(message)
        else:
            raise ValueError("A conversation turn must start with a 'user' message")

    def add_turn(self, messages: list[dict]) -> None:
        """Appends a whole turn at once (DEC-057).

        The ReACT loop collects a task and all its iterations, whose
        observations also have the "user" role, and adds them here when the
        task ends; add() would open a new turn on every observation.

        Args:
            messages: The turn's {"role": ..., "content": ...} dicts, oldest
                first. Copies are stored.

        Raises:
            ValueError: If messages is empty or does not start with a "user"
                message.
        """
        if not messages or messages[0].get("role") != "user":
            raise ValueError("A conversation turn must start with a 'user' message")
        self._turns.append([dict(message) for message in messages])

    def get_turn_starts(self) -> list[str]:
        """Returns the opening user message of each turn in the window.

        In the ReACT loop this is the task of each turn (DEC-048).

        Returns:
            The content of each turn's first message, oldest first.
        """
        return [turn[0]["content"] for turn in self._turns]

    def get_messages(self) -> list[dict]:
        """Returns the messages currently in the window.

        Returns:
            Copies of the messages, oldest first, as a flat list of
            {"role": ..., "content": ...} dicts.
        """
        return [dict(message) for turn in self._turns for message in turn]

    def __len__(self) -> int:
        """Returns the number of turns currently in the window."""
        return len(self._turns)


# --- Long-term memory (write) ------------------------------------------------

# DEC-014: one id per process run; every memory stored in this run carries it.
RUN_ID = uuid.uuid4().hex


def _memory_id(text: str) -> str:
    """Returns the id of a memory, derived from its normalized text.

    The same normalized text always gives the same id, so repeats are
    deduplicated (DEC-011, DEC-012).

    Args:
        text: Memory text.

    Returns:
        SHA-256 hex digest of the text, lowercased and with whitespace
        collapsed.
    """
    normalized = " ".join(text.split()).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def outcome_memory_id(task: str) -> str:
    """Returns the id of a task's outcome memory (DEC-058).

    Derived from the task, so repeating a task updates its outcome memory
    and the tasks in the window give the outcome ids to exclude.

    Args:
        task: Task text as sent by the user.

    Returns:
        "outcome-" followed by the task's memory id.
    """
    return f"outcome-{_memory_id(task)}"


def _upsert_memory(memory_id: str, text: str, role: str, collection) -> None:
    """Writes one memory, keeping its creation date if it exists (DEC-013).

    Args:
        memory_id: Id of the memory.
        text: Memory text, already checked to be non-empty.
        role: Value of the "role" metadata.
        collection: Chroma collection to write to.
    """
    now = datetime.now(timezone.utc).isoformat()
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
    logger.debug("Stored memory %s (run %s)", memory_id[:16], RUN_ID)


def store_memory(text: str, collection=None, role: str = "user") -> str:
    """Embeds and stores a message in Chroma.

    Only user messages (the tasks) are stored as messages (DEC-008, DEC-049),
    hence the default role.
    Exact repeats update the existing memory instead of adding a new one, and
    keep its original creation date (DEC-011..DEC-013).

    Args:
        text: Message to store.
        collection: Chroma collection to use. Defaults to the shared one.
        role: Role of the message author.

    Returns:
        The id of the stored memory.

    Raises:
        ValueError: If text is empty or only whitespace (DEC-010).
    """
    if not text or not text.strip():
        raise ValueError("Cannot store an empty memory")  # DEC-010
    if collection is None:
        collection = get_collection()

    memory_id = _memory_id(text)
    _upsert_memory(memory_id, text, role, collection)
    return memory_id


def store_outcome(
    task: str,
    status: str,
    main_file: str | None,
    explanation: str,
    collection=None,
) -> str:
    """Stores the outcome of a task that ended with a final answer (DEC-049).

    The text is "Task / Status / Main file / Explanation", without the code
    (DEC-059). Its id comes from the task, so running the same task again
    replaces the previous outcome (DEC-058).

    Args:
        task: Task text as sent by the user.
        status: Final status of the task, for example "success".
        main_file: Main file declared by the agent, or None.
        explanation: Final explanation of the agent.
        collection: Chroma collection to use. Defaults to the shared one.

    Returns:
        The id of the stored memory.

    Raises:
        ValueError: If task or explanation is empty or only whitespace
            (DEC-010).
    """
    if not task.strip() or not explanation.strip():
        raise ValueError("Cannot store an outcome without task or explanation")
    if collection is None:
        collection = get_collection()

    text = (
        f"Task: {task.strip()}\n"
        f"Status: {status}\n"
        f"Main file: {main_file or 'none'}\n"
        f"Explanation: {explanation.strip()}"
    )
    memory_id = outcome_memory_id(task)
    _upsert_memory(memory_id, text, "outcome", collection)
    return memory_id


# --- Long-term memory (read) + context assembly ------------------------------

MEMORY_HEADING = "Relevant context from past conversations (may not be relevant):"


def _retrieve_memories(user_input: str, window: SlidingWindowBuffer, collection) -> list[dict]:
    """Returns the long-term memories relevant to the user input.

    Leaves out the input itself, the tasks already in the window and their
    outcome memories (DEC-016, DEC-021, DEC-031, DEC-049).

    Args:
        user_input: Current user message, used as the query.
        window: Short-term window of the conversation.
        collection: Chroma collection to query.

    Returns:
        Up to MEMORY_TOP_K memories, closest first, each a
        {"id", "text", "distance"} dict. Empty when the store is empty or
        retrieval is disabled (MEMORY_TOP_K < 1, DEC-026).
    """
    if MEMORY_TOP_K < 1:
        # DEC-026: retrieval is disabled, which breaks C1.2; warn but keep chatting.
        logger.warning("MEMORY_TOP_K=%d: long-term memory retrieval is disabled", MEMORY_TOP_K)
        return []

    stored = collection.count()
    if stored == 0:
        return []  # first run: nothing to retrieve yet

    # Only tasks and their outcomes are stored (DEC-008, DEC-049). A task in
    # the window brings its own outcome id (DEC-058); observations are never
    # stored, so only the first message of each turn matters.
    # The current input is already stored (DEC-019) but not in the window yet
    # (DEC-031); the outcome of an earlier run of the same task may come back.
    excluded = set()
    for task in window.get_turn_starts():
        excluded.add(_memory_id(task))
        excluded.add(outcome_memory_id(task))
    excluded.add(_memory_id(user_input))

    # Ask for extra results to make up for the ones we drop (DEC-021).
    results = collection.query(
        query_texts=[user_input],
        n_results=min(MEMORY_TOP_K + len(excluded), stored),
        include=["documents", "distances"],
    )
    memories = [
        {"id": memory_id, "text": text, "distance": distance}
        for memory_id, text, distance in zip(
            results["ids"][0], results["documents"][0], results["distances"][0]
        )
        if memory_id not in excluded
    ]
    return memories[:MEMORY_TOP_K]


def build_context(
    user_input: str,
    window: SlidingWindowBuffer,
    collection=None,
    system_prompt: str = SYSTEM_PROMPT,
    turn_messages: list[dict] | None = None,
) -> list[dict]:
    """Assembles the message list sent to the LLM.

    Called before every LLM call, also on every ReACT iteration, with the task
    as user_input (DEC-050, DEC-058). Order: system prompt (with retrieved
    memories) -> sliding window -> current user_input -> messages of the turn
    in progress. The window does not hold the current turn yet; it is added
    only when the turn ends well (DEC-031, DEC-057).

    Args:
        user_input: Current user message (the task in the ReACT loop); also
            the retrieval query.
        window: Short-term window of the conversation.
        collection: Chroma collection to query. Defaults to the shared one.
        system_prompt: Base system message, before the memories. Defaults to
            the Lab 1.1 conversational prompt.
        turn_messages: Messages of the turn in progress after user_input
            (the loop's responses and observations). Defaults to none.

    Returns:
        The messages for the LLM call, as {"role": ..., "content": ...} dicts.
    """
    if collection is None:
        collection = get_collection()
    memories = _retrieve_memories(user_input, window, collection)

    # DEC-015, DEC-022: memories go in the system message; no heading when empty.
    system_content = system_prompt
    if memories:
        lines = "\n".join(f"- {memory['text']}" for memory in memories)
        system_content += f"\n\n{MEMORY_HEADING}\n{lines}"

    window_messages = window.get_messages()
    messages = [
        {"role": "system", "content": system_content},
        *window_messages,
        {"role": "user", "content": user_input},
        *(dict(message) for message in turn_messages or []),
    ]

    # DEC-025: C1.2 evidence — one INFO line per call; full LLM input at DEBUG.
    retrieved = ", ".join(f'{m["id"][:8]} ({m["distance"]:.2f})' for m in memories)
    logger.info("Context: window %d/%d turns, %d msgs | %d memories%s",
                len(window), window.max_turns, len(window_messages),
                len(memories), f": {retrieved}" if memories else "")
    logger.debug("LLM input:\n%s", json.dumps(messages, ensure_ascii=False, indent=2))
    return messages

import re as _re
import uuid
from typing import List, Callable, Optional
from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage
from langchain_groq import ChatGroq
from langgraph.store.base import BaseStore


# ── LTM Schema ───────────────────────────────────────────────
class MemoryItem(BaseModel):
    text: str = Field(description="One short atomic fact about the user")
    is_new: bool = Field(description="True if NEW info, False if duplicate")


class MemoryDecision(BaseModel):
    should_write: bool
    memories: List[MemoryItem] = Field(default_factory=list)


# ── Prompt ───────────────────────────────────────────────────
MEMORY_EXTRACT_PROMPT = """You maintain a clean long-term memory for a user.

EXISTING MEMORIES:
{existing}

TASK:
Review the user's latest message and extract ONLY permanently useful facts.

STORE ONLY:
- Name or identity        → "User's name is Sun"
- Stable preferences      → "User prefers dark mode"
- Ongoing projects/goals  → "User is building a RAG chatbot"
- Tools or platforms      → "User uses LangGraph and Python"
- Financial habits        → "User tracks monthly expenses"

NEVER STORE (return should_write=false immediately):
- Greetings: "hi", "hello", "hey", "haha", "heh", "daami", "thikxa"
- Emotional states: "I am fine", "I am good", "I am tired"
- Questions the user asked: "user asked about X", "user asked for Y"
- One-off calculations or lookups
- Small talk, laughter, filler words
- Anything in Nepali/Hindi that is just casual conversation
- Any message shorter than 6 words that contains no identity/preference facts

DEDUPLICATION:
- Set is_new=true ONLY if the fact is genuinely new vs EXISTING MEMORIES
- If same meaning already exists, set is_new=false

RULES:
- One short atomic English sentence per memory item
- No speculation — only facts the user explicitly stated about themselves
- When in doubt, do NOT store (return should_write=false)
"""

# ── Pre-filter patterns — skip LLM call entirely for these ───
_SKIP_PATTERNS = [
    r"^(hi|hey|hello|haha|heh|lol|ok|okay|ohh|oh|hmm|umm|daami|thikxa|chaliraxa|haai|namaste)[\s!?.]*$",
    r"^(i am fine|i'm fine|i am good|i'm good|i am ok|i'm ok|fine|good|great|nice)[\s!?.]*$",
    r"^[\w\s]{1,15}$",
]
_SKIP_RE = [_re.compile(p, _re.IGNORECASE) for p in _SKIP_PATTERNS]


def _should_skip(message: str) -> bool:
    """Return True if the message is obviously not worth extracting from."""
    msg = message.strip()

    # Skip short Devanagari casual messages
    devanagari_ratio = len(_re.findall(r"[\u0900-\u097F]", msg)) / max(len(msg), 1)
    if devanagari_ratio > 0.4 and len(msg) < 60:
        return True

    for pattern in _SKIP_RE:
        if pattern.match(msg):
            return True

    return False


# ── LTM Manager class ────────────────────────────────────────
class LongTermMemory:
    """
    Manages user long-term memory using LangGraph PostgresStore.

    Supports multi-key rotation: pass a `key_factory` callable that returns
    a fresh ChatGroq instance on each call.  If omitted, the single `llm`
    passed at init is used for every call (original behaviour).

    Key-rotation flow:
        1. extract_and_save() builds a fresh extractor via key_factory()
        2. On a 429/rate-limit it calls key_factory() again to get the next key
        3. Retries up to `max_retries` times before giving up

    - Pre-filters obvious non-storable messages before calling LLM
    - Extracts only meaningful user facts (name, projects, preferences)
    - Deduplicates using is_new flag
    - Scales: ≤30 memories → return all | >30 → keyword-scored top-10
    """

    def __init__(
        self,
        llm: ChatGroq,
        key_factory: Optional[Callable[[], ChatGroq]] = None,
        max_retries: int = 5,
    ):
        """
        Args:
            llm:         Initial / fallback ChatGroq instance.
            key_factory: Optional callable that returns a new ChatGroq on each
                         call with the next rotated key.  When provided, a fresh
                         instance is used for every LLM invocation.
            max_retries: How many keys to try before giving up on a rate limit.
        """
        self._base_llm = llm
        self._key_factory = key_factory
        self._max_retries = max_retries
        # Build the initial extractor from the base llm
        self.extractor = llm.with_structured_output(MemoryDecision)

    # ── internal helpers ──────────────────────────────────────

    def _fresh_extractor(self):
        """Return a structured-output extractor using the next rotated key."""
        if self._key_factory is not None:
            return self._key_factory().with_structured_output(MemoryDecision)
        return self.extractor  # single-key fallback

    @staticmethod
    def _is_rate_limit(exc: Exception) -> bool:
        msg = str(exc).lower()
        return "rate_limit_exceeded" in msg or "429" in msg

    # ── public API ────────────────────────────────────────────

    def extract_and_save(
        self,
        store: BaseStore,
        user_id: str,
        last_message: str,
    ) -> None:
        """Extract facts from user message and save new ones to store."""
        # Pre-filter: skip obviously non-storable messages without LLM call
        if _should_skip(last_message):
            print(f"[LTM] skipped (pre-filter): {last_message[:40]!r}")
            return

        ns = ("user", user_id, "details")

        try:
            items = store.search(ns)
            existing = (
                "\n".join(it.value.get("data", "") for it in items)
                if items
                else "(empty)"
            )
        except Exception as e:
            print(f"[LTM] store.search error: {e}")
            return

        prompt_messages = [
            SystemMessage(content=MEMORY_EXTRACT_PROMPT.format(existing=existing)),
            {"role": "user", "content": last_message},
        ]

        # ── retry loop with key rotation ──────────────────────
        last_exc = None
        for attempt in range(self._max_retries):
            try:
                extractor = self._fresh_extractor()
                decision: MemoryDecision = extractor.invoke(prompt_messages)
                break  # success — exit retry loop
            except Exception as exc:
                if self._is_rate_limit(exc):
                    last_exc = exc
                    print(
                        f"[LTM] rate limit on attempt {attempt + 1}"
                        f"/{self._max_retries}, rotating key…"
                    )
                    # continue → next attempt uses key_factory() again
                else:
                    print(f"[LTM] extraction error: {exc}")
                    return
        else:
            # All retries exhausted
            print(f"[LTM] all keys rate-limited, skipping memory save: {last_exc}")
            return

        # ── persist new memories ──────────────────────────────
        if decision.should_write:
            for mem in decision.memories:
                if mem.is_new and mem.text.strip():
                    store.put(ns, str(uuid.uuid4()), {"data": mem.text.strip()})
                    print(f"[LTM] saved: {mem.text.strip()}")
        else:
            print(f"[LTM] nothing to store for: {last_message[:40]!r}")

    def fetch(
        self,
        store: BaseStore,
        user_id: str,
        query: str = "",
    ) -> str:
        """
        Fetch relevant LTM memories as a plain string.
        ≤30 memories → return all
        >30 memories → return top-10 by keyword overlap with query
        """
        try:
            ns = ("user", user_id, "details")
            items = store.search(ns)
            if not items:
                return ""

            if len(items) <= 30:
                return "\n".join(it.value.get("data", "") for it in items)

            # keyword-overlap scoring for large memory stores
            q_words = set(query.lower().split())
            scored = sorted(
                [
                    (
                        len(q_words & set(it.value.get("data", "").lower().split())),
                        it.value.get("data", ""),
                    )
                    for it in items
                ],
                reverse=True,
            )
            return "\n".join(text for _, text in scored[:10])

        except Exception as e:
            print(f"[LTM] fetch error: {e}")
            return ""

    def get_all(self, store: BaseStore, user_id: str) -> list[str]:
        """Return all stored memories for a user — for UI display."""
        try:
            ns = ("user", user_id, "details")
            return [it.value.get("data", "") for it in store.search(ns)]
        except Exception:
            return []

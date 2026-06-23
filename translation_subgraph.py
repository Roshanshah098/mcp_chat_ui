from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage
from dotenv import load_dotenv

load_dotenv(override=True)

# ── LLM (same model family as backend) ────────────────────────
_translation_llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0)


# ── Subgraph state ─────────────────────────────────────────────
class TranslationState(TypedDict):
    user_message: str  # last human message (for language detection)
    assistant_response: str  # last AI message (to be translated if needed)
    detected_language: str  # filled by detect_language node
    final_response: str  # filled by translate_response node


# ── Supported languages ────────────────────────────────────────
SUPPORTED_LANGUAGES = {
    "nepali",
    "hindi",
    "sanskrit",
    "english",
}

LANGUAGE_DISPLAY = {
    "nepali": "Nepali (नेपाली)",
    "hindi": "Hindi (हिन्दी)",
    "sanskrit": "Sanskrit (संस्कृतम्)",
    "english": "English",
}

TRANSLATION_PROMPTS = {
    "nepali": (
        "Translate the following text into natural, fluent Nepali (नेपाली). "
        "Preserve all formatting including markdown bold (**text**), numbered lists, "
        "and bullet points. Keep technical terms (like quantum physics concepts) "
        "as they are or use standard Nepali equivalents. "
        "Do not add any extra commentary — return only the translated text."
    ),
    "hindi": (
        "Translate the following text into natural, fluent Hindi (हिन्दी). "
        "Preserve all formatting including markdown bold (**text**), numbered lists, "
        "and bullet points. Keep technical terms as they are or use standard Hindi equivalents. "
        "Do not add any extra commentary — return only the translated text."
    ),
    "sanskrit": (
        "Translate the following text into Sanskrit (संस्कृतम्) using Devanagari script. "
        "Use classical Sanskrit where possible. Preserve numbered lists and structure. "
        "For highly technical modern terms with no Sanskrit equivalent, keep the English term. "
        "Do not add any extra commentary — return only the translated text."
    ),
}

DETECT_PROMPT = """You are a language detector.

Identify the primary language of the user's message below.
Reply with EXACTLY one word — all lowercase — from this list:
  english | nepali | hindi | sanskrit

Rules:
- If the message contains Devanagari script (नेपाली / हिन्दी / संस्कृत characters), detect accordingly.
- If the message is a mix (code-switching), pick the dominant language.
- If you're unsure, reply: english

User message:
{message}
"""


# Phrases that explicitly request English — always treated as English
_ENGLISH_OVERRIDE_PHRASES = [
    "talk in english",
    "speak english",
    "speak in english",
    "reply in english",
    "respond in english",
    "write in english",
    "use english",
    "in english",
    "english only",
    "english please",
    "switch to english",
    "back to english",
    "type in english",
]


# ── Node 1: detect_language ────────────────────────────────────
async def detect_language(state: TranslationState) -> dict:
    """
    Detects the language of the user's last message.
    Returns 'english' | 'nepali' | 'hindi' | 'sanskrit'.

    Short-circuits to 'english' if the message explicitly requests
    English (e.g. "talk in english", "reply in english").
    """
    user_msg = state.get("user_message", "").strip()

    if not user_msg:
        return {"detected_language": "english"}

    # Fast path: explicit English override
    lower_msg = user_msg.lower()
    if any(phrase in lower_msg for phrase in _ENGLISH_OVERRIDE_PHRASES):
        print("[Translation] English override detected — skipping translation")
        return {"detected_language": "english"}

    prompt = DETECT_PROMPT.format(message=user_msg)
    response = await _translation_llm.ainvoke(prompt)
    raw = (
        response.content.strip().lower().split()[0]
        if response.content.strip()
        else "english"
    )

    lang = raw if raw in SUPPORTED_LANGUAGES else "english"
    print(f"[Translation] Detected language: {lang!r} (raw: {raw!r})")
    return {"detected_language": lang}


# ── Node 2: translate_response ─────────────────────────────────
async def translate_response(state: TranslationState) -> dict:
    """
    Translates assistant_response if detected_language != 'english'.
    If English (or no translation prompt defined), passes through unchanged.
    """
    lang = state.get("detected_language", "english")
    response_text = state.get("assistant_response", "")

    if lang == "english" or lang not in TRANSLATION_PROMPTS:
        return {"final_response": response_text}

    if not response_text.strip():
        return {"final_response": response_text}

    system_prompt = TRANSLATION_PROMPTS[lang]
    messages = [
        SystemMessage(content=system_prompt),
        {"role": "user", "content": response_text},
    ]

    translated = await _translation_llm.ainvoke(messages)
    translated_text = translated.content.strip()

    # Sanity check: if translated text has far fewer spaces than expected
    # (e.g. Groq returned words joined without spaces), discard it and
    # return the original English response unchanged.
    def _space_ratio(t: str) -> float:
        return t.count(" ") / max(len(t), 1)

    original_ratio = _space_ratio(response_text)
    translated_ratio = _space_ratio(translated_text)

    # If original had reasonable spacing but translated has almost none → corrupted
    if original_ratio > 0.05 and translated_ratio < 0.02:
        print(
            f"[Translation] Corrupted output detected (space ratio {translated_ratio:.3f}), returning original"
        )
        return {"final_response": response_text}

    print(
        f"[Translation] Translated to {LANGUAGE_DISPLAY[lang]}: {translated_text[:80]}…"
    )
    return {"final_response": translated_text}


# ── Build + compile subgraph ───────────────────────────────────
_subgraph_builder = StateGraph(TranslationState)
_subgraph_builder.add_node("detect_language", detect_language)
_subgraph_builder.add_node("translate_response", translate_response)
_subgraph_builder.add_edge(START, "detect_language")
_subgraph_builder.add_edge("detect_language", "translate_response")
_subgraph_builder.add_edge("translate_response", END)

translation_subgraph = _subgraph_builder.compile()


# ── Convenience helper (called from backend) ───────────────────
async def run_translation(user_message: str, assistant_response: str) -> str:
    """
    Runs the translation subgraph and returns the final (possibly translated)
    response string.  Drop-in async helper for use in backend nodes.

    Args:
        user_message:       The raw user message (used for language detection).
        assistant_response: The assistant's English response to translate.

    Returns:
        Translated string (or original if English / detection failed).
    """
    result = await translation_subgraph.ainvoke(
        {
            "user_message": user_message,
            "assistant_response": assistant_response,
            "detected_language": "",
            "final_response": "",
        }
    )
    return result.get("final_response", assistant_response)

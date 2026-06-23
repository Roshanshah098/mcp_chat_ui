import queue
import re
import uuid
import streamlit as st
from lang_rag_backend import (
    chatbot,
    ingest_document,
    remove_document,
    retrieve_all_threads,
    submit_async_task,
    run_async,
    thread_document_metadata,
    thread_has_document,
    save_thread_title,
    get_all_thread_titles,
    get_user_memories,
    SUPPORTED_EXTENSIONS,
    checkpointer,
)
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

# ── Port where dashboard.py runs (streamlit run dashboard.py --server.port 8502) ──
DASHBOARD_URL = "http://localhost:8502"

# =========================== Page Config ===========================
st.set_page_config(page_title="MCP Chat", page_icon="💬", layout="centered")

# =========================== Custom CSS ===========================
st.markdown(
    """
<style>
[data-testid="stSidebar"] {
    background:#0f0f11;
    border-right:1px solid #1e1e24;
}
[data-testid="stSidebar"] * { color:#e2e2e6 !important; }
.brand-header {
    display:flex; align-items:center; gap:10px;
    padding:4px 0 20px 0; border-bottom:1px solid #1e1e24; margin-bottom:18px;
}
.brand-icon {
    width:32px; height:32px;
    background:linear-gradient(135deg,#6366f1,#8b5cf6);
    border-radius:8px; display:flex;
    align-items:center; justify-content:center; font-size:16px;
}
.brand-name { font-size:17px; font-weight:700; letter-spacing:-0.3px; color:#f1f1f3 !important; }
.section-label {
    font-size:10px; font-weight:700; letter-spacing:1.2px; text-transform:uppercase;
    color:#555568 !important; margin:18px 0 8px 2px;
}
.doc-badge {
    background:#1a1a2e; border:1px solid #6366f1; border-radius:8px;
    padding:8px 10px; font-size:12px; margin:8px 0; color:#a5b4fc !important;
}
.memory-badge {
    background:#0f1a0f; border:1px solid #16a34a; border-radius:8px;
    padding:8px 10px; font-size:11px; margin:6px 0; color:#86efac !important; line-height:1.6;
}
.approval-card {
    background:#1c1a0e; border:1px solid #ca8a04;
    border-radius:10px; padding:16px 18px; margin:12px 0;
}
/* analytics link pill */
.dash-link {
    display:flex; align-items:center; gap:8px;
    background:#12121e; border:1px solid #2d2d4e;
    border-radius:8px; padding:8px 12px;
    font-size:12px; font-weight:600; color:#a5b4fc !important;
    text-decoration:none; margin-bottom:16px;
    transition:border-color .2s;
}
.dash-link:hover { border-color:#6366f1; }
/* first New-chat button */
[data-testid="stSidebar"] [data-testid="stButton"]:first-of-type button {
    background:#6366f1 !important; color:#fff !important;
    border:none !important; border-radius:8px !important;
    font-weight:600 !important; width:100% !important;
}
[data-testid="stSidebar"] [data-testid="stButton"]:first-of-type button:hover {
    background:#4f46e5 !important;
}
</style>
""",
    unsafe_allow_html=True,
)

# =========================== Utilities ===========================
USER_ID = "default_user"

_ROMANIZED_TRIGGERS = [
    "tapai",
    "timi",
    "maaile",
    "bhai",
    "ksto",
    "k xa",
    "k gaardaixau",
    "namaste",
    "kya hal",
    "theek hai",
    "kaise",
    "sathi",
    "yaar",
    "hajur",
    "haina",
    "garcha",
    "garnu",
    "sunnu",
    "hunchha",
]
_ENGLISH_OVERRIDES = [
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


def _is_non_english(text: str) -> bool:
    lower = text.lower()
    if any(p in lower for p in _ENGLISH_OVERRIDES):
        return False
    has_devanagari = bool(re.search(r"[\u0900-\u097F]", text))
    has_romanized = any(t in lower for t in _ROMANIZED_TRIGGERS)
    return has_devanagari or has_romanized


def _extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(block.get("text", ""))
        return "".join(parts)
    return str(content) if content else ""


def _strip_function_calls(content) -> str:
    text = _extract_text(content)
    if not text:
        return ""
    text = re.sub(r"<function=[^>]*>.*?</function>", "", text, flags=re.DOTALL)
    text = re.sub(r"<function=[^>]*>\{[^<]*\}", "", text, flags=re.DOTALL)
    text = re.sub(r"</function>", "", text)
    return text.strip()


def generate_thread_id():
    return str(uuid.uuid4())


def reset_chat():
    tid = generate_thread_id()
    st.session_state["thread_id"] = tid
    _add_thread_to_front(tid)
    st.session_state["message_history"] = []


def _add_thread_to_front(tid):
    tid = str(tid)
    threads = st.session_state.get("chat_threads", [])
    if tid in threads:
        threads.remove(tid)
    threads.insert(0, tid)
    st.session_state["chat_threads"] = threads


def load_conversation(thread_id):
    state = chatbot.get_state(
        config={"configurable": {"thread_id": str(thread_id), "user_id": USER_ID}}
    )
    return state.values.get("messages", [])


def delete_thread(tid):
    tid = str(tid)
    try:
        run_async(checkpointer.adelete_thread({"configurable": {"thread_id": tid}}))
    except Exception:
        pass
    threads = st.session_state.get("chat_threads", [])
    if tid in threads:
        threads.remove(tid)
    st.session_state["chat_threads"] = threads
    st.session_state["thread_titles"].pop(tid, None)
    if st.session_state.get("thread_id") == tid:
        reset_chat()


def file_icon(filetype):
    return "📝" if filetype == ".docx" else "📄"


def make_title(thread_id, titles):
    return titles.get(str(thread_id), f"Chat · {str(thread_id)[-8:]}")


def safe_md(text: str) -> str:
    return text.replace("$", "\\$") if text else ""


def get_pending_approval(config):
    try:
        state = chatbot.get_state(config=config)
        for task in state.tasks or []:
            for iv in getattr(task, "interrupts", None) or []:
                return iv.value
    except Exception:
        pass
    return None


# ======================= Session Init ==========================
if "message_history" not in st.session_state:
    st.session_state["message_history"] = []
if "thread_id" not in st.session_state:
    st.session_state["thread_id"] = generate_thread_id()
if "chat_threads" not in st.session_state:
    st.session_state["chat_threads"] = list(retrieve_all_threads())
if "ingested_docs" not in st.session_state:
    st.session_state["ingested_docs"] = {}
if "thread_titles" not in st.session_state:
    st.session_state["thread_titles"] = get_all_thread_titles()

_add_thread_to_front(st.session_state["thread_id"])

thread_key = str(st.session_state["thread_id"])
thread_docs = st.session_state["ingested_docs"].setdefault(thread_key, {})
CONFIG = {
    "configurable": {"thread_id": thread_key, "user_id": USER_ID},
    "metadata": {"thread_id": thread_key},
    "run_name": "chat_turn",
}

# ============================ Sidebar ============================
with st.sidebar:
    # ── Brand ──
    st.markdown(
        """
        <div class="brand-header">
            <div class="brand-icon">✦</div>
            <span class="brand-name">MCP Chat</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Analytics dashboard link ──────────────────────────────
    st.markdown(
        f'<a href="{DASHBOARD_URL}" target="_blank" class="dash-link">'
        "📊 &nbsp;Open Analytics Dashboard"
        "</a>",
        unsafe_allow_html=True,
    )

    st.button("＋ New chat", on_click=reset_chat, use_container_width=True)

    st.markdown('<p class="section-label">Document</p>', unsafe_allow_html=True)
    doc_meta = thread_document_metadata(thread_key)
    if doc_meta:
        icon = file_icon(doc_meta.get("filetype", ".pdf"))
        st.markdown(
            f"""
            <div class="doc-badge">
                {icon} <b>{doc_meta.get('filename')}</b><br>
                {doc_meta.get('chunks')} chunks · {doc_meta.get('documents')} pages
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("🗑️ Remove document", use_container_width=True):
            remove_document(thread_key)
            st.rerun()
    else:
        st.caption("No document uploaded yet.")
        uploaded_file = st.file_uploader(
            "Upload PDF or DOCX", type=["pdf", "docx"], label_visibility="collapsed"
        )
        if uploaded_file:
            existing = thread_document_metadata(thread_key)
            if existing and existing.get("filename") == uploaded_file.name:
                st.caption(f"`{uploaded_file.name}` already indexed.")
            else:
                with st.status("Indexing document…", expanded=True) as sb:
                    try:
                        summary = ingest_document(
                            uploaded_file.getvalue(),
                            thread_id=thread_key,
                            filename=uploaded_file.name,
                        )
                        thread_docs[uploaded_file.name] = summary
                        sb.update(label="✅ Indexed", state="complete", expanded=False)
                    except ValueError as e:
                        sb.update(label=f"❌ {e}", state="error", expanded=False)
                st.rerun()

    st.markdown('<p class="section-label">My Memory</p>', unsafe_allow_html=True)
    memories = get_user_memories(USER_ID)
    if memories:
        memory_lines = "<br>".join(f"• {m}" for m in memories)
        st.markdown(
            f"""
            <div class="memory-badge">
                🧠 <b>What I remember:</b><br>{memory_lines}
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.caption("No memories yet — tell me about yourself!")

    st.markdown('<p class="section-label">Recent</p>', unsafe_allow_html=True)

    selected_thread = None
    titles = st.session_state["thread_titles"]
    threads = st.session_state["chat_threads"]

    if not threads:
        st.caption("No past conversations yet.")
    else:
        for tid in threads:
            tid = str(tid)
            title = make_title(tid, titles)
            meta = thread_document_metadata(tid)
            if thread_has_document(tid):
                icon = file_icon(meta.get("filetype", ".pdf"))
                label = f"{icon} {title}"
            else:
                label = f"💬 {title}"

            is_active = tid == thread_key
            display_label = f"▶ {title}" if is_active else label

            col1, col2 = st.columns([10, 1])
            with col1:
                if st.button(
                    display_label, key=f"thread_{tid}", use_container_width=True
                ):
                    selected_thread = tid
            with col2:
                if st.button(
                    "🗑", key=f"del_thread_{tid}", help="Delete this conversation"
                ):
                    delete_thread(tid)
                    st.rerun()

# ============================= Main UI ============================
st.title("MCP + RAG Chatbot")

doc_meta = thread_document_metadata(thread_key)
if doc_meta:
    icon = file_icon(doc_meta.get("filetype", ".pdf"))
    st.caption(
        f"{icon} Active doc: **{doc_meta.get('filename')}** — "
        f"{doc_meta.get('chunks')} chunks, {doc_meta.get('documents')} pages"
    )

for message in st.session_state["message_history"]:
    with st.chat_message(message["role"]):
        st.markdown(safe_md(message["content"]))

# ── Approval UI ───────────────────────────────────────────────
pending = get_pending_approval(CONFIG)
if pending:
    summary = pending.get("summary", "Proceed with this action?")
    st.markdown(
        f"""
        <div class="approval-card">
            ⚠️ <b>Approval needed</b><br><br>
            {summary.replace("$", "$")}
        </div>
        """,
        unsafe_allow_html=True,
    )
    col1, col2 = st.columns(2)
    with col1:
        if st.button("✅ Approve", use_container_width=True, key="approve_btn"):

            async def _approve():
                return await chatbot.ainvoke(
                    Command(resume={"approved": True}), config=CONFIG
                )

            result = run_async(_approve())
            if result and result.get("messages"):
                for msg in reversed(result["messages"]):
                    if isinstance(msg, AIMessage) and msg.content:
                        st.session_state["message_history"].append(
                            {
                                "role": "assistant",
                                "content": _strip_function_calls(msg.content),
                            }
                        )
                        break
            st.rerun()
    with col2:
        if st.button("❌ Reject", use_container_width=True, key="reject_btn"):

            async def _reject():
                return await chatbot.ainvoke(
                    Command(resume={"approved": False}), config=CONFIG
                )

            result = run_async(_reject())
            if result and result.get("messages"):
                for msg in reversed(result["messages"]):
                    if isinstance(msg, AIMessage) and msg.content:
                        st.session_state["message_history"].append(
                            {
                                "role": "assistant",
                                "content": _strip_function_calls(msg.content),
                            }
                        )
                        break
            st.rerun()

# ── Chat input ────────────────────────────────────────────────
user_input = st.chat_input("Ask anything — search, math, expenses, or your document…")

if user_input:
    titles = st.session_state["thread_titles"]
    if thread_key not in titles:
        title = user_input[:40] + ("…" if len(user_input) > 40 else "")
        save_thread_title(thread_key, title)
        st.session_state["thread_titles"][thread_key] = title

    _add_thread_to_front(thread_key)

    st.session_state["message_history"].append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(safe_md(user_input))

    needs_translation = _is_non_english(user_input)

    with st.chat_message("assistant"):
        status_holder = {"box": None}
        stream_error = {"value": None}
        streamed_chunks: list[str] = []

        def ai_only_stream():
            event_queue: queue.Queue = queue.Queue()

            async def run_stream():
                try:
                    async for message_chunk, metadata in chatbot.astream(
                        {"messages": [HumanMessage(content=user_input)]},
                        config=CONFIG,
                        stream_mode="messages",
                    ):
                        event_queue.put((message_chunk, metadata))
                except Exception as exc:
                    event_queue.put(("error", exc))
                finally:
                    event_queue.put(None)

            submit_async_task(run_stream())

            while True:
                item = event_queue.get()
                if item is None:
                    break
                message_chunk, metadata = item

                if message_chunk == "error":
                    err_str = str(metadata)
                    import traceback

                    print(f"\n[CHAT ERROR] {repr(metadata)}", flush=True)
                    if hasattr(metadata, "__traceback__"):
                        traceback.print_tb(metadata.__traceback__)
                    stream_error["value"] = err_str
                    if "rate_limit_exceeded" in err_str or "429" in err_str:
                        yield "⏳ Usage limit reached. Please try again in a little while."
                    elif (
                        "api_key" in err_str.lower() or "credentials" in err_str.lower()
                    ):
                        yield "🔑 API key missing. Please check your `.env` file."
                    elif (
                        "connection" in err_str.lower() or "timeout" in err_str.lower()
                    ):
                        yield "🌐 Connection issue. Please check your internet."
                    else:
                        yield f"⚠️ Something went wrong.\n\n`{err_str[:500]}`"
                    return

                if isinstance(message_chunk, ToolMessage):
                    tool_name = getattr(message_chunk, "name", "tool")
                    if status_holder["box"] is None:
                        status_holder["box"] = st.status(
                            f"🔧 Using `{tool_name}` …", expanded=True
                        )
                    else:
                        status_holder["box"].update(
                            label=f"🔧 Using `{tool_name}` …",
                            state="running",
                            expanded=True,
                        )

                node = (
                    metadata.get("langgraph_node", "")
                    if isinstance(metadata, dict)
                    else ""
                )
                if (
                    isinstance(message_chunk, AIMessage)
                    and node == "chat_node"
                    and not getattr(message_chunk, "tool_calls", [])
                    and message_chunk.content
                ):
                    raw = message_chunk.content
                    if isinstance(raw, str):
                        chunk_text = raw
                    elif isinstance(raw, list):
                        chunk_text = "".join(
                            b.get("text", "") if isinstance(b, dict) else str(b)
                            for b in raw
                        )
                    else:
                        chunk_text = str(raw) if raw else ""

                    if chunk_text:
                        streamed_chunks.append(chunk_text)
                        yield chunk_text

        st.write_stream(ai_only_stream())

        if status_holder["box"] is not None:
            status_holder["box"].update(
                label="✅ Done", state="complete", expanded=False
            )

    # ── Save final assistant message to history — ONCE ────────
    if not stream_error["value"]:
        if needs_translation:
            graph_state = chatbot.get_state(config=CONFIG)
            all_msgs = graph_state.values.get("messages", [])
            final_ai = next(
                (
                    m
                    for m in reversed(all_msgs)
                    if isinstance(m, AIMessage) and m.content
                ),
                None,
            )
            if final_ai:
                final_text = _strip_function_calls(final_ai.content)
                if final_text:
                    st.session_state["message_history"].append(
                        {"role": "assistant", "content": final_text}
                    )
        else:
            streamed_text = _strip_function_calls("".join(streamed_chunks)).strip()
            if streamed_text:
                st.session_state["message_history"].append(
                    {"role": "assistant", "content": streamed_text}
                )

    if get_pending_approval(CONFIG):
        st.rerun()

# ── Thread switch ─────────────────────────────────────────────
if selected_thread:
    selected_thread = str(selected_thread)
    st.session_state.setdefault("saved_histories", {})[thread_key] = list(
        st.session_state["message_history"]
    )
    st.session_state["thread_id"] = selected_thread
    _add_thread_to_front(selected_thread)

    if selected_thread in st.session_state.get("saved_histories", {}):
        st.session_state["message_history"] = st.session_state["saved_histories"][
            selected_thread
        ]
        st.rerun()

    messages = load_conversation(selected_thread)
    temp_messages = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            role = "user"
        elif isinstance(msg, AIMessage):
            role = "assistant"
        else:
            continue
        if msg.content:
            text = _strip_function_calls(msg.content)
            if text:
                temp_messages.append({"role": role, "content": text})
    st.session_state["message_history"] = temp_messages
    st.rerun()

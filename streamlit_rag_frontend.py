import queue
import uuid

import streamlit as st
from langraph_rag_backend import (
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
    SUPPORTED_EXTENSIONS,
)
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

# =========================== Page Config ===========================
st.set_page_config(page_title="MCP Chat", page_icon="💬", layout="centered")

# =========================== Custom CSS ===========================
st.markdown(
    """
<style>
[data-testid="stSidebar"] { background:#0f0f11; border-right:1px solid #1e1e24; }
[data-testid="stSidebar"] * { color:#e2e2e6 !important; }
.brand-header {
    display:flex; align-items:center; gap:10px;
    padding:4px 0 20px 0; border-bottom:1px solid #1e1e24; margin-bottom:18px;
}
.brand-icon {
    width:32px; height:32px;
    background:linear-gradient(135deg,#6366f1,#8b5cf6);
    border-radius:8px; display:flex; align-items:center;
    justify-content:center; font-size:16px;
}
.brand-name { font-size:17px; font-weight:700; letter-spacing:-0.3px; color:#f1f1f3 !important; }
.section-label {
    font-size:10px; font-weight:700; letter-spacing:1.2px;
    text-transform:uppercase; color:#555568 !important; margin:18px 0 8px 2px;
}
.doc-badge {
    background:#1a1a2e; border:1px solid #6366f1; border-radius:8px;
    padding:8px 10px; font-size:12px; margin:8px 0; color:#a5b4fc !important;
}
.approval-card {
    background:#1c1a0e; border:1px solid #ca8a04; border-radius:10px;
    padding:16px 18px; margin:12px 0;
}
[data-testid="stSidebar"] [data-testid="stButton"]:first-of-type button {
    background:#6366f1 !important; color:#fff !important; border:none !important;
    border-radius:8px !important; font-weight:600 !important; width:100% !important;
}
[data-testid="stSidebar"] [data-testid="stButton"]:first-of-type button:hover { background:#4f46e5 !important; }
[data-testid="stSidebar"] [data-testid="stButton"]:not(:first-of-type) button {
    background:transparent !important; border:1px solid #1e1e24 !important;
    border-radius:7px !important; color:#b0b0c0 !important; font-size:13px !important;
    text-align:left !important; padding:0.4rem 0.75rem !important;
    width:100% !important; margin-bottom:4px !important;
}
[data-testid="stSidebar"] [data-testid="stButton"]:not(:first-of-type) button:hover {
    background:#18181f !important; border-color:#6366f1 !important; color:#e2e2f0 !important;
}
</style>
""",
    unsafe_allow_html=True,
)


# =========================== Utilities ===========================
def generate_thread_id():
    return str(uuid.uuid4())


def reset_chat():
    tid = generate_thread_id()
    st.session_state["thread_id"] = tid
    add_thread(tid)
    st.session_state["message_history"] = []


def add_thread(thread_id):
    tid = str(thread_id)
    if tid not in st.session_state["chat_threads"]:
        st.session_state["chat_threads"].append(tid)


def load_conversation(thread_id):
    state = chatbot.get_state(config={"configurable": {"thread_id": str(thread_id)}})
    return state.values.get("messages", [])


def file_icon(filetype):
    return "📝" if filetype == ".docx" else "📄"


def make_title(thread_id, titles):
    return titles.get(str(thread_id), f"Chat · {str(thread_id)[-8:]}")


def safe_md(text: str) -> str:
    """Escape $ so markdown doesn't swallow currency symbols."""
    return text.replace("$", "\\$") if text else ""


def get_pending_approval(config):
    """Return interrupt payload if graph is paused, else None."""
    try:
        state = chatbot.get_state(config=config)
        for task in state.tasks or []:
            for iv in getattr(task, "interrupts", None) or []:
                return iv.value
    except Exception:
        pass
    return None


# ======================= Session Init ===================
if "message_history" not in st.session_state:
    st.session_state["message_history"] = []
if "thread_id" not in st.session_state:
    st.session_state["thread_id"] = generate_thread_id()
if "chat_threads" not in st.session_state:
    st.session_state["chat_threads"] = [str(t) for t in retrieve_all_threads()]
if "ingested_docs" not in st.session_state:
    st.session_state["ingested_docs"] = {}
if "thread_titles" not in st.session_state:
    st.session_state["thread_titles"] = get_all_thread_titles()

add_thread(st.session_state["thread_id"])
thread_key = str(st.session_state["thread_id"])
thread_docs = st.session_state["ingested_docs"].setdefault(thread_key, {})

CONFIG = {
    "configurable": {"thread_id": thread_key},
    "metadata": {"thread_id": thread_key},
    "run_name": "chat_turn",
}

# ============================ Sidebar ============================
with st.sidebar:
    st.markdown(
        """
        <div class="brand-header">
            <div class="brand-icon">✦</div>
            <span class="brand-name">MCP Chat</span>
        </div>
    """,
        unsafe_allow_html=True,
    )

    st.button("＋  New chat", on_click=reset_chat, use_container_width=True)

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
        if st.button("🗑️  Remove document", use_container_width=True):
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

    st.markdown('<p class="section-label">Recent</p>', unsafe_allow_html=True)
    selected_thread = None
    titles = st.session_state["thread_titles"]
    threads = st.session_state["chat_threads"][::-1]

    if not threads:
        st.caption("No past conversations yet.")
    else:
        for tid in threads:
            title = make_title(str(tid), titles)
            meta = thread_document_metadata(str(tid))
            if thread_has_document(str(tid)):
                icon = file_icon(meta.get("filetype", ".pdf"))
                label = f"{icon}  {title}"
            else:
                label = f"💬  {title}"
            if str(tid) == thread_key:
                label = f"▶  {title}"
            if st.button(label, key=f"thread_{tid}", use_container_width=True):
                selected_thread = tid

# ============================ Main UI ============================
st.title("MCP + RAG Chatbot")

doc_meta = thread_document_metadata(thread_key)
if doc_meta:
    icon = file_icon(doc_meta.get("filetype", ".pdf"))
    st.caption(
        f"{icon} Active doc: **{doc_meta.get('filename')}** — "
        f"{doc_meta.get('chunks')} chunks, {doc_meta.get('documents')} pages"
    )

# Render history
for message in st.session_state["message_history"]:
    with st.chat_message(message["role"]):
        st.markdown(safe_md(message["content"]))

# ── Approval UI — shown when graph is paused ──
pending = get_pending_approval(CONFIG)
if pending:
    summary = pending.get("summary", "Proceed with this action?")
    tool_name = pending.get("tool_name", "action")

    st.markdown(
        f"""
        <div class="approval-card">
            ⚠️ <b>Approval needed</b><br><br>
            {summary.replace("$", "&#36;")}
        </div>
    """,
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns(2)

    with col1:
        if st.button("✅  Approve", use_container_width=True, key="approve_btn"):

            async def _approve():
                return await chatbot.ainvoke(
                    Command(resume={"approved": True}), config=CONFIG
                )

            result = run_async(_approve())
            # Pick up final assistant message after approval
            if result and result.get("messages"):
                for msg in reversed(result["messages"]):
                    if isinstance(msg, AIMessage) and msg.content:
                        st.session_state["message_history"].append(
                            {"role": "assistant", "content": msg.content}
                        )
                        break
            st.rerun()

    with col2:
        if st.button("❌  Reject", use_container_width=True, key="reject_btn"):

            async def _reject():
                return await chatbot.ainvoke(
                    Command(resume={"approved": False}), config=CONFIG
                )

            result = run_async(_reject())
            if result and result.get("messages"):
                for msg in reversed(result["messages"]):
                    if isinstance(msg, AIMessage) and msg.content:
                        st.session_state["message_history"].append(
                            {"role": "assistant", "content": msg.content}
                        )
                        break
            st.rerun()

# ── Chat input ──
user_input = st.chat_input("Ask anything — search, math, expenses, or your document…")

if user_input:
    titles = st.session_state["thread_titles"]
    if thread_key not in titles:
        title = user_input[:40] + ("…" if len(user_input) > 40 else "")
        save_thread_title(thread_key, title)
        st.session_state["thread_titles"][thread_key] = title

    st.session_state["message_history"].append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(safe_md(user_input))

    with st.chat_message("assistant"):
        status_holder = {"box": None}

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
                        yield f"⚠️ Something went wrong.\n\n`{err_str[:200]}`"
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

                if isinstance(message_chunk, AIMessage):
                    yield message_chunk.content

        ai_message = st.write_stream(ai_only_stream())

        if status_holder["box"] is not None:
            status_holder["box"].update(
                label="✅ Done", state="complete", expanded=False
            )

    st.session_state["message_history"].append(
        {"role": "assistant", "content": ai_message}
    )

    # Rerun if graph paused for approval
    if get_pending_approval(CONFIG):
        st.rerun()

# Thread switch
if selected_thread:
    st.session_state["thread_id"] = str(selected_thread)
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
            temp_messages.append({"role": role, "content": msg.content})
    st.session_state["message_history"] = temp_messages
    st.rerun()

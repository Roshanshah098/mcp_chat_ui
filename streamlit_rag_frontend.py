import queue
import uuid

import streamlit as st
from langraph_rag_backend import (
    chatbot,
    ingest_document,
    retrieve_all_threads,
    submit_async_task,
    thread_document_metadata,
    thread_has_document,
    SUPPORTED_EXTENSIONS,
)
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

# =========================== Page Config ===========================
st.set_page_config(
    page_title="MCP Chat",
    page_icon="💬",
    layout="centered",
)

# =========================== Custom CSS ===========================
st.markdown(
    """
    <style>
    [data-testid="stSidebar"] {
        background: #0f0f11;
        border-right: 1px solid #1e1e24;
    }
    [data-testid="stSidebar"] * { color: #e2e2e6 !important; }
    .brand-header {
        display: flex; align-items: center; gap: 10px;
        padding: 4px 0 20px 0;
        border-bottom: 1px solid #1e1e24;
        margin-bottom: 18px;
    }
    .brand-icon {
        width: 32px; height: 32px;
        background: linear-gradient(135deg, #6366f1, #8b5cf6);
        border-radius: 8px;
        display: flex; align-items: center; justify-content: center;
        font-size: 16px;
    }
    .brand-name {
        font-size: 17px; font-weight: 700;
        letter-spacing: -0.3px; color: #f1f1f3 !important;
    }
    .section-label {
        font-size: 10px; font-weight: 700;
        letter-spacing: 1.2px; text-transform: uppercase;
        color: #555568 !important; margin: 18px 0 8px 2px;
    }
    .doc-badge {
        background: #1a1a2e; border: 1px solid #6366f1;
        border-radius: 8px; padding: 8px 10px;
        font-size: 12px; margin: 8px 0;
        color: #a5b4fc !important;
    }
    [data-testid="stSidebar"] [data-testid="stButton"]:first-of-type button {
        background: #6366f1 !important; color: #fff !important;
        border: none !important; border-radius: 8px !important;
        font-weight: 600 !important; width: 100% !important;
        transition: background 0.2s !important;
    }
    [data-testid="stSidebar"] [data-testid="stButton"]:first-of-type button:hover {
        background: #4f46e5 !important;
    }
    [data-testid="stSidebar"] [data-testid="stButton"]:not(:first-of-type) button {
        background: transparent !important;
        border: 1px solid #1e1e24 !important;
        border-radius: 7px !important; color: #b0b0c0 !important;
        font-size: 13px !important; text-align: left !important;
        padding: 0.4rem 0.75rem !important; width: 100% !important;
        margin-bottom: 4px !important;
        transition: background 0.15s, border-color 0.15s !important;
    }
    [data-testid="stSidebar"] [data-testid="stButton"]:not(:first-of-type) button:hover {
        background: #18181f !important;
        border-color: #6366f1 !important; color: #e2e2f0 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# =========================== Utilities ===========================
def generate_thread_id():
    return uuid.uuid4()


def reset_chat():
    thread_id = generate_thread_id()
    st.session_state["thread_id"] = thread_id
    add_thread(thread_id)
    st.session_state["message_history"] = []


def add_thread(thread_id):
    if thread_id not in st.session_state["chat_threads"]:
        st.session_state["chat_threads"].append(thread_id)


def load_conversation(thread_id):
    state = chatbot.get_state(config={"configurable": {"thread_id": thread_id}})
    return state.values.get("messages", [])


def short_label(thread_id):
    return f"💬  Chat · {str(thread_id)[-8:]}"


def file_icon(filetype):
    return "📝" if filetype == ".docx" else "📄"


# ======================= Session Initialization ===================
if "message_history" not in st.session_state:
    st.session_state["message_history"] = []

if "thread_id" not in st.session_state:
    st.session_state["thread_id"] = generate_thread_id()

if "chat_threads" not in st.session_state:
    st.session_state["chat_threads"] = retrieve_all_threads()

if "ingested_docs" not in st.session_state:
    st.session_state["ingested_docs"] = {}

add_thread(st.session_state["thread_id"])

thread_key = str(st.session_state["thread_id"])
thread_docs = st.session_state["ingested_docs"].setdefault(thread_key, {})

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

    # Document section
    st.markdown('<p class="section-label">Document</p>', unsafe_allow_html=True)

    if thread_docs:
        latest_doc = list(thread_docs.values())[-1]
        icon = file_icon(latest_doc.get("filetype", ".pdf"))
        st.markdown(
            f"""
            <div class="doc-badge">
                {icon} <b>{latest_doc.get('filename')}</b><br>
                {latest_doc.get('chunks')} chunks · {latest_doc.get('documents')} pages
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.caption("No document uploaded for this chat yet.")

    # Accept both PDF and DOCX
    uploaded_file = st.file_uploader(
        "Upload PDF or DOCX",
        type=["pdf", "docx"],
        label_visibility="collapsed",
    )

    if uploaded_file:
        if uploaded_file.name in thread_docs:
            st.caption(f"`{uploaded_file.name}` already indexed.")
        else:
            with st.status("Indexing document…", expanded=True) as status_box:
                try:
                    summary = ingest_document(
                        uploaded_file.getvalue(),
                        thread_id=thread_key,
                        filename=uploaded_file.name,
                    )
                    thread_docs[uploaded_file.name] = summary
                    status_box.update(
                        label="✅ Document indexed", state="complete", expanded=False
                    )
                except ValueError as e:
                    status_box.update(label=f"❌ {e}", state="error", expanded=False)
            st.rerun()

    # Past conversations
    st.markdown('<p class="section-label">Recent</p>', unsafe_allow_html=True)

    selected_thread = None
    threads = st.session_state["chat_threads"][::-1]

    if not threads:
        st.caption("No past conversations yet.")
    else:
        for thread_id in threads:
            label = short_label(thread_id)
            meta = thread_document_metadata(str(thread_id))
            if thread_has_document(str(thread_id)):
                icon = file_icon(meta.get("filetype", ".pdf"))
                label = f"{icon}  Chat · {str(thread_id)[-8:]}"
            if st.button(label, key=f"thread_{thread_id}", use_container_width=True):
                selected_thread = thread_id

# ============================ Main UI ============================
st.title("MCP + RAG Chatbot")

doc_meta = thread_document_metadata(thread_key)
if doc_meta:
    icon = file_icon(doc_meta.get("filetype", ".pdf"))
    st.caption(
        f"{icon} Active doc: **{doc_meta.get('filename')}** — "
        f"{doc_meta.get('chunks')} chunks, {doc_meta.get('documents')} pages "
        f"(k={doc_meta.get('k')}, fetch_k={doc_meta.get('fetch_k')})"
    )

for message in st.session_state["message_history"]:
    with st.chat_message(message["role"]):
        st.text(message["content"])

user_input = st.chat_input("Ask anything — search, math, expenses, or your document…")

if user_input:
    st.session_state["message_history"].append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.text(user_input)

    CONFIG = {
        "configurable": {"thread_id": thread_key},
        "metadata": {"thread_id": thread_key},
        "run_name": "chat_turn",
    }

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
                        yield "⏳ I've hit my usage limit for now. Please try again in a little while."
                    elif (
                        "api_key" in err_str.lower() or "credentials" in err_str.lower()
                    ):
                        yield "🔑 API key missing or invalid. Please check your `.env` file."
                    elif (
                        "connection" in err_str.lower() or "timeout" in err_str.lower()
                    ):
                        yield "🌐 Connection issue. Please check your internet and try again."
                    else:
                        yield f"⚠️ Something went wrong. Please try again.\n\n`{err_str[:200]}`"
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

# Handle thread switch
if selected_thread:
    st.session_state["thread_id"] = selected_thread
    messages = load_conversation(selected_thread)
    temp_messages = []
    for msg in messages:
        role = "user" if isinstance(msg, HumanMessage) else "assistant"
        temp_messages.append({"role": role, "content": msg.content})
    st.session_state["message_history"] = temp_messages
    st.session_state["ingested_docs"].setdefault(str(selected_thread), {})
    st.rerun()

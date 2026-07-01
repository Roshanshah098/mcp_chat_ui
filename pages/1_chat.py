# =============================================================
# - MCP Chat Interface
# =============================================================
import queue
import re
import sqlite3
import sys
import uuid
import streamlit as st

st.set_page_config(page_title="MCP Chat", page_icon="💬", layout="wide")

# =============================================================
# CSS 
# =============================================================
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

html,body,[data-testid="stAppViewContainer"]{
    background:#080810!important;color:#e2e2f0;font-family:'Inter',sans-serif;
}
[data-testid="stHeader"]  {background:transparent!important;}
[data-testid="stToolbar"] {display:none;}

::-webkit-scrollbar{width:4px;}
::-webkit-scrollbar-track{background:#0d0d1a;}
::-webkit-scrollbar-thumb{background:#6366f1;border-radius:4px;}

[data-testid="stSidebar"] {
    width: 280px !important;
    min-width: 280px !important;
    max-width: 280px !important;
    margin-left: 0 !important;
    transform: none !important;
    transition: none !important;
    background: linear-gradient(180deg,#0a0a14 0%,#0d0d1a 100%) !important;
    border-right: 1px solid #1a1a2e !important;
    visibility: visible !important;
    opacity: 1 !important;
    display: block !important;
    position: relative !important;
    left: 0 !important;
}
[data-testid="stSidebar"] > div:first-child {
    width: 280px !important;
    margin-left: 0 !important;
    transform: none !important;
    position: relative !important;
    left: 0 !important;
}
[data-testid="stSidebar"] div {
    transform: none !important;
    transition: none !important;
}
[data-testid="stSidebar"] * {
    color: #e2e2f0 !important;
}
[data-testid="stSidebar"] [data-testid="stButton"] button {
    background: transparent !important;
    border: 1px solid #1e1e2e !important;
    border-radius: 10px !important;
    color: #c4c4d8 !important;
    font-size: 13px !important;
    text-align: left !important;
    padding: 9px 12px !important;
    transition: all .18s !important;
    width: 100% !important;
}
[data-testid="stSidebar"] [data-testid="stButton"] button:hover {
    background: rgba(99,102,241,.12) !important;
    border-color: #6366f1 !important;
    color: #a5b4fc !important;
}
[data-testid="stSidebarCollapseButton"] { display: none !important; }
[data-testid="stSidebarCollapsedControl"] { display: none !important; }
[data-testid="collapsedControl"] { display: none !important; }
button[kind="secondary"] [data-testid="stIcon"] { display: none !important; }

[data-testid="stAppViewContainer"] > section:first-child {
    margin-left: 0 !important;
}
[data-testid="stAppViewContainer"] > section:nth-child(2) {
    margin-left: 280px !important;
    max-width: calc(100% - 280px) !important;
}

.brand-wrap{padding:20px 4px 16px;border-bottom:1px solid #1a1a2e;margin-bottom:16px;}
.brand-row{display:flex;align-items:center;gap:10px;margin-bottom:4px;}
.brand-icon{width:36px;height:36px;background:linear-gradient(135deg,#6366f1,#8b5cf6);
  border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:17px;
  box-shadow:0 0 18px rgba(99,102,241,.4);}
.brand-name{font-size:16px;font-weight:700;color:#f1f1f3!important;letter-spacing:-.3px;}
.brand-tagline{font-size:10px;color:#454560!important;letter-spacing:.6px;margin-left:46px;}

.status-card{background:#0d0d1a;border:1px solid #1a1a2e;border-radius:12px;
  padding:11px 14px;margin-bottom:14px;}
.status-row{display:flex;align-items:center;gap:8px;font-size:11.5px;padding:3px 0;}
.status-dot{width:7px;height:7px;border-radius:50%;flex-shrink:0;}
.status-dot.ok  {background:#22c55e;box-shadow:0 0 6px rgba(34,197,94,.7);}
.status-dot.warn{background:#eab308;box-shadow:0 0 6px rgba(234,179,8,.7);}
.status-dot.bad {background:#ef4444;box-shadow:0 0 6px rgba(239,68,68,.7);}
.status-label   {color:#c4c4d8!important;}
.status-label b {color:#f1f1f3!important;}

.sec-label{font-size:9.5px;font-weight:700;letter-spacing:1.4px;text-transform:uppercase;
  color:#454560!important;margin:16px 2px 8px;display:flex;align-items:center;gap:6px;}
.sec-label::after{content:'';flex:1;height:1px;background:#1a1a2e;}

.new-chat-btn button{
    background:linear-gradient(135deg,#6366f1,#8b5cf6)!important;color:#fff!important;
    border:none!important;border-radius:10px!important;font-weight:600!important;
    font-size:13.5px!important;padding:10px!important;
    box-shadow:0 4px 16px rgba(99,102,241,.35)!important;width:100%!important;
}
.new-chat-btn button:hover{
    transform:translateY(-1px)!important;
    box-shadow:0 6px 22px rgba(99,102,241,.5)!important;
}

.doc-badge{background:linear-gradient(135deg,rgba(99,102,241,.1),rgba(139,92,246,.06));
  border:1px solid rgba(99,102,241,.35);border-radius:10px;padding:10px 12px;
  font-size:12px;margin:6px 0 10px;color:#a5b4fc!important;line-height:1.7;}
.doc-badge .doc-name{font-weight:600;color:#c4b5fd!important;}
.doc-badge .doc-meta{font-size:10.5px;color:#6366f1!important;margin-top:3px;}

.upload-hint{border:1.5px dashed #1e1e3a;border-radius:10px;padding:14px 12px;
  text-align:center;font-size:11.5px;color:#454560!important;margin-bottom:8px;
  background:rgba(99,102,241,.03);}
.upload-hint span{color:#6366f1!important;font-weight:600;}

.memory-wrap{background:linear-gradient(135deg,rgba(34,197,94,.07),rgba(16,185,129,.04));
  border:1px solid rgba(34,197,94,.25);border-radius:10px;padding:10px 12px;margin:6px 0;}
.memory-header{font-size:10.5px;font-weight:700;color:#4ade80!important;
  margin-bottom:7px;display:flex;align-items:center;gap:5px;}
.memory-item{font-size:11.5px;color:#86efac!important;padding:2px 0;line-height:1.55;
  display:flex;align-items:flex-start;gap:5px;}
.memory-dot{color:#22c55e!important;margin-top:1px;flex-shrink:0;}

.thread-active button{background:rgba(99,102,241,.15)!important;
  border-color:rgba(99,102,241,.5)!important;color:#a5b4fc!important;}

.approval-card{background:linear-gradient(135deg,rgba(234,179,8,.08),rgba(251,146,60,.05));
  border:1px solid rgba(234,179,8,.4);border-radius:12px;padding:16px 18px;margin:14px 0;}
.approval-title{font-size:12px;font-weight:700;color:#fbbf24;margin-bottom:8px;
  display:flex;align-items:center;gap:6px;}
.approval-body{font-size:13px;color:#e2e2f0;line-height:1.6;}

.chat-header{background:linear-gradient(135deg,rgba(99,102,241,.08),rgba(139,92,246,.04));
  border:1px solid #1a1a2e;border-radius:16px;padding:18px 24px;margin-bottom:20px;
  display:flex;align-items:center;justify-content:space-between;}
.chat-header-left{display:flex;align-items:center;gap:14px;}
.chat-header-icon{width:44px;height:44px;background:linear-gradient(135deg,#6366f1,#8b5cf6);
  border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:20px;
  box-shadow:0 0 22px rgba(99,102,241,.4);}
.chat-header-title{font-size:1.1rem;font-weight:700;color:#f1f1f3;letter-spacing:-.3px;}
.chat-header-sub{font-size:.74rem;color:#6b7280;margin-top:3px;}
.chat-header-badge{background:rgba(99,102,241,.12);border:1px solid rgba(99,102,241,.3);
  border-radius:20px;padding:5px 14px;font-size:11.5px;color:#a5b4fc;
  display:flex;align-items:center;gap:6px;}
.badge-dot{width:6px;height:6px;border-radius:50%;background:#22c55e;
  box-shadow:0 0 6px rgba(34,197,94,.8);animation:pulse-dot 2s infinite;}
@keyframes pulse-dot{0%,100%{opacity:1;}50%{opacity:.4;}}

.doc-active-banner{background:linear-gradient(135deg,rgba(99,102,241,.1),rgba(6,182,212,.06));
  border:1px solid rgba(99,102,241,.3);border-radius:10px;padding:9px 14px;margin-bottom:16px;
  display:flex;align-items:center;gap:10px;font-size:12.5px;color:#a5b4fc;}
.doc-active-banner b{color:#c4b5fd;}

.empty-chat{display:flex;flex-direction:column;align-items:center;justify-content:center;
  padding:50px 20px 20px;gap:18px;text-align:center;}
.empty-orb{width:76px;height:76px;background:linear-gradient(135deg,#6366f1,#8b5cf6);
  border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:32px;
  box-shadow:0 0 40px rgba(99,102,241,.3),0 0 80px rgba(99,102,241,.1);
  animation:orb-float 4s ease-in-out infinite;}
@keyframes orb-float{0%,100%{transform:translateY(0);}50%{transform:translateY(-8px);}}
.empty-title{font-size:1.35rem;font-weight:700;color:#f1f1f3;letter-spacing:-.3px;}
.empty-sub{font-size:.83rem;color:#6b7280;max-width:400px;line-height:1.7;}
.suggestion-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;
  width:100%;max-width:500px;margin-top:6px;}
.suggestion-chip{background:#0d0d1a;border:1px solid #1a1a2e;border-radius:10px;
  padding:12px 14px;font-size:12px;color:#9696b0;text-align:left;line-height:1.5;}
.suggestion-chip b{color:#e2e2f0;display:block;margin-bottom:2px;font-size:12.5px;}

[data-testid="stChatInput"]{background:#0d0d1a!important;
  border:1.5px solid #2a2a3e!important;border-radius:14px!important;}
[data-testid="stChatInput"]:focus-within{border-color:#6366f1!important;
  box-shadow:0 0 0 3px rgba(99,102,241,.15)!important;}
[data-testid="stChatInput"] textarea{background:transparent!important;color:#e2e2f0!important;
  font-family:'Inter',sans-serif!important;min-height:44px!important;
  max-height:120px!important;padding:10px 14px!important;font-size:14px!important;}
[data-testid="stChatInput"] textarea::placeholder{color:#454560!important;}
[data-testid="stChatInput"] button{
    background:linear-gradient(135deg,#6366f1,#8b5cf6)!important;
    border:none!important;border-radius:8px!important;
    width:34px!important;height:34px!important;
}

.loader-outer{
    position:fixed;top:0;left:0;right:0;bottom:0;
    background:#080810;
    display:flex;flex-direction:column;align-items:center;justify-content:center;
    gap:24px;z-index:9999;
}
.cube-scene{width:96px;height:96px;perspective:800px;}
.cube{width:100%;height:100%;position:relative;transform-style:preserve-3d;
  animation:cube-rotate 3.5s infinite linear;}
.cube-face{position:absolute;width:96px;height:96px;border-radius:8px;
  border:1px solid rgba(165,180,252,.3);box-shadow:inset 0 0 24px rgba(99,102,241,.2);}
.cube-face.front {background:linear-gradient(135deg,rgba(99,102,241,.7),rgba(139,92,246,.4));transform:translateZ(48px);}
.cube-face.back  {background:linear-gradient(135deg,rgba(139,92,246,.6),rgba(99,102,241,.3));transform:translateZ(-48px) rotateY(180deg);}
.cube-face.right {background:linear-gradient(135deg,rgba(6,182,212,.6),rgba(99,102,241,.3));transform:rotateY(90deg) translateZ(48px);}
.cube-face.left  {background:linear-gradient(135deg,rgba(99,102,241,.6),rgba(6,182,212,.3));transform:rotateY(-90deg) translateZ(48px);}
.cube-face.top   {background:linear-gradient(135deg,rgba(139,92,246,.7),rgba(6,182,212,.3));transform:rotateX(90deg) translateZ(48px);}
.cube-face.bottom{background:linear-gradient(135deg,rgba(6,182,212,.5),rgba(139,92,246,.3));transform:rotateX(-90deg) translateZ(48px);}
@keyframes cube-rotate{0%{transform:rotateX(0) rotateY(0);}100%{transform:rotateX(360deg) rotateY(360deg);}}

.loader-title{font-size:1.15rem;font-weight:700;color:#f1f1f3;text-align:center;
  letter-spacing:-.3px;}
.loader-sub{font-size:.82rem;color:#6b7280;text-align:center;margin-top:-8px;}

.loader-steps{position:relative;height:24px;width:360px;font-size:.8rem;
  color:#9696b0;text-align:center;}
.loader-steps span{position:absolute;left:0;right:0;opacity:0;
  animation:step-fade 10s infinite;}
.loader-steps span:nth-child(1){animation-delay:0s;}
.loader-steps span:nth-child(2){animation-delay:2.5s;}
.loader-steps span:nth-child(3){animation-delay:5s;}
.loader-steps span:nth-child(4){animation-delay:7.5s;}
@keyframes step-fade{
  0%{opacity:0;transform:translateY(5px);}
  5%{opacity:1;transform:translateY(0);}
  22%{opacity:1;}
  27%{opacity:0;transform:translateY(-4px);}
  100%{opacity:0;}
}

.loader-bar-wrap{width:300px;height:3px;background:#1a1a2e;border-radius:3px;overflow:hidden;}
.loader-bar{height:3px;border-radius:3px;
  background:linear-gradient(90deg,#6366f1,#8b5cf6,#06b6d4,#8b5cf6,#6366f1);
  background-size:200% 100%;
  animation:bar-shimmer 2s linear infinite;}
@keyframes bar-shimmer{0%{background-position:200% 0;}100%{background-position:-200% 0;}}

.loader-timer{font-size:.72rem;color:#454560;font-family:'JetBrains Mono',monospace;}

.loader-patience{font-size:.78rem;color:#6366f1;text-align:center;
  background:rgba(99,102,241,.08);border:1px solid rgba(99,102,241,.2);
  border-radius:10px;padding:8px 20px;margin-top:4px;}
</style>
""",
    unsafe_allow_html=True,
)

# ── First-load detection ──
_FIRST_LOAD = "lang_rag_backend" not in sys.modules

loader_slot = st.empty()
if _FIRST_LOAD:
    with loader_slot.container():
        st.markdown(
            """
        <div class="loader-outer" id="loader-outer">
          <div class="cube-scene">
            <div class="cube">
              <div class="cube-face front"></div>
              <div class="cube-face back"></div>
              <div class="cube-face right"></div>
              <div class="cube-face left"></div>
              <div class="cube-face top"></div>
              <div class="cube-face bottom"></div>
            </div>
          </div>
          <div class="loader-title">Booting up MCP Chat…</div>
          <div class="loader-sub">Loading models, memory, and tools</div>
          <div class="loader-steps">
            <span>🔑 &nbsp;Rotating in Groq API keys…</span>
            <span>🧠 &nbsp;Loading embedding model (MiniLM-L6-v2)…</span>
            <span>💾 &nbsp;Connecting short-term memory (PostgreSQL)…</span>
            <span>📚 &nbsp;Connecting long-term memory (LTM store)…</span>
          </div>
          <div class="loader-bar-wrap"><div class="loader-bar"></div></div>
          <div class="loader-timer" id="loader-timer">Elapsed: 0s</div>
          <div class="loader-patience">
            ⏳ &nbsp;First load takes 15–30 seconds — please keep patience!
          </div>
        </div>
        <script>
        (function() {
          var start = Date.now();
          var el = document.getElementById('loader-timer');
          if (!el) return;
          var interval = setInterval(function() {
            var s = Math.floor((Date.now() - start) / 1000);
            el.textContent = 'Elapsed: ' + s + 's';
            if (s > 120) clearInterval(interval);
          }, 1000);
        })();
        </script>
        """,
            unsafe_allow_html=True,
        )

# ── Heavy import ──
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
    _GROQ_KEYS,
    _pg_store,
    mcp_tools,
    mark_thread_deleted,
    get_thread_created_dates,
    record_thread_created,
    generate_blog,
)
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

if "system_status" not in st.session_state:
    st.session_state["system_status"] = {
        "groq_keys": len(_GROQ_KEYS),
        "stm_ok": checkpointer is not None,
        "ltm_ok": _pg_store is not None,
        "mcp_tools": len(mcp_tools),
    }

if _FIRST_LOAD:
    loader_slot.empty()
    _s = st.session_state["system_status"]
    st.toast(
        f"✅ {_s['groq_keys']} key(s) · "
        f"STM {'✓' if _s['stm_ok'] else '✗'} · "
        f"LTM {'✓' if _s['ltm_ok'] else '✗'} · "
        f"{_s['mcp_tools']} MCP tools",
        icon="🚀",
    )

# =============================================================
# UTILITIES
# =============================================================
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


def _is_non_english(text):
    lower = text.lower()
    if any(p in lower for p in _ENGLISH_OVERRIDES):
        return False
    return bool(re.search(r"[\u0900-\u097F]", text)) or any(
        t in lower for t in _ROMANIZED_TRIGGERS
    )


def _extract_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            b.get("text", "") if isinstance(b, dict) else str(b) for b in content
        )
    return str(content) if content else ""


def _strip_function_calls(content):
    text = _extract_text(content)
    if not text:
        return ""
    text = re.sub(r"<function=[^>]*>.*?</function>", "", text, flags=re.DOTALL)
    text = re.sub(r"<function=[^>]*>\{[^<]*\}", "", text, flags=re.DOTALL)
    return re.sub(r"</function>", "", text).strip()


def generate_thread_id():
    return str(uuid.uuid4())


def _set_active_thread(tid: str):
    tid = str(tid)
    st.session_state["thread_id"] = tid
    _add_thread_to_front(tid)


def reset_chat():
    tid = generate_thread_id()
    _set_active_thread(tid)
    st.session_state["message_history"] = []
    st.session_state.setdefault("loaded_threads", set()).add(tid)
    record_thread_created(tid)


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
    except Exception as e:
        print(f"[Chat] checkpointer delete failed for {tid}: {e}")
    mark_thread_deleted(tid)
    threads = st.session_state.get("chat_threads", [])
    if tid in threads:
        threads.remove(tid)
    st.session_state["chat_threads"] = threads
    st.session_state["thread_titles"].pop(tid, None)
    st.session_state.get("saved_histories", {}).pop(tid, None)
    if st.session_state.get("thread_id") == tid:
        reset_chat()


def file_icon(ft):
    return "📝" if ft == ".docx" else "📄"


def make_title(tid, titles):
    return titles.get(str(tid), f"Chat · {str(tid)[-8:]}")


def safe_md(text):
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


# =============================================================
# SESSION STATE
# =============================================================
if "chat_threads" not in st.session_state:
    st.session_state["chat_threads"] = list(retrieve_all_threads())
if "ingested_docs" not in st.session_state:
    st.session_state["ingested_docs"] = {}
if "thread_titles" not in st.session_state:
    st.session_state["thread_titles"] = get_all_thread_titles()
if "loaded_threads" not in st.session_state:
    st.session_state["loaded_threads"] = set()
if "message_history" not in st.session_state:
    st.session_state["message_history"] = []

if "thread_id" not in st.session_state:
    st.session_state["thread_id"] = generate_thread_id()

_add_thread_to_front(st.session_state["thread_id"])
thread_key = str(st.session_state["thread_id"])
thread_docs = st.session_state["ingested_docs"].setdefault(thread_key, {})
CONFIG = {
    "configurable": {"thread_id": thread_key, "user_id": USER_ID},
    "metadata": {"thread_id": thread_key},
    "run_name": "chat_turn",
}

# Auto-restore messages on first visit to a thread
if thread_key not in st.session_state["loaded_threads"]:
    record_thread_created(thread_key)
    try:
        raw_msgs = load_conversation(thread_key)
        if raw_msgs:
            restored = []
            for msg in raw_msgs:
                if isinstance(msg, HumanMessage):
                    role = "user"
                elif isinstance(msg, AIMessage):
                    role = "assistant"
                else:
                    continue
                if msg.content:
                    text = _strip_function_calls(msg.content)
                    if text:
                        restored.append({"role": role, "content": text})
            if restored:
                st.session_state["message_history"] = restored
    except Exception as _e:
        print(f"[Chat] restore error: {_e}")

    _doc_meta_check = thread_document_metadata(thread_key)
    if _doc_meta_check:
        st.toast(
            f"📄 \"{_doc_meta_check.get('filename','your document')}\" is still "
            f"attached to this conversation — ask away.",
            icon="📎",
        )

    st.session_state["loaded_threads"].add(thread_key)

# =============================================================
# SIDEBAR
# =============================================================
selected_thread = None
with st.sidebar:
    st.markdown(
        """
    <div class="brand-wrap">
      <div class="brand-row">
        <div class="brand-icon">✦</div>
        <div><div class="brand-name">MCP Chat</div></div>
      </div>
      <div class="brand-tagline">AI · Memory · RAG · Multi-tool</div>
    </div>""",
        unsafe_allow_html=True,
    )

    _s = st.session_state["system_status"]
    kd = "ok" if _s["groq_keys"] > 1 else ("warn" if _s["groq_keys"] == 1 else "bad")
    st.markdown(
        f"""
    <div class="status-card">
      <div class="status-row"><span class="status-dot {kd}"></span>
        <span class="status-label"><b>{_s['groq_keys']}</b> Groq key(s) loaded</span></div>
      <div class="status-row"><span class="status-dot {'ok' if _s['stm_ok'] else 'bad'}"></span>
        <span class="status-label">STM — <b>{'connected' if _s['stm_ok'] else 'unavailable'}</b></span></div>
      <div class="status-row"><span class="status-dot {'ok' if _s['ltm_ok'] else 'bad'}"></span>
        <span class="status-label">LTM — <b>{'connected' if _s['ltm_ok'] else 'unavailable'}</b></span></div>
      <div class="status-row"><span class="status-dot {'ok' if _s['mcp_tools']>0 else 'warn'}"></span>
        <span class="status-label"><b>{_s['mcp_tools']}</b> MCP tool(s) active</span></div>
    </div>""",
        unsafe_allow_html=True,
    )

    st.page_link("app.py", label="📊  Back to Dashboard")
    st.page_link("pages/2_Blog.py", label="📝  Blog Generator")
    st.markdown("<div style='margin-bottom:8px'></div>", unsafe_allow_html=True)

    st.markdown('<div class="new-chat-btn">', unsafe_allow_html=True)
    st.button(
        "＋  New conversation",
        on_click=reset_chat,
        width="stretch",
        key="new_conversation_btn",
    )
    st.markdown("</div>", unsafe_allow_html=True)

    # Document
    st.markdown('<div class="sec-label">📄 Document</div>', unsafe_allow_html=True)
    doc_meta = thread_document_metadata(thread_key)
    if doc_meta:
        icon = file_icon(doc_meta.get("filetype", ".pdf"))
        st.markdown(
            f"""
        <div class="doc-badge">
          <div class="doc-name">{icon} {doc_meta.get('filename')}</div>
          <div class="doc-meta">{doc_meta.get('chunks')} chunks · {doc_meta.get('documents')} pages · {doc_meta.get('filetype','').upper().lstrip('.')}</div>
        </div>""",
            unsafe_allow_html=True,
        )
        if st.button("🗑️  Remove document", width="stretch", key="remove_doc_btn"):
            remove_document(thread_key)
            st.rerun()
    else:
        st.markdown(
            '<div class="upload-hint"><span>↑ Drop a file here</span><br>PDF or DOCX</div>',
            unsafe_allow_html=True,
        )
        uploaded_file = st.file_uploader(
            "Upload", type=["pdf", "docx"], label_visibility="collapsed"
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

    # Memory
    st.markdown('<div class="sec-label">🧠 My Memory</div>', unsafe_allow_html=True)
    try:
        memories = get_user_memories(USER_ID)
    except Exception as _e:
        print(f"[Chat] get_user_memories failed: {_e}")
        memories = []
    if memories:
        items_html = "".join(
            f'<div class="memory-item"><span class="memory-dot">▸</span>{m}</div>'
            for m in memories
        )
        st.markdown(
            f'<div class="memory-wrap"><div class="memory-header">🧠 What I remember about you</div>'
            f"{items_html}</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div style="font-size:11.5px;color:#454560;padding:8px 4px;line-height:1.6">'
            "💡 Tell me your name, what you're working on, or your preferences.</div>",
            unsafe_allow_html=True,
        )

    # Blog Generator in Sidebar
    st.markdown('<div class="sec-label">📝 Blog</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="upload-hint"><span>Generate a blog</span><br>AI-powered research & writing with free images</div>',
        unsafe_allow_html=True,
    )
    blog_topic_input = st.text_input(
        "Topic",
        placeholder="e.g., Latest AI trends...",
        key="chat_sidebar_blog_topic",
        label_visibility="collapsed",
    )
    if st.button("✨ Generate Blog", width="stretch", key="generate_blog_btn_sidebar"):
        if blog_topic_input.strip():
            # FIXED: Updated spinner to reflect new image hierarchy
            with st.spinner(
                "Researching and writing... (images: HF FLUX.1-schnell → HF Providers fallback)"
            ):
                try:
                    blog_md = generate_blog(topic=blog_topic_input.strip())
                    st.session_state["last_blog"] = blog_md
                    st.session_state["last_blog_topic"] = blog_topic_input.strip()
                    st.toast("✅ Blog generated! Check the Blog page.", icon="📝")
                except Exception as e:
                    st.error(f"Blog generation failed: {e}")
        else:
            st.warning("Please enter a topic first.")

    # Recent threads
    st.markdown('<div class="sec-label">🕐 Recent</div>', unsafe_allow_html=True)
    titles = st.session_state["thread_titles"]
    threads = st.session_state["chat_threads"]
    if not threads:
        st.markdown(
            '<div style="font-size:11.5px;color:#454560;padding:4px">No conversations yet.</div>',
            unsafe_allow_html=True,
        )
    else:
        ordered = list(threads[:30])
        date_labels = {}
        try:
            from datetime import (
                datetime as _dt,
                timedelta as _timedelta,
                timezone as _timezone,
            )

            created_dates = get_thread_created_dates() or {}
            today = _dt.now(_timezone.utc).date()
            yesterday = today - _timedelta(days=1)

            def _date_label(tid: str) -> str:
                iso = created_dates.get(tid)
                if not iso:
                    return "Earlier"
                try:
                    d = _dt.fromisoformat(iso).date()
                except Exception:
                    return "Earlier"
                if d == today:
                    return "Today"
                if d == yesterday:
                    return "Yesterday"
                return d.strftime("%b %d")

            def _sort_key(tid: str):
                return created_dates.get(tid, "")

            ordered = sorted(threads[:30], key=_sort_key, reverse=True)
            date_labels = {str(t): _date_label(str(t)) for t in ordered}
        except Exception as _e:
            print(f"[Chat] date-grouping failed, showing flat list: {_e}")
            date_labels = {}

        last_label = None
        for tid in ordered:
            tid = str(tid)
            label = date_labels.get(tid)
            if label and label != last_label:
                st.markdown(
                    f'<div style="font-size:9.5px;font-weight:700;letter-spacing:1px;'
                    f'text-transform:uppercase;color:#454560;margin:10px 2px 4px">{label}</div>',
                    unsafe_allow_html=True,
                )
                last_label = label

            title = make_title(tid, titles)
            meta = thread_document_metadata(tid)
            is_active = tid == thread_key
            prefix = (
                (file_icon(meta.get("filetype", ".pdf")) + " ")
                if thread_has_document(tid)
                else "💬 "
            )
            display = f"▶  {title}" if is_active else f"{prefix}{title}"
            c1, c2 = st.columns([9, 1])
            with c1:
                if is_active:
                    st.markdown('<div class="thread-active">', unsafe_allow_html=True)
                if st.button(display, key=f"thread_{tid}", width="stretch"):
                    selected_thread = tid
                if is_active:
                    st.markdown("</div>", unsafe_allow_html=True)
            with c2:
                if st.button("✕", key=f"del_{tid}", help="Delete"):
                    delete_thread(tid)
                    st.rerun()

# =============================================================
# MAIN AREA
# =============================================================
user_input = st.chat_input(
    "Message MCP Chat… (search, math, expenses, or ask about your doc)"
)

_, main_col, _ = st.columns([1, 10, 1])
with main_col:
    doc_meta = thread_document_metadata(thread_key)
    _s = st.session_state["system_status"]

    st.markdown(
        f"""
    <div class="chat-header">
      <div class="chat-header-left">
        <div class="chat-header-icon">✦</div>
        <div>
          <div class="chat-header-title">MCP + RAG Chatbot</div>
          <div class="chat-header-sub">Search · Math · Expenses · Documents · Memory · Multilingual</div>
        </div>
      </div>
      <div class="chat-header-badge">
        <div class="badge-dot"></div>
        {_s['groq_keys']} key(s) &nbsp;·&nbsp; {_s['mcp_tools']} tools active
      </div>
    </div>""",
        unsafe_allow_html=True,
    )

    if doc_meta:
        icon = file_icon(doc_meta.get("filetype", ".pdf"))
        st.markdown(
            f"""
        <div class="doc-active-banner">
          {icon}
          <div><b>{doc_meta.get('filename')}</b> is active —
          {doc_meta.get('chunks')} chunks · ask me anything about it</div>
        </div>""",
            unsafe_allow_html=True,
        )

    msgs = st.session_state["message_history"]
    if not msgs:
        st.markdown(
            """
        <div class="empty-chat">
          <div class="empty-orb">✦</div>
          <div class="empty-title">What can I help you with?</div>
          <div class="empty-sub">Search the web, do math, track expenses, ask about your documents, or just chat — in English or Nepali.</div>
          <div class="suggestion-grid">
            <div class="suggestion-chip"><b>🔍 Web Search</b>What's the latest news on AI today?</div>
            <div class="suggestion-chip"><b>💸 Expenses</b>Add expense of $50 for groceries today</div>
            <div class="suggestion-chip"><b>📈 Stocks</b>What's the current price of AAPL?</div>
            <div class="suggestion-chip"><b>🔢 Math</b>Calculate 15% tip on an $84 dinner</div>
          </div>
        </div>""",
            unsafe_allow_html=True,
        )
    else:
        for message in msgs:
            with st.chat_message(message["role"]):
                st.markdown(safe_md(message["content"]))

    pending = get_pending_approval(CONFIG)
    if pending:
        action_summary = pending.get("summary", "Proceed with this action?")
        st.markdown(
            f"""
        <div class="approval-card">
          <div class="approval-title">⚠️ Approval Required</div>
          <div class="approval-body">{action_summary.replace("$","$")}</div>
        </div>""",
            unsafe_allow_html=True,
        )
        ac1, ac2, _ = st.columns([2, 2, 6])
        with ac1:
            if st.button(
                "✅ Approve", width="stretch", key="approve_btn", type="primary"
            ):

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
        with ac2:
            if st.button("❌ Reject", width="stretch", key="reject_btn"):

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

# =============================================================
# HANDLE USER INPUT
# =============================================================
if user_input:
    titles = st.session_state["thread_titles"]
    if thread_key not in titles:
        title = user_input[:40] + ("…" if len(user_input) > 40 else "")
        save_thread_title(thread_key, title)
        st.session_state["thread_titles"][thread_key] = title
        record_thread_created(thread_key)

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
            eq: queue.Queue = queue.Queue()

            async def run_stream():
                try:
                    async for chunk, meta in chatbot.astream(
                        {"messages": [HumanMessage(content=user_input)]},
                        config=CONFIG,
                        stream_mode="messages",
                    ):
                        eq.put((chunk, meta))
                except Exception as exc:
                    eq.put(("error", exc))
                finally:
                    eq.put(None)

            submit_async_task(run_stream())
            while True:
                item = eq.get()
                if item is None:
                    break
                chunk, meta = item
                if chunk == "error":
                    err = str(meta)
                    import traceback

                    print(f"\n[CHAT ERROR] {repr(meta)}", flush=True)
                    if hasattr(meta, "__traceback__"):
                        traceback.print_tb(meta.__traceback__)
                    stream_error["value"] = err
                    if "rate_limit_exceeded" in err or "429" in err:
                        yield "⏳ All API keys are rate-limited. Please wait a few minutes."
                    elif "api_key" in err.lower() or "credentials" in err.lower():
                        yield "🔑 API key missing. Check your `.env` file."
                    elif "connection" in err.lower() or "timeout" in err.lower():
                        yield "🌐 Connection issue. Check your internet."
                    else:
                        yield f"⚠️ Something went wrong.\n\n`{err[:500]}`"
                    return
                if isinstance(chunk, ToolMessage):
                    tn = getattr(chunk, "name", "tool")
                    if status_holder["box"] is None:
                        status_holder["box"] = st.status(
                            f"🔧 Using `{tn}`…", expanded=True
                        )
                    else:
                        status_holder["box"].update(
                            label=f"🔧 Using `{tn}`…", state="running", expanded=True
                        )
                node = meta.get("langgraph_node", "") if isinstance(meta, dict) else ""
                if (
                    isinstance(chunk, AIMessage)
                    and node == "chat_node"
                    and not getattr(chunk, "tool_calls", [])
                    and chunk.content
                ):
                    raw = chunk.content
                    ct = (
                        raw
                        if isinstance(raw, str)
                        else (
                            "".join(
                                b.get("text", "") if isinstance(b, dict) else str(b)
                                for b in raw
                            )
                            if isinstance(raw, list)
                            else str(raw) if raw else ""
                        )
                    )
                    if ct:
                        streamed_chunks.append(ct)
                        yield ct

        st.write_stream(ai_only_stream())
        if status_holder["box"] is not None:
            status_holder["box"].update(
                label="✅ Done", state="complete", expanded=False
            )

    if not stream_error["value"]:
        if needs_translation:
            gs = chatbot.get_state(config=CONFIG)
            amsgs = gs.values.get("messages", [])
            fai = next(
                (m for m in reversed(amsgs) if isinstance(m, AIMessage) and m.content),
                None,
            )
            if fai:
                ft = _strip_function_calls(fai.content)
                if ft:
                    st.session_state["message_history"].append(
                        {"role": "assistant", "content": ft}
                    )
        else:
            streamed_text = _strip_function_calls("".join(streamed_chunks)).strip()
            if streamed_text:
                st.session_state["message_history"].append(
                    {"role": "assistant", "content": streamed_text}
                )

    if get_pending_approval(CONFIG):
        st.rerun()

# =============================================================
# THREAD SWITCH
# =============================================================
if selected_thread:
    selected_thread = str(selected_thread)
    st.session_state.setdefault("saved_histories", {})[thread_key] = list(
        st.session_state["message_history"]
    )
    _set_active_thread(selected_thread)

    if selected_thread in st.session_state.get("saved_histories", {}):
        st.session_state["message_history"] = st.session_state["saved_histories"][
            selected_thread
        ]
        st.session_state.setdefault("loaded_threads", set()).add(selected_thread)
        st.rerun()

    messages = load_conversation(selected_thread)
    temp = []
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
                temp.append({"role": role, "content": text})
    st.session_state["message_history"] = temp
    st.session_state.setdefault("loaded_threads", set()).add(selected_thread)
    st.rerun()

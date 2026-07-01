from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Send
from typing import TypedDict, Annotated, Optional, Dict, Any
from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    SystemMessage,
    AIMessage,
    RemoveMessage,
)
from langchain_groq import ChatGroq
from langchain_huggingface import HuggingFaceEmbeddings
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langchain_community.tools import DuckDuckGoSearchRun
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader
from langchain_community.vectorstores import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.tools import tool, BaseTool
from langchain_core.runnables import RunnableConfig
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.store.base import BaseStore
from dotenv import load_dotenv

from memory_checkpointer import init_stm, init_ltm, _loop as _ASYNC_LOOP
from memory_store import LongTermMemory
from translation_subgraph import run_translation

import asyncio
import gc
import itertools
import shutil
import sqlite3
import requests
import tempfile
import time
import json
import re
import os
import base64
import urllib.parse
import random
from datetime import datetime, timezone, date, timedelta
from pathlib import Path
from urllib.parse import quote, urlparse

load_dotenv(override=True)

os.environ["TRANSFORMERS_VERBOSITY"] = "error"
os.environ["TOKENIZERS_PARALLELISM"] = "false"


# =============================================================
# BLOG OUTPUT DIRECTORIES
# =============================================================
BLOG_OUTPUT_DIR = Path(os.environ.get("BLOG_OUTPUT_DIR", "blogs"))
BLOG_IMAGES_DIR = BLOG_OUTPUT_DIR / "images"
BLOG_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
BLOG_IMAGES_DIR.mkdir(parents=True, exist_ok=True)


# =============================================================
# ASYNC HELPERS
# =============================================================
def _submit_async(coro):
    return asyncio.run_coroutine_threadsafe(coro, _ASYNC_LOOP)


def run_async(coro):
    return _submit_async(coro).result()


def submit_async_task(coro):
    return _submit_async(coro)


# =============================================================
# LLM + EMBEDDINGS (MULTI-KEY ROTATION)
# =============================================================
_RAW_KEYS = os.getenv("GROQ_API_KEYS", os.getenv("GROQ_API_KEY", ""))
_GROQ_KEYS: list[str] = [k.strip() for k in _RAW_KEYS.split(",") if k.strip()]

if not _GROQ_KEYS:
    raise EnvironmentError(
        "No Groq API key found. Set GROQ_API_KEYS or GROQ_API_KEY in your .env file."
    )

print(f"[Groq] Loaded {len(_GROQ_KEYS)} API key(s) for rotation.")

_chat_key_cycle = itertools.cycle(_GROQ_KEYS)
_mem_key_cycle = itertools.cycle(_GROQ_KEYS)
_blog_key_cycle = itertools.cycle(_GROQ_KEYS)

_GROQ_MODEL = "llama-3.3-70b-versatile"
_RATE_LIMIT_CODES = {"rate_limit_exceeded", "429"}


def _make_chat_llm(temperature: float = 0.3) -> ChatGroq:
    return ChatGroq(
        model=_GROQ_MODEL,
        temperature=temperature,
        api_key=next(_chat_key_cycle),
    )


def _make_mem_llm(temperature: float = 0) -> ChatGroq:
    return ChatGroq(
        model=_GROQ_MODEL,
        temperature=temperature,
        api_key=next(_mem_key_cycle),
    )


def _make_blog_llm(temperature: float = 0.4) -> ChatGroq:
    return ChatGroq(
        model=_GROQ_MODEL,
        temperature=temperature,
        api_key=next(_blog_key_cycle),
    )


def _is_rate_limit(exc: Exception) -> bool:
    msg = str(exc).lower()
    return (
        "rate_limit_exceeded" in msg
        or '"code": "rate_limit_exceeded"' in msg
        or "429" in msg
    )


async def _invoke_with_fallback(messages, config=None, tools_bound_llm=None):
    """Try every available key. On rate-limit, rotate to next key."""
    tried = 0
    last_exc = None
    total = len(_GROQ_KEYS)

    while tried < total:
        try:
            candidate = tools_bound_llm or _make_chat_llm()
            if config:
                return await candidate.ainvoke(messages, config=config)
            return await candidate.ainvoke(messages)
        except Exception as exc:
            if _is_rate_limit(exc):
                tried += 1
                last_exc = exc
                key_preview = _GROQ_KEYS[(tried - 1) % total][:8]
                print(
                    f"[Groq] Rate limit on key …{key_preview} "
                    f"({tried}/{total}), rotating…"
                )
            else:
                raise

    print("[Groq] All keys exhausted — raising last rate-limit error.")
    raise last_exc


async def _invoke_blog_with_fallback(messages, config=None, tools_bound_llm=None):
    """Blog-specific key rotation."""
    tried = 0
    last_exc = None
    total = len(_GROQ_KEYS)
    while tried < total:
        try:
            candidate = tools_bound_llm or _make_blog_llm()
            if config:
                return await candidate.ainvoke(messages, config=config)
            return await candidate.ainvoke(messages)
        except Exception as exc:
            if _is_rate_limit(exc):
                tried += 1
                last_exc = exc
                print(f"[Blog/Groq] Rate limit ({tried}/{total}), rotating…")
            else:
                raise
    raise last_exc


def _invoke_blog_sync_with_fallback(messages, config=None):
    """SYNC blog LLM call with key rotation + exponential backoff on rate limits.

    CRITICAL: Groq rate limits are per-organization, not per-key.
    Key rotation alone does NOT avoid rate limits.
    We MUST add exponential backoff with sleep.
    """
    tried = 0
    last_exc = None
    total = len(_GROQ_KEYS)

    while tried < total:
        try:
            candidate = _make_blog_llm()
            if config:
                return candidate.invoke(messages, config=config)
            return candidate.invoke(messages)
        except Exception as exc:
            if _is_rate_limit(exc):
                tried += 1
                last_exc = exc
                # Exponential backoff: 2s, 4s, 8s, ... capped at 30s
                wait = min(2**tried, 30)
                key_preview = _GROQ_KEYS[(tried - 1) % total][:8]
                print(
                    f"[Blog/Groq] Rate limit on key …{key_preview} "
                    f"({tried}/{total}), backing off {wait}s…"
                )
                time.sleep(wait)
            else:
                raise

    # All keys exhausted with backoff - try one more time with longest wait
    print(f"[Blog/Groq] All keys exhausted, final retry after 15s...")
    time.sleep(15)
    try:
        return _make_blog_llm().invoke(messages, config=config)
    except Exception as e:
        raise last_exc if last_exc else e


# Initial LLM instances
llm = _make_chat_llm(temperature=0.3)
memory_llm = _make_mem_llm(temperature=0)
blog_llm = _make_blog_llm(temperature=0.4)
embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")


# =============================================================
# MEMORY INIT
# =============================================================
checkpointer = init_stm()
_pg_store = init_ltm()
ltm = LongTermMemory(
    llm=memory_llm,
    key_factory=_make_mem_llm,
    max_retries=len(_GROQ_KEYS),
)


# =============================================================
#  SYSTEM PROMPT
# =============================================================
SYSTEM_PROMPT = """You are a helpful friendly assistant with memory capabilities.
{user_context}

Tools: search_tool, get_stock_price, calculator, add_expense, list_expenses,
       edit_expense, delete_expense, add_credit, list_credits, summarize{rag_context}

Rules:
- ONE tool call at a time
- If user mentions multiple expenses, add them one by one across turns
- For edit/delete call list_expenses first to find the id
- If no date mentioned use today's date
- Never show raw JSON
- Be concise and friendly
- If you know the user's name address them naturally
- Always respond in English internally
- ONLY call a tool when the user EXPLICITLY requests it
- NEVER call tools during greetings, casual chat, emotional support
- If unsure whether to call a tool — do NOT call it. Just talk.
"""


# =============================================================
#  DOCUMENT STORE (SQLITE + CHROMADB — PER-THREAD RAG)
# =============================================================
_THREAD_RETRIEVERS: Dict[str, Any] = {}
_THREAD_METADATA: Dict[str, dict] = {}
_THREAD_VECTORSTORES: Dict[str, Any] = {}
SUPPORTED_EXTENSIONS = {".pdf", ".docx"}
DOC_DB = "chatbot.db"
CHROMA_BASE_DIR = "./chroma_db"
APPROVAL_REQUIRED = {"add_expense", "edit_expense", "delete_expense", "add_credit"}
STM_SUMMARIZE_AFTER = 10


def _doc_db_conn():
    conn = sqlite3.connect(DOC_DB, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS thread_documents (
            thread_id  TEXT PRIMARY KEY,
            filename   TEXT NOT NULL,
            filetype   TEXT NOT NULL,
            metadata   TEXT NOT NULL,
            file_blob  BLOB NOT NULL
        )
    """)
    conn.commit()
    return conn


_doc_conn = _doc_db_conn()


def _save_doc_to_db(thread_id, filename, filetype, metadata, file_bytes):
    _doc_conn.execute(
        "INSERT OR REPLACE INTO thread_documents "
        "(thread_id,filename,filetype,metadata,file_blob) VALUES (?,?,?,?,?)",
        (thread_id, filename, filetype, json.dumps(metadata), file_bytes),
    )
    _doc_conn.commit()


def _delete_doc_from_db(thread_id):
    _doc_conn.execute("DELETE FROM thread_documents WHERE thread_id=?", (thread_id,))
    _doc_conn.commit()


def _load_all_docs_from_db():
    rows = _doc_conn.execute(
        "SELECT thread_id, filename, filetype, metadata, file_blob FROM thread_documents"
    ).fetchall()
    for tid, fname, ftype, meta_json, fbytes in rows:
        try:
            _rebuild_retriever(tid, fname, ftype, fbytes, json.loads(meta_json))
        except Exception as e:
            print(f"[warn] Could not reload doc for thread {tid}: {e}")


def _release_chroma(thread_id: str):
    old_vs = _THREAD_VECTORSTORES.pop(thread_id, None)
    if old_vs is not None:
        try:
            old_vs._client._system.stop()
        except Exception:
            pass
        try:
            old_vs._client.reset()
        except Exception:
            pass
        del old_vs
    gc.collect()


def _safe_rmtree(path: str, retries: int = 3, delay: float = 0.4):
    for attempt in range(retries):
        try:
            shutil.rmtree(path)
            return
        except PermissionError:
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                shutil.rmtree(path, ignore_errors=True)


def _rebuild_retriever(thread_id, filename, filetype, file_bytes, meta):
    with tempfile.NamedTemporaryFile(delete=False, suffix=filetype) as f:
        f.write(file_bytes)
        temp_path = f.name
    try:
        loader = (
            PyPDFLoader(temp_path) if filetype == ".pdf" else Docx2txtLoader(temp_path)
        )
        docs = loader.load()
        for doc in docs:
            text = re.sub(r"\n{3,}", "\n\n", doc.page_content)
            doc.page_content = "\n".join(
                line.strip() for line in text.splitlines()
            ).strip()
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=meta.get("chunk_size", 1000),
            chunk_overlap=meta.get("chunk_overlap", 200),
            separators=["\n\n", "\n", " ", ""],
        )
        chunks = splitter.split_documents(docs)
        persist_dir = os.path.join(CHROMA_BASE_DIR, str(thread_id))
        vs = Chroma.from_documents(
            chunks,
            embeddings,
            persist_directory=persist_dir,
        )
        retr = vs.as_retriever(
            search_type="mmr",
            search_kwargs={"k": meta.get("k", 4), "fetch_k": meta.get("fetch_k", 20)},
        )
        _THREAD_VECTORSTORES[str(thread_id)] = vs
        _THREAD_RETRIEVERS[str(thread_id)] = retr
        _THREAD_METADATA[str(thread_id)] = meta
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass


def _get_retriever(thread_id):
    if not thread_id:
        return None
    tid = str(thread_id)
    retr = _THREAD_RETRIEVERS.get(tid)
    if retr is not None:
        return retr
    try:
        row = _doc_conn.execute(
            "SELECT filename, filetype, metadata, file_blob "
            "FROM thread_documents WHERE thread_id = ?",
            (tid,),
        ).fetchone()
        if row:
            fname, ftype, meta_json, fbytes = row
            _rebuild_retriever(tid, fname, ftype, fbytes, json.loads(meta_json))
            print(f"[RAG] Rebuilt retriever on-demand for thread {tid}")
            return _THREAD_RETRIEVERS.get(tid)
    except Exception as e:
        print(f"[RAG] On-demand rebuild failed for thread {tid}: {e}")
    return None


def ingest_document(file_bytes, thread_id, filename=None):
    if not file_bytes:
        raise ValueError("No bytes received.")
    filename = filename or "document"
    suffix = os.path.splitext(filename)[-1].lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type '{suffix}'. Use PDF or DOCX.")

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
        f.write(file_bytes)
        temp_path = f.name
    try:
        loader = (
            PyPDFLoader(temp_path) if suffix == ".pdf" else Docx2txtLoader(temp_path)
        )
        docs = loader.load()
        for doc in docs:
            text = re.sub(r"\n{3,}", "\n\n", doc.page_content)
            doc.page_content = "\n".join(
                line.strip() for line in text.splitlines()
            ).strip()

        total_chars = sum(len(d.page_content) for d in docs)
        if total_chars < 5_000:
            cs, co = 500, 50
        elif total_chars < 20_000:
            cs, co = 800, 150
        elif total_chars < 50_000:
            cs, co = 1000, 200
        elif total_chars < 100_000:
            cs, co = 1200, 250
        else:
            cs, co = 1500, 300

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=cs,
            chunk_overlap=co,
            separators=["\n\n", "\n", " ", ""],
        )
        chunks = splitter.split_documents(docs)
        n = len(chunks)
        if n < 20:
            k, fk = 4, 10
        elif n < 50:
            k, fk = 4, 20
        elif n < 100:
            k, fk = 5, 25
        elif n < 200:
            k, fk = 6, 30
        else:
            k, fk = 8, 40

        persist_dir = os.path.join(CHROMA_BASE_DIR, str(thread_id))
        _release_chroma(str(thread_id))
        if os.path.exists(persist_dir):
            _safe_rmtree(persist_dir)

        vs = Chroma.from_documents(
            chunks,
            embeddings,
            persist_directory=persist_dir,
        )
        retr = vs.as_retriever(search_type="mmr", search_kwargs={"k": k, "fetch_k": fk})

        meta = {
            "filename": filename,
            "filetype": suffix,
            "documents": len(docs),
            "chunks": n,
            "chunk_size": cs,
            "chunk_overlap": co,
            "k": k,
            "fetch_k": fk,
        }
        _THREAD_VECTORSTORES[str(thread_id)] = vs
        _THREAD_RETRIEVERS[str(thread_id)] = retr
        _THREAD_METADATA[str(thread_id)] = meta
        _save_doc_to_db(str(thread_id), filename, suffix, meta, file_bytes)
        return meta
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass


def remove_document(thread_id):
    tid = str(thread_id)
    _release_chroma(tid)
    _THREAD_RETRIEVERS.pop(tid, None)
    _THREAD_METADATA.pop(tid, None)
    _delete_doc_from_db(tid)
    chroma_path = os.path.join(CHROMA_BASE_DIR, tid)
    if os.path.exists(chroma_path):
        _safe_rmtree(chroma_path)
        print(f"[Chroma] removed persist dir for thread {tid}")


ingest_pdf = ingest_document
_load_all_docs_from_db()


# =============================================================
#  CHAT TITLE STORE
# =============================================================
def _init_title_table():
    _doc_conn.execute("""
        CREATE TABLE IF NOT EXISTS thread_titles (
            thread_id TEXT PRIMARY KEY,
            title     TEXT NOT NULL
        )
    """)
    _doc_conn.commit()


_init_title_table()


def save_thread_title(thread_id, title):
    _doc_conn.execute(
        "INSERT OR IGNORE INTO thread_titles (thread_id, title) VALUES (?, ?)",
        (str(thread_id), title),
    )
    _doc_conn.commit()


def get_all_thread_titles():
    deleted = _get_deleted_thread_ids()
    return {
        r[0]: r[1]
        for r in _doc_conn.execute(
            "SELECT thread_id, title FROM thread_titles"
        ).fetchall()
        if r[0] not in deleted
    }


# =============================================================
# b. DELETED-THREADS BLOCKLIST
# =============================================================
def _init_deleted_table():
    _doc_conn.execute("""
        CREATE TABLE IF NOT EXISTS deleted_threads (
            thread_id  TEXT PRIMARY KEY,
            deleted_at TEXT NOT NULL
        )
    """)
    _doc_conn.commit()


_init_deleted_table()


def mark_thread_deleted(thread_id):
    _doc_conn.execute(
        "INSERT OR REPLACE INTO deleted_threads (thread_id, deleted_at) VALUES (?, ?)",
        (str(thread_id), datetime.now(timezone.utc).isoformat()),
    )
    _doc_conn.commit()
    _doc_conn.execute(
        "DELETE FROM thread_titles WHERE thread_id = ?", (str(thread_id),)
    )
    _doc_conn.commit()


def _get_deleted_thread_ids() -> set:
    return {
        r[0]
        for r in _doc_conn.execute("SELECT thread_id FROM deleted_threads").fetchall()
    }


# =============================================================
# c. THREAD CREATION TIMESTAMPS
# =============================================================
def _init_thread_created_table():
    _doc_conn.execute("""
        CREATE TABLE IF NOT EXISTS thread_created (
            thread_id  TEXT PRIMARY KEY,
            created_at TEXT NOT NULL
        )
    """)
    _doc_conn.commit()


_init_thread_created_table()


def record_thread_created(thread_id):
    _doc_conn.execute(
        "INSERT OR IGNORE INTO thread_created (thread_id, created_at) VALUES (?, ?)",
        (str(thread_id), datetime.now(timezone.utc).isoformat()),
    )
    _doc_conn.commit()


def get_thread_created_dates() -> dict:
    return {
        r[0]: r[1]
        for r in _doc_conn.execute(
            "SELECT thread_id, created_at FROM thread_created"
        ).fetchall()
    }


# =============================================================
#  TOOLS
# =============================================================
search_tool = DuckDuckGoSearchRun(region="us-en")


@tool
def get_stock_price(symbol: str) -> dict:
    """Fetch latest stock price for a given symbol e.g. 'AAPL', 'TSLA'."""
    url = (
        "https://www.alphavantage.co/query"
        f"?function=GLOBAL_QUOTE&symbol={symbol}"
        f"&apikey={os.getenv('ALPHAVANTAGE_API_KEY')}"
    )
    return requests.get(url).json()


@tool
def calculator(expression: str) -> dict:
    """
    Evaluate a math expression like '2 + 2', '10 * 5', '100 / 4'.
    Supports +, -, *, /, ** (power), % (modulo).
    Always use this for any math question.
    """
    try:
        allowed = set("0123456789+-*/.() %**")
        if not all(c in allowed for c in expression.replace(" ", "")):
            return {"error": "Invalid characters in expression"}
        result = eval(expression, {"__builtins__": {}})
        return {"expression": expression, "result": result}
    except Exception as e:
        return {"error": str(e)}


@tool
def rag_tool(query: str, thread_id: Optional[str] = None) -> dict:
    """
    Retrieve relevant information from uploaded PDF or DOCX for this chat thread.
    Always pass thread_id when calling this tool.
    """
    retr = _get_retriever(thread_id)
    if retr is None:
        return {
            "error": "No document indexed. Please upload a PDF or DOCX first.",
            "query": query,
        }
    result = retr.invoke(query)
    return {
        "query": query,
        "context": [doc.page_content for doc in result],
        "metadata": [doc.metadata for doc in result],
        "source_file": _THREAD_METADATA.get(str(thread_id), {}).get("filename"),
    }


client = MultiServerMCPClient(
    {
        "expense": {
            "transport": "stdio",
            "command": "C:/Users/Hp/AppData/Local/Programs/Python/Python312/Scripts/uv.exe",
            "args": [
                "run",
                "--with",
                "fastmcp",
                "fastmcp",
                "run",
                "E:/langgrapph_chat_ui/expense_server.py",
            ],
        },
    }
)


def load_mcp_tools() -> list[BaseTool]:
    try:
        return run_async(client.get_tools())
    except Exception as e:
        print(f"[warn] Could not load MCP tools: {e}")
        return []


mcp_tools = load_mcp_tools()
tools = [search_tool, get_stock_price, calculator, rag_tool, *mcp_tools]
llm_with_tools = llm.bind_tools(tools) if tools else llm


# =============================================================
# STATE
# =============================================================
class ChatState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    summary: str
    detected_language: str


# =============================================================
#  NODES
# =============================================================
def _build_summary(tool_name: str, tool_args: dict) -> str:
    if tool_name == "add_expense":
        return (
            f"Add expense of **${tool_args.get('amount')}** "
            f"for **{tool_args.get('category', 'unknown')}** "
            f"on {tool_args.get('date', 'today')}"
        )
    elif tool_name == "edit_expense":
        changes = {k: v for k, v in tool_args.items() if k != "id" and v is not None}
        return f"Edit expense ID **{tool_args.get('id')}** → {changes}"
    elif tool_name == "delete_expense":
        return f"Permanently delete expense ID **{tool_args.get('id')}**"
    elif tool_name == "add_credit":
        return (
            f"Add income of **${tool_args.get('amount')}** "
            f"from **{tool_args.get('source', 'unknown')}** "
            f"on {tool_args.get('date', 'today')}"
        )
    return f"Run `{tool_name}` with {tool_args}"


def remember_node(state: ChatState, config: RunnableConfig, *, store: BaseStore):
    if store is None:
        return {}
    user_id = config.get("configurable", {}).get("user_id", "default_user")
    last_human = next(
        (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
        None,
    )
    if last_human:
        ltm.extract_and_save(store, user_id, last_human.content)
    return {}


async def summarize_node(state: ChatState) -> dict:
    existing_summary = state.get("summary", "")
    messages = state["messages"]

    if existing_summary:
        prompt = (
            f"Existing summary:\n{existing_summary}\n\n"
            "Extend this summary with the new messages above. "
            "Be concise. Write in English only. Return only the summary text."
        )
    else:
        prompt = (
            "Summarize the conversation above concisely in English. "
            "Preserve key facts, requests, tool results, and decisions. "
            "Return only the summary text."
        )

    _sum_msgs = [
        SystemMessage(
            content="You are a conversation summarizer. Return only the summary text, no commentary."
        ),
        *messages,
        HumanMessage(content=prompt),
    ]
    tried, last_exc = 0, None
    while tried < len(_GROQ_KEYS):
        try:
            _summarizer = _make_mem_llm(temperature=0)
            response = await _summarizer.ainvoke(_sum_msgs)
            break
        except Exception as exc:
            if _is_rate_limit(exc):
                tried += 1
                last_exc = exc
                print(
                    f"[Groq/summarize] Rate limit, rotating key ({tried}/{len(_GROQ_KEYS)})…"
                )
            else:
                raise
    else:
        raise last_exc

    messages_to_delete = messages[:-2]
    deletions = [RemoveMessage(id=m.id) for m in messages_to_delete]
    print(f"[STM] Summarized {len(messages_to_delete)} messages → kept last 2")

    return {
        "summary": response.content.strip(),
        "messages": deletions,
    }


async def chat_node(state: ChatState, config: RunnableConfig, *, store: BaseStore):
    thread_id = config.get("configurable", {}).get("thread_id")
    user_id = config.get("configurable", {}).get("user_id", "default_user")
    has_doc = thread_id and _get_retriever(thread_id) is not None
    meta = _THREAD_METADATA.get(str(thread_id), {})
    doc_name = meta.get("filename", "")

    last_human = next(
        (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
        None,
    )
    query = last_human.content if last_human else ""
    user_memories = ltm.fetch(store, user_id, query=query) if store else ""
    user_context = (
        f"What I know about you:\n{user_memories}\nUse this to personalize your responses."
        if user_memories
        else ""
    )
    if has_doc:
        rag_context = f", rag_tool (use for doc '{doc_name}', always pass thread_id='{thread_id}')"
    else:
        rag_context = (
            ". IMPORTANT: No document is currently uploaded for this "
            "conversation, and rag_tool is unavailable right now. If "
            "earlier messages in this conversation reference a document "
            "or its content, that document has since been removed — do "
            "NOT answer from memory of it or repeat/paraphrase old details "
            "about it. Tell the user no document is currently active and "
            "ask them to upload one if they want to ask about a document."
        )

    summary = state.get("summary", "")
    summary_context = (
        f"\n\nSummary of earlier conversation:\n{summary}" if summary else ""
    )

    system_message = SystemMessage(
        content=SYSTEM_PROMPT.format(
            user_context=user_context,
            rag_context=rag_context,
        )
        + summary_context
    )

    messages = [system_message, *state["messages"]]
    response = await _invoke_with_fallback(
        messages, config=config, tools_bound_llm=llm_with_tools
    )

    tool_calls = getattr(response, "tool_calls", [])
    pending = [tc for tc in tool_calls if tc["name"] in APPROVAL_REQUIRED]
    if pending:
        tc = pending[0]
        tool_name = tc["name"]
        tool_args = tc["args"]
        summary_text = _build_summary(tool_name, tool_args)
        decision = interrupt(
            {
                "tool_name": tool_name,
                "tool_args": tool_args,
                "summary": summary_text,
            }
        )
        if not decision.get("approved"):
            return {
                "messages": [
                    AIMessage(
                        content=f"No problem — I've canceled the {tool_name.replace('_', ' ')}."
                    )
                ]
            }

    return {"messages": [response]}


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


async def translate_node(state: ChatState) -> dict:
    messages = state["messages"]

    last_human = next(
        (m for m in reversed(messages) if isinstance(m, HumanMessage)), None
    )
    last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)

    if not last_human or not last_ai:
        return {}
    if getattr(last_ai, "tool_calls", []):
        return {}
    if not last_ai.content:
        return {}

    user_msg = last_human.content.strip()
    ai_text = last_ai.content
    lower_msg = user_msg.lower()

    if any(phrase in lower_msg for phrase in _ENGLISH_OVERRIDES):
        print("[translate_node] English override — skipping translation")
        return {}

    has_devanagari = bool(re.search(r"[\u0900-\u097F]", user_msg))
    has_romanized = any(t in lower_msg for t in _ROMANIZED_TRIGGERS)

    if not has_devanagari and not has_romanized:
        return {}

    try:
        translated = await run_translation(user_msg, ai_text)
    except Exception as e:
        print(f"[translate_node] Error, keeping original: {e}")
        return {}

    if translated == ai_text:
        return {}

    def _space_ratio(t: str) -> float:
        return t.count(" ") / max(len(t), 1)

    if _space_ratio(ai_text) > 0.05 and _space_ratio(translated) < 0.02:
        print("[translate_node] Corrupted translation discarded — keeping original")
        return {}

    translated_message = AIMessage(
        content=translated,
        id=last_ai.id,
    )
    return {
        "messages": [RemoveMessage(id=last_ai.id), translated_message],
        "detected_language": "non-english",
    }


tool_node = ToolNode(tools) if tools else None


# =============================================================
#  GRAPH
# =============================================================
def route_after_chat(state: ChatState):
    last = state["messages"][-1]
    if getattr(last, "tool_calls", []):
        return "tools"
    return "translate"


def route_after_translate(state: ChatState):
    if len(state["messages"]) > STM_SUMMARIZE_AFTER:
        return "summarize"
    return END


graph = StateGraph(ChatState)
graph.add_node("remember", remember_node)
graph.add_node("chat_node", chat_node)
graph.add_node("translate", translate_node)
graph.add_node("summarize", summarize_node)

graph.add_edge(START, "remember")
graph.add_edge("remember", "chat_node")

if tool_node:
    graph.add_node("tools", tool_node)
    graph.add_conditional_edges(
        "chat_node",
        route_after_chat,
        {"tools": "tools", "translate": "translate"},
    )
    graph.add_edge("tools", "chat_node")
else:
    graph.add_conditional_edges(
        "chat_node",
        route_after_chat,
        {"translate": "translate"},
    )

graph.add_conditional_edges(
    "translate",
    route_after_translate,
    {"summarize": "summarize", END: END},
)
graph.add_edge("summarize", END)

chatbot = graph.compile(
    checkpointer=checkpointer,
    store=_pg_store,
)


# =============================================================
#  HELPERS
# =============================================================
def retrieve_all_threads():
    try:
        all_threads = set()
        for checkpoint in checkpointer.list(None):
            all_threads.add(checkpoint.config["configurable"]["thread_id"])
        deleted = _get_deleted_thread_ids()
        live_threads = [t for t in all_threads if str(t) not in deleted]
        for t in live_threads:
            record_thread_created(t)
        return live_threads
    except Exception:
        return []


def thread_has_document(thread_id):
    return _get_retriever(thread_id) is not None


def thread_document_metadata(thread_id):
    return _THREAD_METADATA.get(str(thread_id), {})


def get_user_memories(user_id: str = "default_user") -> list[str]:
    if _pg_store is None:
        return []
    return ltm.get_all(_pg_store, user_id)


# =============================================================
# BLOG GENERATION MODULE
# =============================================================
from typing import List, Literal
from pydantic import BaseModel, Field
import operator


# -- Blog Schemas --
class BlogTask(BaseModel):
    id: int
    title: str
    goal: str = Field(
        ..., description="One sentence describing what the reader should understand."
    )
    bullets: List[str] = Field(..., min_length=2, max_length=6)
    target_words: int = Field(..., description="Target words (120–550).")
    tags: List[str] = Field(default_factory=list)
    requires_research: bool = False
    requires_citations: bool = False
    requires_code: bool = False


class BlogPlan(BaseModel):
    blog_title: str
    audience: str
    tone: str
    blog_kind: Literal[
        "explainer", "tutorial", "news_roundup", "comparison", "system_design"
    ] = "explainer"
    constraints: List[str] = Field(default_factory=list)
    tasks: List[BlogTask]


class BlogEvidenceItem(BaseModel):
    title: str
    url: str
    published_at: Optional[str] = None
    snippet: Optional[str] = None
    source: Optional[str] = None


class BlogRouterDecision(BaseModel):
    needs_research: bool
    mode: Literal["closed_book", "hybrid", "open_book"]
    reason: str
    queries: List[str] = Field(default_factory=list)
    max_results_per_query: int = Field(5)


class BlogEvidencePack(BaseModel):
    evidence: List[BlogEvidenceItem] = Field(default_factory=list)


class BlogImageSpec(BaseModel):
    placeholder: str = Field(..., description="e.g. [[IMAGE_1]]")
    filename: str = Field(..., description="Save under images/, e.g. hero.png")
    alt: str
    caption: str
    prompt: str = Field(..., description="Prompt to send to the image model.")
    size: Literal["1024x1024", "1024x1536", "1536x1024"] = "1024x1024"
    quality: Literal["low", "medium", "high"] = "medium"


class BlogGlobalImagePlan(BaseModel):
    md_with_placeholders: str
    images: List[BlogImageSpec] = Field(default_factory=list)


class BlogState(TypedDict):
    topic: str
    mode: str
    needs_research: bool
    queries: List[str]
    evidence: List[BlogEvidenceItem]
    plan: Optional[BlogPlan]
    as_of: str
    recency_days: int
    sections: Annotated[List[tuple], operator.add]
    merged_md: str
    md_with_placeholders: str
    image_specs: List[dict]
    final: str


# -- Blog Router --
BLOG_ROUTER_SYSTEM = """You are a routing module for a technical blog planner.
Decide whether web research is needed BEFORE planning.

Modes:
- closed_book (needs_research=false): evergreen concepts.
- hybrid (needs_research=true): evergreen + needs up-to-date examples/tools/models.
- open_book (needs_research=true): volatile weekly/news/"latest"/pricing/policy.
If needs_research=true: Output 3–10 high-signal, scoped queries."""


def blog_router_node(state: BlogState) -> dict:
    decider = blog_llm.with_structured_output(BlogRouterDecision)
    decision = decider.invoke(
        [
            SystemMessage(content=BLOG_ROUTER_SYSTEM),
            HumanMessage(
                content=f"Topic: {state['topic']}\nAs-of date: {state['as_of']}"
            ),
        ]
    )
    if decision.mode == "open_book":
        recency_days = 7
    elif decision.mode == "hybrid":
        recency_days = 45
    else:
        recency_days = 3650
    return {
        "needs_research": decision.needs_research,
        "mode": decision.mode,
        "queries": decision.queries,
        "recency_days": recency_days,
    }


def blog_route_next(state: BlogState) -> str:
    return "blog_research" if state["needs_research"] else "blog_orchestrator"


# -- Blog Research --
def _tavily_search(query: str, max_results: int = 5) -> List[dict]:
    """Search Tavily and return normalized evidence dicts with guaranteed fields."""
    if not os.getenv("TAVILY_API_KEY"):
        return []
    try:
        try:
            from langchain_tavily import TavilySearch

            tool = TavilySearch(max_results=max_results)
        except ImportError:
            from langchain_community.tools.tavily_search import TavilySearchResults

            tool = TavilySearchResults(max_results=max_results)

        raw_results = tool.invoke({"query": query})

        results = []
        if isinstance(raw_results, str):
            try:
                parsed = json.loads(raw_results)
                if isinstance(parsed, list):
                    results = parsed
                elif isinstance(parsed, dict) and "results" in parsed:
                    results = parsed["results"]
                else:
                    results = [parsed]
            except json.JSONDecodeError:
                return [
                    {
                        "title": f"Tavily search: {query}",
                        "url": f"https://tavily.com/?q={quote(query)}",
                        "snippet": raw_results[:800],
                        "published_at": "N/A",
                        "source": "tavily.com",
                    }
                ]
        elif isinstance(raw_results, dict):
            results = raw_results.get("results", [raw_results])
        elif isinstance(raw_results, list):
            results = raw_results
        else:
            print(f"[Research/Tavily] Unexpected response type: {type(raw_results)}")
            return []

        out = []
        for r in results or []:
            if isinstance(r, str):
                continue
            url = r.get("url") or r.get("href") or r.get("link") or ""
            title = r.get("title") or r.get("name") or ""
            if not url:
                continue
            out.append(
                {
                    "title": title or "Untitled",
                    "url": url,
                    "snippet": (
                        r.get("content")
                        or r.get("snippet")
                        or r.get("body")
                        or r.get("text")
                        or ""
                    )[:500],
                    "published_at": r.get("published_date")
                    or r.get("published_at")
                    or r.get("date")
                    or "N/A",
                    "source": r.get("source") or _extract_domain(url),
                }
            )
        return out
    except Exception as e:
        print(f"[Research/Tavily] Error: {e}")
        return []


def _duckduckgo_search(query: str) -> List[dict]:
    """DuckDuckGo fallback with real URLs and snippets."""
    try:
        ddg = DuckDuckGoSearchRun(region="us-en")
        result_text = ddg.run(query)
        if not result_text:
            return []
        return [
            {
                "title": f"Search: {query}",
                "url": f"https://duckduckgo.com/?q={quote(query)}",
                "snippet": result_text[:600],
                "published_at": "N/A",
                "source": "duckduckgo.com",
            }
        ]
    except Exception as e:
        print(f"[Research/DDG] Error for query '{query}': {e}")
        return []


def _iso_to_date(s):
    if not s:
        return None
    try:
        from datetime import date as _date

        return _date.fromisoformat(s[:10])
    except Exception:
        return None


def blog_research_node(state: BlogState) -> dict:
    queries = (state.get("queries") or [])[:10]
    raw = []

    for q in queries:
        raw.extend(_tavily_search(q, max_results=6))

    if not raw:
        print("[Research] Tavily returned no results, trying DuckDuckGo fallback...")
        for q in queries[:3]:
            raw.extend(_duckduckgo_search(q))
        print(f"[Research] DuckDuckGo found {len(raw)} results")

    if not raw:
        print("[Research] No evidence found from any source")
        return {"evidence": []}

    # Deduplicate by URL
    dedup_raw = {}
    for item in raw:
        url = item.get("url", "")
        if not url:
            continue
        if url in dedup_raw:
            existing = dedup_raw[url]
            if len(item.get("snippet", "")) > len(existing.get("snippet", "")):
                dedup_raw[url] = item
        else:
            dedup_raw[url] = item

    raw_deduped = list(dedup_raw.values())
    print(f"[Research] {len(raw)} raw results → {len(raw_deduped)} after dedup")

    # Convert to BlogEvidenceItem objects directly (skip LLM structured extraction)
    evidence = []
    for item in raw_deduped:
        evidence.append(
            BlogEvidenceItem(
                title=item.get("title", "Untitled"),
                url=item["url"],
                published_at=item.get("published_at", "N/A"),
                snippet=item.get("snippet", "")[:300],
                source=item.get("source") or _extract_domain(item["url"]),
            )
        )

    print(f"[Research] Extracted {len(evidence)} unique evidence items with valid URLs")
    return {"evidence": evidence}


# -- Blog Orchestrator --
BLOG_ORCH_SYSTEM = """You are a senior technical writer and developer advocate.
Produce a highly actionable outline for a technical blog post.

ANTI-HALLUCINATION RULES:
- Use the EXACT topic name the user provided — do NOT correct or change it.
- "India's Got Talent" is a real TV show — do NOT rename it.
- If you don't recognize a name, assume the user is correct and use it verbatim.

CRITICAL REQUIREMENTS:
- 5–9 tasks total
- EACH task MUST have 3–6 bullet points — NEVER fewer than 3
- Each bullet must be a specific, actionable point to cover
- If you only have 2 ideas for a section, split one into two or add a "Broader implications" bullet
- Each task needs: goal (1 sentence) + bullets (3–6 items) + target_words"""


def blog_orchestrator_node(state: BlogState) -> dict:
    planner = blog_llm.with_structured_output(BlogPlan)
    mode = state.get("mode", "closed_book")
    evidence = state.get("evidence", [])
    forced_kind = "news_roundup" if mode == "open_book" else None

    # Format evidence for the planner
    evidence_text = (
        "\n".join(f"[{i+1}] {e.title} — {e.url}" for i, e in enumerate(evidence[:8]))
        if evidence
        else "No evidence available."
    )

    plan = planner.invoke(
        [
            SystemMessage(content=BLOG_ORCH_SYSTEM),
            HumanMessage(
                content=(
                    f"Topic: {state['topic']}\nMode: {mode}\nAs-of: {state['as_of']}\n"
                    f"{'Force blog_kind=news_roundup' if forced_kind else ''}\n\n"
                    f"Available Evidence:\n{evidence_text}"
                )
            ),
        ]
    )
    if forced_kind:
        plan.blog_kind = "news_roundup"
    return {"plan": plan}


# -- Blog Fanout --
def blog_fanout(state: BlogState):
    assert state["plan"] is not None
    return [
        Send(
            "blog_worker",
            {
                "task": task.model_dump(),
                "topic": state["topic"],
                "mode": state["mode"],
                "as_of": state["as_of"],
                "recency_days": state["recency_days"],
                "plan": state["plan"].model_dump(),
                "evidence": [e.model_dump() for e in state.get("evidence", [])[:8]],
            },
        )
        for task in state["plan"].tasks
    ]


BLOG_WORKER_SYSTEM = """You are a senior technical writer writing ONE section of a professional blog post in Markdown.

CRITICAL FORMATTING RULES — YOU MUST FOLLOW THESE EXACTLY:

1. Start with: ## <Section Title>
2. Write 2-4 well-formed PARAGRAPHS. Each paragraph must be 3-5 sentences and separated by a blank line.
3. Use bullet points ONLY for lists of 3+ related items. Do not overuse bullets.
4. EVERY fact, statistic, or claim from the Evidence MUST have a superscript citation [N] immediately after it.
   Example: "RAG systems improve answer accuracy by up to 40%[1]."
5. Use consecutive numbers [1], [2], [3]... matching the Evidence order provided.
6. At the VERY END of your section (after ALL paragraphs), you MUST add:

   ### Sources
   [1] [Title](URL) — published: date
   [2] [Title](URL) — published: date

7. The title in Sources MUST be a clickable Markdown link: [Title](URL)
8. If Evidence is EMPTY, write WITHOUT any citations and WITHOUT a Sources section.
9. NEVER invent fake sources. Only cite from the exact evidence URLs provided.
10. Write in a conversational yet professional tone. Use transitions between paragraphs.
11. Each paragraph should flow logically to the next. Avoid repetition.

EXAMPLE OUTPUT FORMAT:

## Introduction to RAG Systems

Retrieval-Augmented Generation (RAG) has emerged as one of the most important paradigms in modern AI[1]. By combining external knowledge retrieval with generative capabilities, RAG addresses a fundamental limitation of standalone large language models.

The core mechanism is elegantly simple. When a user asks a question, the RAG system first searches a knowledge base for relevant documents, then feeds those documents along with the original query to a language model[2]. This two-step process dramatically improves factual accuracy.

### Sources
[1] [RAG Systems Survey 2024](https://arxiv.org/abs/2401.12345) — published: 2024-01-15
[2] [Understanding RAG Architecture](https://blog.example.com/rag) — published: 2024-03-20"""


def blog_worker_node(payload: dict) -> dict:
    task = BlogTask(**payload["task"])
    plan = BlogPlan(**payload["plan"])
    evidence = [BlogEvidenceItem(**e) for e in payload.get("evidence", [])]

    # Format evidence as clean numbered list for the worker
    evidence_lines = []
    for i, e in enumerate(evidence[:8], 1):
        evidence_lines.append(
            f'[{i}] "{e.title}" — {e.url} (published: {e.published_at or "N/A"}) [source: {e.source}]'
        )
        if e.snippet:
            evidence_lines.append(f"    Snippet: {e.snippet[:200]}")

    evidence_text = (
        "\n".join(evidence_lines)
        if evidence_lines
        else "NO EVIDENCE — write original content without citations"
    )

    # FIXED: Truncate evidence to avoid TPM limit on large evidence packs
    # Each worker runs in parallel (fanout), so all hit Groq simultaneously
    max_evidence_chars = 2500
    if len(evidence_text) > max_evidence_chars:
        truncated_evidence = (
            evidence_text[:max_evidence_chars]
            + "\n...[additional evidence truncated for TPM protection]..."
        )
        print(
            f"[Blog/Worker] Truncated evidence {len(evidence_text)} → {len(truncated_evidence)} chars for TPM safety"
        )
    else:
        truncated_evidence = evidence_text

    # FIXED: Use sync fallback with exponential backoff instead of direct invoke
    # Groq rate limits are PER ORGANIZATION — key rotation alone does not help
    section_md = _invoke_blog_sync_with_fallback(
        [
            SystemMessage(content=BLOG_WORKER_SYSTEM),
            HumanMessage(
                content=(
                    f"Blog title: {plan.blog_title}\n"
                    f"Audience: {plan.audience}\n"
                    f"Tone: {plan.tone}\n"
                    f"Blog kind: {plan.blog_kind}\n"
                    f"Topic: {payload['topic']}\n"
                    f"Mode: {payload.get('mode')}\n"
                    f"As-of: {payload.get('as_of')}\n\n"
                    f"Section title: {task.title}\n"
                    f"Goal: {task.goal}\n"
                    f"Target words: {task.target_words}\n"
                    f"requires_citations: {task.requires_citations}\n"
                    f"requires_code: {task.requires_code}\n"
                    f"Key points to cover: {', '.join(task.bullets)}\n\n"
                    f"=== EVIDENCE SOURCES (CITE USING [1], [2], [3]...) ===\n"
                    f"{truncated_evidence}\n"
                    f"=== END EVIDENCE ==="
                )
            ),
        ]
    ).content.strip()

    # Post-process: ensure section starts with ##
    if not section_md.startswith("##"):
        section_md = f"## {task.title}\n\n{section_md}"

    # Post-process: ensure Sources section exists if evidence was provided
    if evidence and "### Sources" not in section_md:
        # Force-add Sources section from evidence
        sources_lines = ["\n### Sources"]
        for i, e in enumerate(evidence[:8], 1):
            pub = e.published_at or "N/A"
            sources_lines.append(f"[{i}] [{e.title}]({e.url}) — published: {pub}")
        section_md += "\n" + "\n".join(sources_lines)

    return {"sections": [(task.id, section_md)]}


def blog_merge_content(state: BlogState) -> dict:
    plan = state["plan"]
    if plan is None:
        raise ValueError("merge_content called without plan.")

    ordered_sections = [md for _, md in sorted(state["sections"], key=lambda x: x[0])]

    # Build properly formatted blog
    parts = []

    # Title
    parts.append(f"# {plan.blog_title}")
    parts.append("")

    # Metadata line
    parts.append(
        f"*Published: {state.get('as_of', datetime.now().strftime('%Y-%m-%d'))} | Audience: {plan.audience} | Tone: {plan.tone}*"
    )
    parts.append("")
    parts.append("---")
    parts.append("")

    # Table of Contents
    parts.append("## Table of Contents")
    parts.append("")
    for i, section_md in enumerate(ordered_sections, 1):
        title_match = re.search(r"^##\s+(.+)$", section_md, re.MULTILINE)
        if title_match:
            title = title_match.group(1).strip()
            anchor = re.sub(r"[^\w\s-]", "", title).lower().strip().replace(" ", "-")
            parts.append(f"{i}. [{title}](#{anchor})")
    parts.append("")
    parts.append("---")
    parts.append("")

    # Introduction paragraph
    if plan.blog_kind == "news_roundup":
        parts.append(
            "This article covers the latest developments and insights on the topic. Each section dives into a specific aspect, backed by credible sources where available."
        )
    elif plan.blog_kind == "tutorial":
        parts.append(
            "In this guide, we'll walk through everything you need to know, step by step. Whether you're a beginner or looking to deepen your understanding, this article has you covered."
        )
    else:
        parts.append(
            "In this article, we'll explore the topic in depth, breaking it down into clear, actionable sections. Let's dive in."
        )
    parts.append("")
    parts.append("---")
    parts.append("")

    # Sections with dividers
    for i, section_md in enumerate(ordered_sections):
        parts.append(section_md)
        parts.append("")
        if i < len(ordered_sections) - 1:
            parts.append("---")
            parts.append("")

    # Conclusion
    parts.append("## Conclusion")
    parts.append("")
    parts.append(
        f"We've covered the key aspects of **{plan.blog_title}**. From understanding the fundamentals to exploring practical applications, this guide should serve as a solid foundation. If you have questions or want to dive deeper into any specific area, feel free to explore the sources cited throughout this article."
    )
    parts.append("")

    merged_md = "\n".join(parts)
    return {"merged_md": merged_md}


# -- Image Planning --
BLOG_DECIDE_IMAGES_SYSTEM = """You are an expert blog editor who adds compelling visuals.

RULES:
1. ALWAYS insert exactly 1 to 3 image placeholders: [[IMAGE_1]], [[IMAGE_2]], [[IMAGE_3]].
2. NEVER return an empty images list. Every blog needs at least one hero image.
3. Insert [[IMAGE_1]] right after the first heading (hero/banner image for the topic).
4. Insert [[IMAGE_2]] and [[IMAGE_3]] where a visual would help understanding.
5. For non-technical topics (entertainment, sports, news): use illustrative/mood images.
6. For technical topics: use diagrams, flowcharts, or concept illustrations.
7. Write vivid, detailed image prompts — the more specific, the better the output.
8. Image style by topic:
   - Entertainment/TV shows: "vibrant stage lighting, crowd energy, colorful performance"
   - Tech/coding: "clean diagram, dark background, purple/blue accent lines"
   - News/events: "editorial illustration, bold composition, impactful visual"
   - Tutorial: "step-by-step diagram, minimalist, arrows showing flow"

Output: md_with_placeholders (markdown with [[IMAGE_N]] inserted) + images list (NEVER empty)."""


def blog_decide_images(state: BlogState) -> dict:
    planner = blog_llm.with_structured_output(BlogGlobalImagePlan)
    merged_md = state["merged_md"]
    plan = state["plan"]
    assert plan is not None

    # FIXED: Truncate merged_md to avoid TPM limit on large blogs
    # Keep first 3000 chars + last 2000 chars = ~5000 chars max prompt
    max_md_chars = 5000
    if len(merged_md) > max_md_chars:
        truncated = (
            merged_md[:3000]
            + "\n\n...[content truncated for TPM protection]...\n\n"
            + merged_md[-2000:]
        )
        print(
            f"[Blog] Truncated merged_md {len(merged_md)} → {len(truncated)} chars for TPM safety"
        )
    else:
        truncated = merged_md

    try:
        image_plan = planner.invoke(
            [
                SystemMessage(content=BLOG_DECIDE_IMAGES_SYSTEM),
                HumanMessage(
                    content=(
                        f"Blog kind: {plan.blog_kind}\n"
                        f"Topic: {state['topic']}\n\n"
                        f"Insert placeholders + propose image prompts.\n\n{truncated}"
                    )
                ),
            ]
        )
    except Exception as e:
        print(f"[Blog] image_plan LLM call failed: {e} — using fallback hero image")
        image_plan = BlogGlobalImagePlan(md_with_placeholders=merged_md, images=[])

    # Safety net: force hero image if LLM returns none
    if not image_plan.images:
        print(
            f"[Blog] LLM returned no image specs — injecting fallback hero for: {state['topic']!r}"
        )
        topic_slug = re.sub(r"[^a-z0-9]+", "_", state["topic"].lower().strip())[:40]
        fallback_spec = BlogImageSpec(
            placeholder="[[IMAGE_1]]",
            filename=f"{topic_slug}_hero.png",
            alt=f"Blog hero image: {state['topic']}",
            caption=state["topic"],
            prompt=(
                f"A high-quality, visually compelling hero banner illustration for a blog post "
                f"titled: '{state['topic']}'. "
                f"Style: vibrant colors, professional editorial look, dramatic lighting, "
                f"modern design. The image immediately conveys the topic at a glance. "
                f"No text overlaid. Wide cinematic format, high contrast, rich colors."
            ),
            size="1536x1024",
            quality="high",
        )
        lines = image_plan.md_with_placeholders.splitlines()
        new_lines = []
        inserted = False
        for line in lines:
            new_lines.append(line)
            if not inserted and line.startswith("#") and not line.startswith("##"):
                new_lines.extend(["", "[[IMAGE_1]]", ""])
                inserted = True
        if not inserted:
            new_lines = [new_lines[0], "", "[[IMAGE_1]]", ""] + new_lines[1:]
        image_plan.md_with_placeholders = "\n".join(new_lines)
        image_plan.images = [fallback_spec]

    return {
        "md_with_placeholders": image_plan.md_with_placeholders,
        "image_specs": [img.model_dump() for img in image_plan.images],
    }


# =============================================================
# IMAGE GENERATION: HF-Primary + Pollinations + Google Fallback
# =============================================================


def _generate_hf_inference_client(
    prompt: str, width: int = 1024, height: int = 1024
) -> bytes:
    """PRIMARY: Generate image using HF InferenceClient (router.huggingface.co)."""
    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        raise RuntimeError("HF_TOKEN not set")

    try:
        from huggingface_hub import InferenceClient

        print(f"[HF InferenceClient] Generating via router.huggingface.co...")
        client = InferenceClient(token=hf_token, provider="auto")

        models_to_try = [
            "black-forest-labs/FLUX.1-schnell",
            "black-forest-labs/FLUX.1-dev",
        ]

        last_error = None
        for model_id in models_to_try:
            try:
                print(f"[HF InferenceClient] Trying model: {model_id}")
                image = client.text_to_image(
                    prompt,
                    model=model_id,
                    width=width,
                    height=height,
                )
                import io

                img_buffer = io.BytesIO()
                image.save(img_buffer, format="PNG")
                img_bytes = img_buffer.getvalue()
                print(
                    f"[HF InferenceClient] Generated: {len(img_bytes)} bytes via {model_id}"
                )
                return img_bytes
            except Exception as e:
                print(f"[HF InferenceClient] {model_id} failed: {e}")
                last_error = e
                continue

        raise last_error if last_error else RuntimeError("All models failed")

    except ImportError:
        raise RuntimeError("huggingface_hub not installed")
    except Exception as e:
        raise RuntimeError(f"HF InferenceClient failed: {e}")


def _generate_pollinations_image(
    prompt: str, width: int = 1024, height: int = 1024
) -> bytes:
    """FALLBACK 1: Pollinations AI — completely free, no API key needed."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # Truncate very long prompts (Pollinations has URL length limits)
            safe_prompt = prompt[:500]
            encoded_prompt = urllib.parse.quote(safe_prompt)

            # Time-based seed avoids cache collisions + attempt offset for retries
            seed = (hash(prompt) + int(time.time()) + attempt) % 100000

            # Use FLUX model explicitly for best quality
            url = (
                f"https://image.pollinations.ai/prompt/{encoded_prompt}"
                f"?width={width}&height={height}&seed={seed}"
                f"&nologo=true&model=flux&enhance=true"
            )

            print(
                f"[Pollinations] Attempt {attempt+1}/{max_retries}: {width}x{height}..."
            )
            print(f"[Pollinations] URL: {url[:120]}...")

            # Stream download for large images
            response = requests.get(url, timeout=180, stream=True)
            response.raise_for_status()

            # Read in chunks to avoid memory spikes
            img_bytes = b"".join(response.iter_content(chunk_size=8192))

            if len(img_bytes) < 1000:
                raise RuntimeError(
                    f"Image too small: {len(img_bytes)} bytes (likely error page)"
                )

            # Verify it's actually an image by checking magic bytes
            if img_bytes[:8] == b"\x89PNG\r\n\x1a\n":
                print(f"[Pollinations] Generated valid PNG: {len(img_bytes)} bytes")
            elif img_bytes[:3] == b"\xff\xd8\xff":
                print(f"[Pollinations] Generated valid JPEG: {len(img_bytes)} bytes")
            else:
                preview = img_bytes[:100]
                print(
                    f"[Pollinations] WARNING: Unknown format. First 100 bytes: {preview}"
                )

            return img_bytes

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 500 and attempt < max_retries - 1:
                wait = 2**attempt  # 1s, 2s, 4s exponential backoff
                print(f"[Pollinations] 500 error, retrying in {wait}s...")
                time.sleep(wait)
                continue
            raise RuntimeError(f"Pollinations HTTP error: {e.response.status_code}")
        except requests.exceptions.Timeout:
            raise RuntimeError("Pollinations timed out after 180s")
        except Exception as e:
            raise RuntimeError(f"Pollinations failed: {e}")

    raise RuntimeError("Pollinations exhausted all retries")


def _generate_google_imagen(
    prompt: str, width: int = 1024, height: int = 1024
) -> bytes:
    """FALLBACK 2: Generate image using Google Imagen via google-genai SDK."""
    google_key = os.environ.get("GOOGLE_API_KEY")
    if not google_key:
        raise RuntimeError("GOOGLE_API_KEY not set")

    try:
        from google import genai
        from google.genai import types

        print("[Google Imagen] Using google-genai SDK (generate_images)...")
        client = genai.Client(api_key=google_key)

        if width == 1024 and height == 1024:
            aspect_ratio = "1:1"
        elif width == 1024 and height == 1536:
            aspect_ratio = "2:3"
        elif width == 1536 and height == 1024:
            aspect_ratio = "3:2"
        else:
            aspect_ratio = "1:1"

        # FIXED: Use generate_images (plural) — API changed in newer SDK
        result = client.models.generate_images(
            model="imagen-3.0-generate-002",
            prompt=prompt,
            config=types.GenerateImagesConfig(
                aspect_ratio=aspect_ratio,
                number_of_images=1,
            ),
        )

        # FIXED: Access generated_images from result
        if result.generated_images and len(result.generated_images) > 0:
            img_bytes = result.generated_images[0].image.image_bytes
            print(f"[Google Imagen] Generated: {len(img_bytes)} bytes")
            return img_bytes
        else:
            raise RuntimeError("No image generated")

    except ImportError:
        raise RuntimeError("google-genai not installed")
    except Exception as e:
        raise RuntimeError(f"Google Imagen failed: {e}")


def _generate_image_bytes(prompt: str, width: int = 1024, height: int = 1024) -> bytes:
    """Generate image using multiple strategies with fallbacks.

    Hierarchy:
    1. HF InferenceClient (requires HF_TOKEN, best quality)
    2. Pollinations AI (completely free, no key needed)
    3. Google Imagen (requires GOOGLE_API_KEY)
    """
    strategies = [
        ("HF InferenceClient (primary)", _generate_hf_inference_client),
        ("Pollinations AI (free fallback)", _generate_pollinations_image),
        ("Google Imagen (fallback)", _generate_google_imagen),
    ]

    last_error = None
    for name, strategy_func in strategies:
        try:
            print(f"[Image Gen] Trying {name}...")
            return strategy_func(prompt, width, height)
        except Exception as e:
            print(f"[Image Gen] {name} failed: {e}")
            last_error = e
            continue

    raise RuntimeError(
        f"All image generation strategies failed. Last error: {last_error}\n"
        "\nTROUBLESHOOTING:\n"
        "1. HF: Check HF_TOKEN and credits at huggingface.co/settings/tokens\n"
        "2. Pollinations: Should work without key — check internet connection\n"
        "3. Google: Set GOOGLE_API_KEY in .env for Imagen fallback"
    )


def _detect_image_format(img_bytes: bytes) -> str:
    """Detect image format from magic bytes — never trust filename extensions."""
    if img_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    elif img_bytes[:3] == b"\xff\xd8\xff":
        return "jpeg"
    elif img_bytes[:4] == b"RIFF" and img_bytes[8:12] == b"WEBP":
        return "webp"
    elif img_bytes[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    else:
        return "png"  # safe default


def _safe_slug(title: str) -> str:
    s = title.strip().lower()
    s = re.sub(r"[^a-z0-9 _-]+", "", s)
    s = re.sub(r"\s+", "_", s).strip("_")
    return s or "blog"


def _extract_domain(url: str) -> str:
    """Extract clean domain name from a URL for source attribution."""
    if not url:
        return "unknown"
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    except Exception:
        return "unknown"


def _format_evidence_for_worker(evidence_list: list) -> str:
    """Format evidence items safely for the blog worker."""
    lines = []
    for i, e in enumerate(evidence_list[:8], 1):
        title = getattr(e, "title", None) or "Untitled Source"
        url = getattr(e, "url", None) or ""
        published = (
            getattr(e, "published_at", None)
            or getattr(e, "published_date", None)
            or "N/A"
        )
        source = getattr(e, "source", None) or _extract_domain(url)
        snippet = getattr(e, "snippet", None) or getattr(e, "content", None) or ""
        snippet = (snippet[:280] + "…") if len(snippet) > 280 else snippet
        lines.append(
            f'[{i}] "{title}" — {url} (published: {published}) [source: {source}]\n'
            f"    Snippet: {snippet}"
        )
    return (
        "\n".join(lines)
        if lines
        else "NO EVIDENCE — write original content without citations"
    )


def blog_generate_and_place_images(state: BlogState) -> dict:
    """
    Generate images, save physical files to blogs/images/, embed base64 in markdown,
    and write final .md + _meta.json to blogs/ folder.

    FIXED: Uses proper HTML img tags with data URIs that work in Streamlit.
    """
    import json

    plan = state["plan"]
    assert plan is not None

    md = state.get("md_with_placeholders") or state["merged_md"]
    image_specs = state.get("image_specs", []) or []
    topic_slug = _safe_slug(plan.blog_title)

    BLOG_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    BLOG_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    generated_images = []
    failed_count = 0

    for spec in image_specs:
        placeholder = spec["placeholder"]
        filename = spec["filename"]
        safe_filename = f"{topic_slug}_{filename}"
        out_path = BLOG_IMAGES_DIR / safe_filename

        if not out_path.exists():
            try:
                size_str = spec.get("size", "1024x1024")
                try:
                    w, h = map(int, size_str.split("x"))
                except (ValueError, AttributeError):
                    w, h = 1024, 1024

                img_bytes = _generate_image_bytes(spec["prompt"], width=w, height=h)
                out_path.write_bytes(img_bytes)
                generated_images.append(str(out_path))
                print(f"[Blog/Image] Saved: {out_path} ({len(img_bytes)} bytes)")

            except Exception as e:
                failed_count += 1
                error_msg = str(e)
                print(f"[Blog/Image] FAILED for {safe_filename}: {error_msg}")
                placeholder_html = (
                    '<div style="background:rgba(239,68,68,.05);'
                    "border:1.5px dashed rgba(239,68,68,.3);border-radius:12px;"
                    'padding:16px;text-align:center;margin:16px 0">'
                    '<div style="font-size:24px;margin-bottom:6px">⚠️</div>'
                    '<div style="font-weight:600;color:#f87171;font-size:13px">'
                    "Image generation failed</div>"
                    f'<div style="font-size:11px;color:#6b7280;margin-top:4px">'
                    f'{spec.get("caption", "")}</div></div>'
                )
                md = md.replace(placeholder, placeholder_html)
                continue

        if out_path.exists():
            img_bytes = out_path.read_bytes()

            img_format = _detect_image_format(img_bytes)

            # Proper base64 encoding with correct MIME type
            img_b64 = base64.b64encode(img_bytes).decode("utf-8")

            # Double quotes for HTML attributes (Streamlit-compatible)
            # display:block ensures proper image rendering
            img_md = (
                f'<img src="data:image/{img_format};base64,{img_b64}" '
                f'alt="{spec["alt"]}" '
                f'style="max-width:100%;border-radius:8px;margin:12px 0;'
                f'box-shadow:0 4px 20px rgba(0,0,0,0.3);display:block;" />'
                f'<p style="text-align:center;font-style:italic;color:#6b7280;'
                f'font-size:13px;margin-top:8px;">{spec["caption"]}</p>'
            )
            md = md.replace(placeholder, img_md)
            print(
                f"[Blog/Image] Embedded {img_format.upper()}: {len(img_b64)} base64 chars"
            )

    md_path = BLOG_OUTPUT_DIR / f"{topic_slug}.md"
    md_path.write_text(md, encoding="utf-8")
    print(f"[Blog] Saved markdown: {md_path}")

    meta = {
        "title": plan.blog_title,
        "topic": state.get("topic", ""),
        "mode": state.get("mode", "closed_book"),
        "as_of": state.get("as_of", ""),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "image_count": len(generated_images),
        "failed_images": failed_count,
        "images": generated_images,
        "markdown_path": str(md_path),
    }
    meta_path = BLOG_OUTPUT_DIR / f"{topic_slug}_meta.json"
    meta_path.write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[Blog] Saved metadata: {meta_path}")

    return {"final": md}


# -- Build Blog Graph --
blog_graph = StateGraph(BlogState)
blog_graph.add_node("blog_router", blog_router_node)
blog_graph.add_node("blog_research", blog_research_node)
blog_graph.add_node("blog_orchestrator", blog_orchestrator_node)
blog_graph.add_node("blog_worker", blog_worker_node)

blog_reducer_graph = StateGraph(BlogState)
blog_reducer_graph.add_node("blog_merge_content", blog_merge_content)
blog_reducer_graph.add_node("blog_decide_images", blog_decide_images)
blog_reducer_graph.add_node(
    "blog_generate_and_place_images", blog_generate_and_place_images
)
blog_reducer_graph.add_edge(START, "blog_merge_content")
blog_reducer_graph.add_edge("blog_merge_content", "blog_decide_images")
blog_reducer_graph.add_edge("blog_decide_images", "blog_generate_and_place_images")
blog_reducer_graph.add_edge("blog_generate_and_place_images", END)
blog_reducer_subgraph = blog_reducer_graph.compile()

blog_graph.add_node("blog_reducer", blog_reducer_subgraph)
blog_graph.add_edge(START, "blog_router")
blog_graph.add_conditional_edges(
    "blog_router",
    blog_route_next,
    {"blog_research": "blog_research", "blog_orchestrator": "blog_orchestrator"},
)
blog_graph.add_edge("blog_research", "blog_orchestrator")
blog_graph.add_conditional_edges("blog_orchestrator", blog_fanout, ["blog_worker"])
blog_graph.add_edge("blog_worker", "blog_reducer")
blog_graph.add_edge("blog_reducer", END)
blog_app = blog_graph.compile()


# -- Public API --
def generate_blog(topic: str, as_of: str = None) -> str:
    if as_of is None:
        as_of = datetime.now().strftime("%Y-%m-%d")
    initial_state = {
        "topic": topic,
        "mode": "closed_book",
        "needs_research": False,
        "queries": [],
        "evidence": [],
        "plan": None,
        "as_of": as_of,
        "recency_days": 3650,
        "sections": [],
        "merged_md": "",
        "md_with_placeholders": "",
        "image_specs": [],
        "final": "",
    }
    result = run_async(blog_app.ainvoke(initial_state))
    return result.get("final", "")

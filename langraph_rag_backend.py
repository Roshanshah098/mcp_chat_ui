from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from typing import TypedDict, Annotated, Optional, Dict, Any
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage
from langchain_groq import ChatGroq
from langchain_community.embeddings import HuggingFaceEmbeddings
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_community.tools import DuckDuckGoSearchRun
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader
from langchain_community.vectorstores import FAISS
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.tools import tool, BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from dotenv import load_dotenv
import aiosqlite
import sqlite3
import requests
import asyncio
import threading
import tempfile
import json
import re
import os

load_dotenv(override=True)

# Dedicated async loop
_ASYNC_LOOP = asyncio.new_event_loop()
_ASYNC_THREAD = threading.Thread(target=_ASYNC_LOOP.run_forever, daemon=True)
_ASYNC_THREAD.start()


def _submit_async(coro):
    return asyncio.run_coroutine_threadsafe(coro, _ASYNC_LOOP)


def run_async(coro):
    return _submit_async(coro).result()


def submit_async_task(coro):
    return _submit_async(coro)


# -------------------
# 1. LLM + Embeddings
# -------------------
llm = ChatGroq(model="llama-3.1-8b-instant", temperature=0.3)
# llama-3.3-70b-versatile
embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

# -------------------
# 2. Document store
# -------------------
_THREAD_RETRIEVERS: Dict[str, Any] = {}
_THREAD_METADATA: Dict[str, dict] = {}
SUPPORTED_EXTENSIONS = {".pdf", ".docx"}
DOC_DB = "chatbot.db"

# Tools that require human approval before execution
APPROVAL_REQUIRED = {"add_expense", "edit_expense", "delete_expense", "add_credit"}


def _doc_db_conn():
    conn = sqlite3.connect(DOC_DB, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS thread_documents (
            thread_id TEXT PRIMARY KEY,
            filename  TEXT NOT NULL,
            filetype  TEXT NOT NULL,
            metadata  TEXT NOT NULL,
            file_blob BLOB NOT NULL
        )
    """)
    conn.commit()
    return conn


_doc_conn = _doc_db_conn()


def _save_doc_to_db(thread_id, filename, filetype, metadata, file_bytes):
    _doc_conn.execute(
        "INSERT OR REPLACE INTO thread_documents (thread_id,filename,filetype,metadata,file_blob) VALUES (?,?,?,?,?)",
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
    for thread_id, filename, filetype, metadata_json, file_bytes in rows:
        try:
            _rebuild_retriever(
                thread_id, filename, filetype, file_bytes, json.loads(metadata_json)
            )
        except Exception as e:
            print(f"[warn] Could not reload doc for thread {thread_id}: {e}")


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
        vector_store = FAISS.from_documents(chunks, embeddings)
        retriever = vector_store.as_retriever(
            search_type="mmr",
            search_kwargs={"k": meta.get("k", 4), "fetch_k": meta.get("fetch_k", 20)},
        )
        _THREAD_RETRIEVERS[str(thread_id)] = retriever
        _THREAD_METADATA[str(thread_id)] = meta
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass


def _get_retriever(thread_id):
    return _THREAD_RETRIEVERS.get(str(thread_id)) if thread_id else None


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
            chunk_size, chunk_overlap = 500, 50
        elif total_chars < 20_000:
            chunk_size, chunk_overlap = 800, 150
        elif total_chars < 50_000:
            chunk_size, chunk_overlap = 1000, 200
        elif total_chars < 100_000:
            chunk_size, chunk_overlap = 1200, 250
        else:
            chunk_size, chunk_overlap = 1500, 300

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", " ", ""],
        )
        chunks = splitter.split_documents(docs)
        total_chunks = len(chunks)

        if total_chunks < 20:
            k, fetch_k = 4, 10
        elif total_chunks < 50:
            k, fetch_k = 4, 20
        elif total_chunks < 100:
            k, fetch_k = 5, 25
        elif total_chunks < 200:
            k, fetch_k = 6, 30
        else:
            k, fetch_k = 8, 40

        vector_store = FAISS.from_documents(chunks, embeddings)
        retriever = vector_store.as_retriever(
            search_type="mmr",
            search_kwargs={"k": k, "fetch_k": fetch_k},
        )
        meta = {
            "filename": filename,
            "filetype": suffix,
            "documents": len(docs),
            "chunks": total_chunks,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "k": k,
            "fetch_k": fetch_k,
        }
        _THREAD_RETRIEVERS[str(thread_id)] = retriever
        _THREAD_METADATA[str(thread_id)] = meta
        _save_doc_to_db(str(thread_id), filename, suffix, meta, file_bytes)
        return meta
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass


def remove_document(thread_id):
    thread_id = str(thread_id)
    _THREAD_RETRIEVERS.pop(thread_id, None)
    _THREAD_METADATA.pop(thread_id, None)
    _delete_doc_from_db(thread_id)


ingest_pdf = ingest_document
_load_all_docs_from_db()


# -------------------
# 3. Chat title store
# -------------------
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
    return {
        r[0]: r[1]
        for r in _doc_conn.execute(
            "SELECT thread_id, title FROM thread_titles"
        ).fetchall()
    }


# -------------------
# 4. Tools
# -------------------
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
    Retrieve relevant information from the uploaded PDF or DOCX for this chat thread.
    Always include the thread_id when calling this tool.
    """
    retriever = _get_retriever(thread_id)
    if retriever is None:
        return {
            "error": "No document indexed. Please upload a PDF or DOCX first.",
            "query": query,
        }
    result = retriever.invoke(query)
    return {
        "query": query,
        "context": [doc.page_content for doc in result],
        "metadata": [doc.metadata for doc in result],
        "source_file": _THREAD_METADATA.get(str(thread_id), {}).get("filename"),
    }


# MCP Tools
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


# -------------------
# 5. State
# -------------------
class ChatState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


# -------------------
# 6. Nodes
# -------------------
def _build_summary(tool_name: str, tool_args: dict) -> str:
    """Build a human-readable approval summary."""
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


async def chat_node(state: ChatState, config=None):
    """LLM node — generates response or tool call, pauses for approval if needed."""
    thread_id = None
    if config and isinstance(config, dict):
        thread_id = config.get("configurable", {}).get("thread_id")

    has_doc = thread_id and thread_id in _THREAD_RETRIEVERS
    meta = _THREAD_METADATA.get(str(thread_id), {})
    doc_name = meta.get("filename", "")
    filetype = meta.get("filetype", "")

    system_message = SystemMessage(
        content=(
            "You are a helpful, friendly assistant with access to these tools:\n\n"
            "- search_tool: search the web\n"
            "- get_stock_price: fetch live stock prices\n"
            "- calculator: solve math — always use this, never answer math in plain text\n"
            "- add_expense: add a new expense\n"
            "- list_expenses: list expenses in a date range\n"
            "- edit_expense: edit an expense by id\n"
            "- delete_expense: delete an expense by id\n"
            "- add_credit: add income or salary\n"
            "- list_credits: list income in a date range\n"
            "- summarize: summarize expenses vs income and show balance\n"
            + (
                f"- rag_tool: answer questions from the uploaded "
                f"{'PDF' if filetype == '.pdf' else 'DOCX'} '{doc_name}'. "
                f"Always pass thread_id='{thread_id}' when calling rag_tool.\n"
                if has_doc
                else "- rag_tool: not available (no document uploaded).\n"
            )
            + "\nRULES:\n"
            "- ONE tool call at a time\n"
            "- For edit/delete, ALWAYS call list_expenses first to find the id\n"
            "- If no date mentioned, assume today\n"
            "- After tool result, give a short friendly response\n"
            "- Never show raw JSON to the user\n"
        )
    )

    messages = [system_message, *state["messages"]]
    response = await llm_with_tools.ainvoke(messages, config=config)

    # ── HITL: pause if response contains a sensitive tool call ──
    tool_calls = getattr(response, "tool_calls", [])
    pending = [tc for tc in tool_calls if tc["name"] in APPROVAL_REQUIRED]

    if pending:
        tc = pending[0]
        tool_name = tc["name"]
        tool_args = tc["args"]
        summary = _build_summary(tool_name, tool_args)

        # interrupt() pauses the graph here — exactly like reference code
        decision = interrupt(
            {
                "tool_name": tool_name,
                "tool_args": tool_args,
                "summary": summary,
            }
        )

        if not decision.get("approved"):
            # User rejected — return cancellation message, skip tool execution
            return {
                "messages": [
                    AIMessage(
                        content=f"No problem — I've cancelled the {tool_name.replace('_', ' ')}."
                    )
                ]
            }

    return {"messages": [response]}


tool_node = ToolNode(tools) if tools else None


# -------------------
# 7. Checkpointer
# -------------------
async def _init_checkpointer():
    conn = await aiosqlite.connect(database="chatbot.db")
    return AsyncSqliteSaver(conn)


checkpointer = run_async(_init_checkpointer())


# -------------------
# 8. Graph
# -------------------
def route_after_chat(state: ChatState):
    """
    After chat_node runs:
    - if last message has tool calls → go to tools
    - otherwise → END
    This prevents chat_node from being called again after approval resume,
    saving tokens and avoiding double LLM calls.
    """
    last = state["messages"][-1]
    tool_calls = getattr(last, "tool_calls", [])
    if tool_calls:
        return "tools"
    return END


graph = StateGraph(ChatState)
graph.add_node("chat_node", chat_node)
graph.add_edge(START, "chat_node")

if tool_node:
    graph.add_node("tools", tool_node)
    graph.add_conditional_edges(
        "chat_node",
        route_after_chat,
        {
            "tools": "tools",
            END: END,
        },
    )
    graph.add_edge("tools", "chat_node")
else:
    graph.add_edge("chat_node", END)

chatbot = graph.compile(checkpointer=checkpointer)


# -------------------
# 9. Helpers
# -------------------
async def _alist_threads():
    all_threads = set()
    async for checkpoint in checkpointer.alist(None):
        all_threads.add(checkpoint.config["configurable"]["thread_id"])
    return list(all_threads)


def retrieve_all_threads():
    return run_async(_alist_threads())


def thread_has_document(thread_id):
    return str(thread_id) in _THREAD_RETRIEVERS


def thread_document_metadata(thread_id):
    return _THREAD_METADATA.get(str(thread_id), {})

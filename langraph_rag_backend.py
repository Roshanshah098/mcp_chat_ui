from langgraph.graph import StateGraph, START, END
from typing import TypedDict, Annotated, Optional, Dict, Any
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
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
import requests
import asyncio
import threading
import tempfile
import os

load_dotenv()

# Dedicated async loop for backend tasks
_ASYNC_LOOP = asyncio.new_event_loop()
_ASYNC_THREAD = threading.Thread(target=_ASYNC_LOOP.run_forever, daemon=True)
_ASYNC_THREAD.start()


def _submit_async(coro):
    return asyncio.run_coroutine_threadsafe(coro, _ASYNC_LOOP)


def run_async(coro):
    return _submit_async(coro).result()


def submit_async_task(coro):
    """Schedule a coroutine on the backend event loop."""
    return _submit_async(coro)


# -------------------
# 1. LLM + Embeddings
# -------------------
llm = ChatGroq(
    # model="llama-3.3-70b-versatile",
    model="llama-3.1-8b-instant",
    temperature=0.3,
)
embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

# -------------------
# 2. Document retriever store (per thread)
# -------------------
_THREAD_RETRIEVERS: Dict[str, Any] = {}
_THREAD_METADATA: Dict[str, dict] = {}

SUPPORTED_EXTENSIONS = {".pdf", ".docx"}


def _get_retriever(thread_id: Optional[str]):
    if thread_id and thread_id in _THREAD_RETRIEVERS:
        return _THREAD_RETRIEVERS[thread_id]
    return None


def _load_file(file_bytes: bytes, suffix: str, temp_path: str):
    """Load documents from a PDF or DOCX file."""
    if suffix == ".pdf":
        loader = PyPDFLoader(temp_path)
    elif suffix == ".docx":
        loader = Docx2txtLoader(temp_path)
    else:
        raise ValueError(f"Unsupported file type: {suffix}")
    return loader.load()


def ingest_document(
    file_bytes: bytes,
    thread_id: str,
    filename: Optional[str] = None,
) -> dict:
    """
    Build a FAISS retriever for an uploaded PDF or DOCX and store it for the thread.
    Returns a summary dict surfaced in the UI.
    """
    if not file_bytes:
        raise ValueError("No bytes received for ingestion.")

    filename = filename or "document"
    suffix = os.path.splitext(filename)[-1].lower()

    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type '{suffix}'. Use PDF or DOCX.")

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        temp_file.write(file_bytes)
        temp_path = temp_file.name

    try:
        docs = _load_file(file_bytes, suffix, temp_path)

        # Clean text for docx (extra blank lines etc.)
        import re

        for doc in docs:
            text = doc.page_content
            text = re.sub(r"\n{3,}", "\n\n", text)
            text = "\n".join(line.strip() for line in text.splitlines())
            doc.page_content = text.strip()

        total_chars = sum(len(doc.page_content) for doc in docs)

        # Auto chunk size
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

        # Auto k / fetch_k
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

        _THREAD_RETRIEVERS[str(thread_id)] = retriever
        _THREAD_METADATA[str(thread_id)] = {
            "filename": filename,
            "filetype": suffix,
            "documents": len(docs),
            "chunks": total_chunks,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "k": k,
            "fetch_k": fetch_k,
        }

        return _THREAD_METADATA[str(thread_id)]

    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass


# Keep old name as alias so existing calls still work
ingest_pdf = ingest_document


# -------------------
# 3. Tools
# -------------------
search_tool = DuckDuckGoSearchRun(region="us-en")


@tool
def get_stock_price(symbol: str) -> dict:
    """
    Fetch latest stock price for a given symbol (e.g. 'AAPL', 'TSLA')
    using Alpha Vantage.
    """
    url = (
        "https://www.alphavantage.co/query"
        f"?function=GLOBAL_QUOTE&symbol={symbol}"
        f"&apikey={os.getenv('ALPHAVANTAGE_API_KEY')}"
    )
    r = requests.get(url)
    return r.json()


@tool
def rag_tool(query: str, thread_id: Optional[str] = None) -> dict:
    """
    Retrieve relevant information from the uploaded PDF or DOCX for this chat thread.
    Always include the thread_id when calling this tool.
    Use this when the user asks questions about their uploaded document.
    """
    retriever = _get_retriever(thread_id)
    if retriever is None:
        return {
            "error": "No document indexed for this chat. Please upload a PDF or DOCX first.",
            "query": query,
        }

    result = retriever.invoke(query)
    context = [doc.page_content for doc in result]
    metadata = [doc.metadata for doc in result]

    return {
        "query": query,
        "context": context,
        "metadata": metadata,
        "source_file": _THREAD_METADATA.get(str(thread_id), {}).get("filename"),
    }


# -------------------
# MCP Tools
# -------------------
client = MultiServerMCPClient(
    {
        "math": {
            "transport": "streamable_http",
            "url": "https://subhai-mcp-testing.fastmcp.app/mcp",
        },
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

tools = [search_tool, get_stock_price, rag_tool, *mcp_tools]
llm_with_tools = llm.bind_tools(tools) if tools else llm


# -------------------
# 4. State
# -------------------
class ChatState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


# -------------------
# 5. Nodes
# -------------------
async def chat_node(state: ChatState, config=None):
    """LLM node that may answer or request a tool call."""
    thread_id = None
    if config and isinstance(config, dict):
        thread_id = config.get("configurable", {}).get("thread_id")

    has_doc = thread_id and thread_id in _THREAD_RETRIEVERS
    meta = _THREAD_METADATA.get(str(thread_id), {})
    doc_name = meta.get("filename", "")
    filetype = meta.get("filetype", "")

    system_message = SystemMessage(
        content=(
            "You are a helpful assistant with access to multiple tools:\n"
            "- web search (DuckDuckGo)\n"
            "- stock price lookup\n"
            "- math operations (MCP)\n"
            "- expense tracking (MCP)\n"
            + (
                f"- rag_tool: to answer questions from the uploaded "
                f"{'PDF' if filetype == '.pdf' else 'DOCX'} '{doc_name}'. "
                f"Always pass thread_id='{thread_id}' when calling rag_tool.\n"
                if has_doc
                else "- rag_tool: not available yet (no document uploaded for this chat).\n"
            )
            + "\nUse the right tool for the right task. Be concise and helpful."
        )
    )

    messages = [system_message, *state["messages"]]
    response = await llm_with_tools.ainvoke(messages, config=config)
    return {"messages": [response]}


tool_node = ToolNode(tools) if tools else None


# -------------------
# 6. Checkpointer
# -------------------
async def _init_checkpointer():
    conn = await aiosqlite.connect(database="chatbot.db")
    return AsyncSqliteSaver(conn)


checkpointer = run_async(_init_checkpointer())

# -------------------
# 7. Graph
# -------------------
graph = StateGraph(ChatState)
graph.add_node("chat_node", chat_node)
graph.add_edge(START, "chat_node")

if tool_node:
    graph.add_node("tools", tool_node)
    graph.add_conditional_edges("chat_node", tools_condition)
    graph.add_edge("tools", "chat_node")
else:
    graph.add_edge("chat_node", END)

chatbot = graph.compile(checkpointer=checkpointer)


# -------------------
# 8. Helpers
# -------------------
async def _alist_threads():
    all_threads = set()
    async for checkpoint in checkpointer.alist(None):
        all_threads.add(checkpoint.config["configurable"]["thread_id"])
    return list(all_threads)


def retrieve_all_threads():
    return run_async(_alist_threads())


def thread_has_document(thread_id: str) -> bool:
    return str(thread_id) in _THREAD_RETRIEVERS


def thread_document_metadata(thread_id: str) -> dict:
    return _THREAD_METADATA.get(str(thread_id), {})

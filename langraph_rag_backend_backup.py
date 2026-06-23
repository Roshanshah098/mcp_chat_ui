# from langgraph.graph import StateGraph, START, END
# from langgraph.types import interrupt
# from typing import TypedDict, Annotated, Optional, Dict, Any
# from langchain_core.messages import (
#     BaseMessage,
#     HumanMessage,
#     SystemMessage,
#     AIMessage,
#     RemoveMessage,
# )
# from langchain_groq import ChatGroq
# from langchain_huggingface import HuggingFaceEmbeddings
# from langgraph.graph.message import add_messages
# from langgraph.prebuilt import ToolNode
# from langchain_community.tools import DuckDuckGoSearchRun
# from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader
# from langchain_community.vectorstores import Chroma
# from langchain_text_splitters import RecursiveCharacterTextSplitter
# from langchain_core.tools import tool, BaseTool
# from langchain_core.runnables import RunnableConfig
# from langchain_mcp_adapters.client import MultiServerMCPClient
# from langgraph.store.base import BaseStore
# from dotenv import load_dotenv

# from memory_checkpointer_backup import init_stm, init_ltm, _loop as _ASYNC_LOOP
# from memory_store import LongTermMemory
# from translation_subgraph import run_translation

# import asyncio
# import gc
# import itertools
# import shutil
# import sqlite3
# import requests
# import tempfile
# import time
# import json
# import re
# import os

# load_dotenv(override=True)

# os.environ["TRANSFORMERS_VERBOSITY"] = "error"
# os.environ["TOKENIZERS_PARALLELISM"] = "false"


# # Async helpers — reuse the ONE loop from memory_checkpointer
# def _submit_async(coro):
#     return asyncio.run_coroutine_threadsafe(coro, _ASYNC_LOOP)


# def run_async(coro):
#     return _submit_async(coro).result()


# def submit_async_task(coro):
#     return _submit_async(coro)


# # 1. LLM + Embeddings  (multi-key rotation with auto-fallback)
# _RAW_KEYS = os.getenv("GROQ_API_KEYS", os.getenv("GROQ_API_KEY", ""))
# _GROQ_KEYS: list[str] = [k.strip() for k in _RAW_KEYS.split(",") if k.strip()]

# if not _GROQ_KEYS:
#     raise EnvironmentError(
#         "No Groq API key found. Set GROQ_API_KEYS or GROQ_API_KEY in your .env file."
#     )

# print(f"[Groq] Loaded {len(_GROQ_KEYS)} API key(s) for rotation.")

# # Separate cycles for chat LLM and memory LLM so they don't share the same cursor
# _chat_key_cycle = itertools.cycle(_GROQ_KEYS)
# _mem_key_cycle = itertools.cycle(_GROQ_KEYS)

# _GROQ_MODEL = "llama-3.3-70b-versatile"
# _RATE_LIMIT_CODES = {"rate_limit_exceeded", "429"}


# def _make_chat_llm(temperature: float = 0.3) -> ChatGroq:
#     """Create a ChatGroq instance using the next key in the rotation."""
#     return ChatGroq(
#         model=_GROQ_MODEL,
#         temperature=temperature,
#         api_key=next(_chat_key_cycle),
#     )


# def _make_mem_llm(temperature: float = 0) -> ChatGroq:
#     """Create a ChatGroq memory LLM using the next key in the rotation."""
#     return ChatGroq(
#         model=_GROQ_MODEL,
#         temperature=temperature,
#         api_key=next(_mem_key_cycle),
#     )


# def _is_rate_limit(exc: Exception) -> bool:
#     msg = str(exc).lower()
#     return (
#         "rate_limit_exceeded" in msg
#         or '"code": "rate_limit_exceeded"' in msg
#         or "429" in msg
#     )


# async def _invoke_with_fallback(messages, config=None, tools_bound_llm=None):
#     """
#     Try every available key in order.  On a rate-limit error rotate to the
#     next key and retry; on any other error re-raise immediately.
#     """
#     tried = 0
#     last_exc = None
#     total = len(_GROQ_KEYS)

#     while tried < total:
#         try:
#             candidate = tools_bound_llm or _make_chat_llm()
#             if config:
#                 return await candidate.ainvoke(messages, config=config)
#             return await candidate.ainvoke(messages)
#         except Exception as exc:
#             if _is_rate_limit(exc):
#                 tried += 1
#                 last_exc = exc
#                 key_preview = _GROQ_KEYS[(tried - 1) % total][:8]
#                 print(
#                     f"[Groq] Rate limit on key …{key_preview} "
#                     f"({tried}/{total}), rotating…"
#                 )
#                 # Advance both cycles to stay in sync
#                 next(_chat_key_cycle)
#             else:
#                 raise

#     print("[Groq] All keys exhausted — raising last rate-limit error.")
#     raise last_exc


# # Initial LLM instances (used at module load for binding tools etc.)
# llm = _make_chat_llm(temperature=0.3)
# memory_llm = _make_mem_llm(temperature=0)
# embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

# # =============================================================
# # 2. Memory init
# # =============================================================
# checkpointer = init_stm()
# _pg_store = init_ltm()
# ltm = LongTermMemory(
#     llm=memory_llm,
#     key_factory=_make_mem_llm,
#     max_retries=len(_GROQ_KEYS),
# )

# # =============================================================
# # 3. System prompt
# # =============================================================
# SYSTEM_PROMPT = """You are a helpful friendly assistant with memory capabilities.
# {user_context}

# Tools: search_tool, get_stock_price, calculator, add_expense, list_expenses,
#        edit_expense, delete_expense, add_credit, list_credits, summarize{rag_context}

# Rules:
# - ONE tool call at a time
# - If user mentions multiple expenses, add them one by one across turns
# - For edit/delete call list_expenses first to find the id
# - If no date mentioned use today's date
# - Never show raw JSON
# - Be concise and friendly
# - If you know the user's name address them naturally
# - Always respond in English internally — a separate translation step will
#   convert your response to the user's language automatically.
# - ONLY call a tool when the user EXPLICITLY and directly requests it.
# - NEVER call any tool during: greetings, casual chat, emotional support,
#   venting, laughter, compliments, or any message that is not a direct
#   tool request. Just reply with plain conversational text.
# - NEVER suggest using a tool or mention expenses/calculations unprompted.
# - If unsure whether to call a tool — do NOT call it. Just talk.
# """

# # =============================================================
# # 4. Document store (SQLite + ChromaDB — per-thread RAG)
# # =============================================================
# _THREAD_RETRIEVERS: Dict[str, Any] = {}
# _THREAD_METADATA: Dict[str, dict] = {}
# _THREAD_VECTORSTORES: Dict[str, Any] = {}  # ← NEW: keeps Chroma instances for cleanup
# SUPPORTED_EXTENSIONS = {".pdf", ".docx"}
# DOC_DB = "chatbot.db"
# CHROMA_BASE_DIR = "./chroma_db"
# APPROVAL_REQUIRED = {"add_expense", "edit_expense", "delete_expense", "add_credit"}
# STM_SUMMARIZE_AFTER = 10


# def _doc_db_conn():
#     conn = sqlite3.connect(DOC_DB, check_same_thread=False)
#     conn.execute("""
#         CREATE TABLE IF NOT EXISTS thread_documents (
#             thread_id  TEXT PRIMARY KEY,
#             filename   TEXT NOT NULL,
#             filetype   TEXT NOT NULL,
#             metadata   TEXT NOT NULL,
#             file_blob  BLOB NOT NULL
#         )
#     """)
#     conn.commit()
#     return conn


# _doc_conn = _doc_db_conn()


# def _save_doc_to_db(thread_id, filename, filetype, metadata, file_bytes):
#     _doc_conn.execute(
#         "INSERT OR REPLACE INTO thread_documents "
#         "(thread_id,filename,filetype,metadata,file_blob) VALUES (?,?,?,?,?)",
#         (thread_id, filename, filetype, json.dumps(metadata), file_bytes),
#     )
#     _doc_conn.commit()


# def _delete_doc_from_db(thread_id):
#     _doc_conn.execute("DELETE FROM thread_documents WHERE thread_id=?", (thread_id,))
#     _doc_conn.commit()


# def _load_all_docs_from_db():
#     rows = _doc_conn.execute(
#         "SELECT thread_id, filename, filetype, metadata, file_blob FROM thread_documents"
#     ).fetchall()
#     for tid, fname, ftype, meta_json, fbytes in rows:
#         try:
#             _rebuild_retriever(tid, fname, ftype, fbytes, json.loads(meta_json))
#         except Exception as e:
#             print(f"[warn] Could not reload doc for thread {tid}: {e}")


# # =============================================================
# # Helper: safely release a Chroma vectorstore on Windows
# # =============================================================
# def _release_chroma(thread_id: str):
#     """
#     Close the Chroma client for this thread so Windows releases all
#     file handles before we attempt to delete the persist directory.
#     """
#     old_vs = _THREAD_VECTORSTORES.pop(thread_id, None)
#     if old_vs is not None:
#         try:
#             # ChromaDB ≥ 0.4 exposes the underlying system via _client._system
#             old_vs._client._system.stop()
#         except Exception:
#             pass
#         try:
#             # Fallback for older versions
#             old_vs._client.reset()
#         except Exception:
#             pass
#         del old_vs
#     gc.collect()


# def _safe_rmtree(path: str, retries: int = 3, delay: float = 0.4):
#     """
#     Attempt shutil.rmtree up to `retries` times with a short sleep between
#     attempts.  On Windows, file handles can linger briefly even after the
#     Chroma client is stopped, so retrying usually succeeds.
#     """
#     for attempt in range(retries):
#         try:
#             shutil.rmtree(path)
#             return  # success
#         except PermissionError:
#             if attempt < retries - 1:
#                 time.sleep(delay)
#             else:
#                 # Last resort: ignore errors so the upload can still proceed
#                 shutil.rmtree(path, ignore_errors=True)


# def _rebuild_retriever(thread_id, filename, filetype, file_bytes, meta):
#     with tempfile.NamedTemporaryFile(delete=False, suffix=filetype) as f:
#         f.write(file_bytes)
#         temp_path = f.name
#     try:
#         loader = (
#             PyPDFLoader(temp_path) if filetype == ".pdf" else Docx2txtLoader(temp_path)
#         )
#         docs = loader.load()
#         for doc in docs:
#             text = re.sub(r"\n{3,}", "\n\n", doc.page_content)
#             doc.page_content = "\n".join(
#                 line.strip() for line in text.splitlines()
#             ).strip()
#         splitter = RecursiveCharacterTextSplitter(
#             chunk_size=meta.get("chunk_size", 1000),
#             chunk_overlap=meta.get("chunk_overlap", 200),
#             separators=["\n\n", "\n", " ", ""],
#         )
#         chunks = splitter.split_documents(docs)
#         persist_dir = os.path.join(CHROMA_BASE_DIR, str(thread_id))
#         vs = Chroma.from_documents(
#             chunks,
#             embeddings,
#             persist_directory=persist_dir,
#         )
#         retr = vs.as_retriever(
#             search_type="mmr",
#             search_kwargs={"k": meta.get("k", 4), "fetch_k": meta.get("fetch_k", 20)},
#         )
#         _THREAD_VECTORSTORES[str(thread_id)] = vs  # ← NEW
#         _THREAD_RETRIEVERS[str(thread_id)] = retr
#         _THREAD_METADATA[str(thread_id)] = meta
#     finally:
#         try:
#             os.remove(temp_path)
#         except OSError:
#             pass


# def _get_retriever(thread_id):
#     return _THREAD_RETRIEVERS.get(str(thread_id)) if thread_id else None


# def ingest_document(file_bytes, thread_id, filename=None):
#     if not file_bytes:
#         raise ValueError("No bytes received.")
#     filename = filename or "document"
#     suffix = os.path.splitext(filename)[-1].lower()
#     if suffix not in SUPPORTED_EXTENSIONS:
#         raise ValueError(f"Unsupported file type '{suffix}'. Use PDF or DOCX.")

#     with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
#         f.write(file_bytes)
#         temp_path = f.name
#     try:
#         loader = (
#             PyPDFLoader(temp_path) if suffix == ".pdf" else Docx2txtLoader(temp_path)
#         )
#         docs = loader.load()
#         for doc in docs:
#             text = re.sub(r"\n{3,}", "\n\n", doc.page_content)
#             doc.page_content = "\n".join(
#                 line.strip() for line in text.splitlines()
#             ).strip()

#         total_chars = sum(len(d.page_content) for d in docs)
#         if total_chars < 5_000:
#             cs, co = 500, 50
#         elif total_chars < 20_000:
#             cs, co = 800, 150
#         elif total_chars < 50_000:
#             cs, co = 1000, 200
#         elif total_chars < 100_000:
#             cs, co = 1200, 250
#         else:
#             cs, co = 1500, 300

#         splitter = RecursiveCharacterTextSplitter(
#             chunk_size=cs,
#             chunk_overlap=co,
#             separators=["\n\n", "\n", " ", ""],
#         )
#         chunks = splitter.split_documents(docs)
#         n = len(chunks)
#         if n < 20:
#             k, fk = 4, 10
#         elif n < 50:
#             k, fk = 4, 20
#         elif n < 100:
#             k, fk = 5, 25
#         elif n < 200:
#             k, fk = 6, 30
#         else:
#             k, fk = 8, 40

#         persist_dir = os.path.join(CHROMA_BASE_DIR, str(thread_id))

#         # ── FIX: release old Chroma handles before deleting directory ──
#         _release_chroma(str(thread_id))
#         if os.path.exists(persist_dir):
#             _safe_rmtree(persist_dir)

#         vs = Chroma.from_documents(
#             chunks,
#             embeddings,
#             persist_directory=persist_dir,
#         )
#         retr = vs.as_retriever(search_type="mmr", search_kwargs={"k": k, "fetch_k": fk})

#         meta = {
#             "filename": filename,
#             "filetype": suffix,
#             "documents": len(docs),
#             "chunks": n,
#             "chunk_size": cs,
#             "chunk_overlap": co,
#             "k": k,
#             "fetch_k": fk,
#         }
#         _THREAD_VECTORSTORES[str(thread_id)] = vs  # ← NEW
#         _THREAD_RETRIEVERS[str(thread_id)] = retr
#         _THREAD_METADATA[str(thread_id)] = meta
#         _save_doc_to_db(str(thread_id), filename, suffix, meta, file_bytes)
#         return meta
#     finally:
#         try:
#             os.remove(temp_path)
#         except OSError:
#             pass


# def remove_document(thread_id):
#     tid = str(thread_id)

#     # ── FIX: shut down Chroma client before removing files ──
#     _release_chroma(tid)

#     _THREAD_RETRIEVERS.pop(tid, None)
#     _THREAD_METADATA.pop(tid, None)
#     _delete_doc_from_db(tid)

#     chroma_path = os.path.join(CHROMA_BASE_DIR, tid)
#     if os.path.exists(chroma_path):
#         _safe_rmtree(chroma_path)
#         print(f"[Chroma] removed persist dir for thread {tid}")


# ingest_pdf = ingest_document
# _load_all_docs_from_db()


# # =============================================================
# # 5. Chat title store
# # =============================================================
# def _init_title_table():
#     _doc_conn.execute("""
#         CREATE TABLE IF NOT EXISTS thread_titles (
#             thread_id TEXT PRIMARY KEY,
#             title     TEXT NOT NULL
#         )
#     """)
#     _doc_conn.commit()


# _init_title_table()


# def save_thread_title(thread_id, title):
#     _doc_conn.execute(
#         "INSERT OR IGNORE INTO thread_titles (thread_id, title) VALUES (?, ?)",
#         (str(thread_id), title),
#     )
#     _doc_conn.commit()


# def get_all_thread_titles():
#     return {
#         r[0]: r[1]
#         for r in _doc_conn.execute(
#             "SELECT thread_id, title FROM thread_titles"
#         ).fetchall()
#     }


# # =============================================================
# # 6. Tools
# # =============================================================
# search_tool = DuckDuckGoSearchRun(region="us-en")


# @tool
# def get_stock_price(symbol: str) -> dict:
#     """Fetch latest stock price for a given symbol e.g. 'AAPL', 'TSLA'."""
#     url = (
#         "https://www.alphavantage.co/query"
#         f"?function=GLOBAL_QUOTE&symbol={symbol}"
#         f"&apikey={os.getenv('ALPHAVANTAGE_API_KEY')}"
#     )
#     return requests.get(url).json()


# @tool
# def calculator(expression: str) -> dict:
#     """
#     Evaluate a math expression like '2 + 2', '10 * 5', '100 / 4'.
#     Supports +, -, *, /, ** (power), % (modulo).
#     Always use this for any math question.
#     """
#     try:
#         allowed = set("0123456789+-*/.() %**")
#         if not all(c in allowed for c in expression.replace(" ", "")):
#             return {"error": "Invalid characters in expression"}
#         result = eval(expression, {"__builtins__": {}})
#         return {"expression": expression, "result": result}
#     except Exception as e:
#         return {"error": str(e)}


# @tool
# def rag_tool(query: str, thread_id: Optional[str] = None) -> dict:
#     """
#     Retrieve relevant information from uploaded PDF or DOCX for this chat thread.
#     Always pass thread_id when calling this tool.
#     """
#     retr = _get_retriever(thread_id)
#     if retr is None:
#         return {
#             "error": "No document indexed. Please upload a PDF or DOCX first.",
#             "query": query,
#         }
#     result = retr.invoke(query)
#     return {
#         "query": query,
#         "context": [doc.page_content for doc in result],
#         "metadata": [doc.metadata for doc in result],
#         "source_file": _THREAD_METADATA.get(str(thread_id), {}).get("filename"),
#     }


# client = MultiServerMCPClient(
#     {
#         "expense": {
#             "transport": "stdio",
#             "command": "C:/Users/Hp/AppData/Local/Programs/Python/Python312/Scripts/uv.exe",
#             "args": [
#                 "run",
#                 "--with",
#                 "fastmcp",
#                 "fastmcp",
#                 "run",
#                 "E:/langgrapph_chat_ui/expense_server.py",
#             ],
#         },
#     }
# )


# def load_mcp_tools() -> list[BaseTool]:
#     try:
#         return run_async(client.get_tools())
#     except Exception as e:
#         print(f"[warn] Could not load MCP tools: {e}")
#         return []


# mcp_tools = load_mcp_tools()
# tools = [search_tool, get_stock_price, calculator, rag_tool, *mcp_tools]
# llm_with_tools = llm.bind_tools(tools) if tools else llm


# # =============================================================
# # 7. State
# # =============================================================
# class ChatState(TypedDict):
#     messages: Annotated[list[BaseMessage], add_messages]
#     summary: str
#     detected_language: str


# # =============================================================
# # 8. Nodes
# # =============================================================
# def _build_summary(tool_name: str, tool_args: dict) -> str:
#     if tool_name == "add_expense":
#         return (
#             f"Add expense of **${tool_args.get('amount')}** "
#             f"for **{tool_args.get('category', 'unknown')}** "
#             f"on {tool_args.get('date', 'today')}"
#         )
#     elif tool_name == "edit_expense":
#         changes = {k: v for k, v in tool_args.items() if k != "id" and v is not None}
#         return f"Edit expense ID **{tool_args.get('id')}** → {changes}"
#     elif tool_name == "delete_expense":
#         return f"Permanently delete expense ID **{tool_args.get('id')}**"
#     elif tool_name == "add_credit":
#         return (
#             f"Add income of **${tool_args.get('amount')}** "
#             f"from **{tool_args.get('source', 'unknown')}** "
#             f"on {tool_args.get('date', 'today')}"
#         )
#     return f"Run `{tool_name}` with {tool_args}"


# def remember_node(state: ChatState, config: RunnableConfig, *, store: BaseStore):
#     """Save memorable facts from the user message to long-term memory.

#     Key rotation is handled inside LongTermMemory.extract_and_save() via the
#     key_factory passed at init — no retry logic needed here.
#     """
#     if store is None:
#         return {}
#     user_id = config.get("configurable", {}).get("user_id", "default_user")
#     last_human = next(
#         (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
#         None,
#     )
#     if last_human:
#         ltm.extract_and_save(store, user_id, last_human.content)
#     return {}


# async def summarize_node(state: ChatState) -> dict:
#     existing_summary = state.get("summary", "")
#     messages = state["messages"]

#     if existing_summary:
#         prompt = (
#             f"Existing summary:\n{existing_summary}\n\n"
#             "Extend this summary with the new messages above. "
#             "Be concise. Write in English only. Return only the summary text."
#         )
#     else:
#         prompt = (
#             "Summarize the conversation above concisely in English. "
#             "Preserve key facts, requests, tool results, and decisions. "
#             "Return only the summary text."
#         )

#     _sum_msgs = [
#         SystemMessage(
#             content="You are a conversation summarizer. Return only the summary text, no commentary."
#         ),
#         *messages,
#         HumanMessage(content=prompt),
#     ]
#     # Use key rotation so summarization doesn't compete with chat on the same key
#     tried, last_exc = 0, None
#     while tried < len(_GROQ_KEYS):
#         try:
#             _summarizer = _make_mem_llm(temperature=0)
#             response = await _summarizer.ainvoke(_sum_msgs)
#             break
#         except Exception as exc:
#             if _is_rate_limit(exc):
#                 tried += 1
#                 last_exc = exc
#                 print(
#                     f"[Groq/summarize] Rate limit, rotating key ({tried}/{len(_GROQ_KEYS)})…"
#                 )
#             else:
#                 raise
#     else:
#         raise last_exc

#     messages_to_delete = messages[:-2]
#     deletions = [RemoveMessage(id=m.id) for m in messages_to_delete]
#     print(f"[STM] Summarized {len(messages_to_delete)} messages → kept last 2")

#     return {
#         "summary": response.content.strip(),
#         "messages": deletions,
#     }


# async def chat_node(state: ChatState, config: RunnableConfig, *, store: BaseStore):
#     thread_id = config.get("configurable", {}).get("thread_id")
#     user_id = config.get("configurable", {}).get("user_id", "default_user")
#     has_doc = thread_id and thread_id in _THREAD_RETRIEVERS
#     meta = _THREAD_METADATA.get(str(thread_id), {})
#     doc_name = meta.get("filename", "")

#     last_human = next(
#         (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
#         None,
#     )
#     query = last_human.content if last_human else ""
#     user_memories = ltm.fetch(store, user_id, query=query) if store else ""
#     user_context = (
#         f"What I know about you:\n{user_memories}\nUse this to personalize your responses."
#         if user_memories
#         else ""
#     )
#     rag_context = (
#         f", rag_tool (use for doc '{doc_name}', always pass thread_id='{thread_id}')"
#         if has_doc
#         else ""
#     )

#     summary = state.get("summary", "")
#     summary_context = (
#         f"\n\nSummary of earlier conversation:\n{summary}" if summary else ""
#     )

#     system_message = SystemMessage(
#         content=SYSTEM_PROMPT.format(
#             user_context=user_context,
#             rag_context=rag_context,
#         )
#         + summary_context
#     )

#     messages = [system_message, *state["messages"]]
#     response = await _invoke_with_fallback(
#         messages, config=config, tools_bound_llm=llm_with_tools
#     )

#     tool_calls = getattr(response, "tool_calls", [])
#     pending = [tc for tc in tool_calls if tc["name"] in APPROVAL_REQUIRED]
#     if pending:
#         tc = pending[0]
#         tool_name = tc["name"]
#         tool_args = tc["args"]
#         summary_text = _build_summary(tool_name, tool_args)
#         decision = interrupt(
#             {
#                 "tool_name": tool_name,
#                 "tool_args": tool_args,
#                 "summary": summary_text,
#             }
#         )
#         if not decision.get("approved"):
#             return {
#                 "messages": [
#                     AIMessage(
#                         content=f"No problem — I've canceled the {tool_name.replace('_', ' ')}."
#                     )
#                 ]
#             }

#     return {"messages": [response]}


# _ENGLISH_OVERRIDES = [
#     "talk in english",
#     "speak english",
#     "speak in english",
#     "reply in english",
#     "respond in english",
#     "write in english",
#     "use english",
#     "in english",
#     "english only",
#     "english please",
#     "switch to english",
#     "back to english",
#     "type in english",
# ]

# _ROMANIZED_TRIGGERS = [
#     "tapai",
#     "timi",
#     "maaile",
#     "bhai",
#     "ksto",
#     "k xa",
#     "k gaardaixau",
#     "namaste",
#     "kya hal",
#     "theek hai",
#     "kaise",
#     "sathi",
#     "yaar",
#     "hajur",
#     "haina",
#     "garcha",
#     "garnu",
#     "sunnu",
#     "hunchha",
# ]


# async def translate_node(state: ChatState) -> dict:
#     messages = state["messages"]

#     last_human = next(
#         (m for m in reversed(messages) if isinstance(m, HumanMessage)), None
#     )
#     last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)

#     if not last_human or not last_ai:
#         return {}
#     if getattr(last_ai, "tool_calls", []):
#         return {}
#     if not last_ai.content:
#         return {}

#     user_msg = last_human.content.strip()
#     ai_text = last_ai.content
#     lower_msg = user_msg.lower()

#     if any(phrase in lower_msg for phrase in _ENGLISH_OVERRIDES):
#         print("[translate_node] English override — skipping translation")
#         return {}

#     has_devanagari = bool(re.search(r"[\u0900-\u097F]", user_msg))
#     has_romanized = any(t in lower_msg for t in _ROMANIZED_TRIGGERS)

#     if not has_devanagari and not has_romanized:
#         return {}

#     try:
#         translated = await run_translation(user_msg, ai_text)
#     except Exception as e:
#         print(f"[translate_node] Error, keeping original: {e}")
#         return {}

#     if translated == ai_text:
#         return {}

#     def _space_ratio(t: str) -> float:
#         return t.count(" ") / max(len(t), 1)

#     if _space_ratio(ai_text) > 0.05 and _space_ratio(translated) < 0.02:
#         print("[translate_node] Corrupted translation discarded — keeping original")
#         return {}

#     translated_message = AIMessage(
#         content=translated,
#         id=last_ai.id,
#     )
#     return {
#         "messages": [RemoveMessage(id=last_ai.id), translated_message],
#         "detected_language": "non-english",
#     }


# tool_node = ToolNode(tools) if tools else None


# # =============================================================
# # 9. Graph
# # =============================================================
# def route_after_chat(state: ChatState):
#     last = state["messages"][-1]
#     if getattr(last, "tool_calls", []):
#         return "tools"
#     return "translate"


# def route_after_translate(state: ChatState):
#     if len(state["messages"]) > STM_SUMMARIZE_AFTER:
#         return "summarize"
#     return END


# graph = StateGraph(ChatState)
# graph.add_node("remember", remember_node)
# graph.add_node("chat_node", chat_node)
# graph.add_node("translate", translate_node)
# graph.add_node("summarize", summarize_node)

# graph.add_edge(START, "remember")
# graph.add_edge("remember", "chat_node")

# if tool_node:
#     graph.add_node("tools", tool_node)
#     graph.add_conditional_edges(
#         "chat_node",
#         route_after_chat,
#         {"tools": "tools", "translate": "translate"},
#     )
#     graph.add_edge("tools", "chat_node")
# else:
#     graph.add_conditional_edges(
#         "chat_node",
#         route_after_chat,
#         {"translate": "translate"},
#     )

# graph.add_conditional_edges(
#     "translate",
#     route_after_translate,
#     {"summarize": "summarize", END: END},
# )
# graph.add_edge("summarize", END)

# chatbot = graph.compile(
#     checkpointer=checkpointer,
#     store=_pg_store,
# )


# # =============================================================
# # 10. Helpers
# # =============================================================
# def retrieve_all_threads():
#     try:
#         all_threads = set()
#         for checkpoint in checkpointer.list(None):
#             all_threads.add(checkpoint.config["configurable"]["thread_id"])
#         return list(all_threads)
#     except Exception:
#         return []


# def thread_has_document(thread_id):
#     return str(thread_id) in _THREAD_RETRIEVERS


# def thread_document_metadata(thread_id):
#     return _THREAD_METADATA.get(str(thread_id), {})


# def get_user_memories(user_id: str = "default_user") -> list[str]:
#     if _pg_store is None:
#         return []
#     return ltm.get_all(_pg_store, user_id)

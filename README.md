# MCP Chat — Agentic RAG Chatbot with Multilingual Support & AI Blog Generation

An agentic AI system built with **LangGraph** and **Groq**, wrapped in a multi-page **Streamlit** app. It chats with your uploaded PDF/DOCX files, tracks expenses with human-in-the-loop approval, searches the web, checks stock prices, auto-translates for Nepali/Hindi/Sanskrit speakers, remembers facts about you across sessions, and generates fully illustrated blog posts end-to-end (research → outline → parallel section writing → image generation).

**Repo:** [github.com/Roshanshah098/mcp_chat_ui](https://github.com/Roshanshah098/mcp_chat_ui)

---

## Table of Contents

- [Features](#features)
- [Tech Stack](#tech-stack)
- [Chat Graph Architecture](#chat-graph-architecture)
- [Blog Generation Graph Architecture](#blog-generation-graph-architecture)
- [MCP (Model Context Protocol) Architecture](#mcp-model-context-protocol-architecture)
- [RAG Workflow](#rag-workflow)
- [Image Generation Pipeline](#image-generation-pipeline)
- [Memory System](#memory-system)
- [Multi-Key Rotation & Rate Limiting](#multi-key-rotation--rate-limiting)
- [Project Structure](#project-structure)
- [Setup](#setup)
- [Environment Variables](#environment-variables)
- [Usage](#usage)
- [Notes & Gotchas](#notes--gotchas)

---

## Features

- **Document Q&A (RAG)** — Upload a PDF or DOCX and ask questions about it. Adaptive chunking based on document size, **ChromaDB** MMR retrieval, HuggingFace embeddings, persisted per-thread so documents survive restarts.
- **Long-Term Memory (LTM)** — Extracts and remembers durable facts (name, projects, preferences, tools you use) across every conversation, backed by a **PostgreSQL store**. Pre-filters greetings/small talk before ever calling the LLM, and deduplicates against what's already stored.
- **Short-Term Memory (STM)** — Per-thread conversation state via LangGraph's `AsyncPostgresSaver` checkpointer (SQLite fallback if Postgres is unavailable). Auto-summarizes once a thread passes 10 messages so context stays small.
- **Web Search** — DuckDuckGo search for real-time information.
- **Stock Price Lookup** — Live quotes via Alpha Vantage.
- **Calculator** — Sandboxed arithmetic evaluation (no hallucinated math).
- **Expense Tracking with HITL** — Add/edit/delete expenses and income via a local MCP server. Mutating actions pause the graph with `interrupt()` and require an explicit Approve/Reject click in the UI before executing.
- **Multi-Session Chat** — Sidebar thread list grouped by date (Today/Yesterday/Earlier), auto-generated titles from your first message, soft-delete so removed threads don't reappear.
- **Multilingual Auto-Translation** — Detects Devanagari script or Romanized Nepali/Hindi trigger words and transparently translates the AI's English reply into Nepali, Hindi, or Sanskrit via a dedicated LangGraph subgraph. Includes corruption detection (falls back to English if the translated output looks garbled) and an explicit "reply in English" override.
- **AI Blog Generator** — Give it a topic; it decides whether the topic needs live research, plans a multi-section outline, writes sections in parallel, and illustrates the result with AI-generated images — exportable as Markdown or PDF.
- **Live Analytics Dashboard** — Message counts, topic breakdown (donut chart), vocabulary heatmap, per-thread activity, all computed live from the checkpointer/SQLite — no separate analytics database.
- **Multi-Key Groq Rotation** — Every LLM call path (chat, memory extraction, translation, blog writing) rotates across comma-separated Groq API keys and retries with backoff on rate limits.

---

## Tech Stack

| Layer                    | Technology                                                                         |
| ------------------------ | ---------------------------------------------------------------------------------- |
| LLM                      | Groq — `llama-3.3-70b-versatile` (multi-key rotation across every subsystem)       |
| Agent Framework          | LangGraph (`StateGraph`, subgraphs, `Send` fan-out, `interrupt`/`Command`)         |
| Vector Store             | ChromaDB (persistent, local, per-thread collections)                               |
| Embeddings               | HuggingFace `sentence-transformers/all-MiniLM-L6-v2`                               |
| Short-Term Memory        | LangGraph `AsyncPostgresSaver` (PostgreSQL), SQLite `AsyncSqliteSaver` fallback    |
| Long-Term Memory         | LangGraph `PostgresStore` (PostgreSQL)                                             |
| MCP Client               | `langchain-mcp-adapters` (`MultiServerMCPClient`, stdio transport via `uv`)        |
| Frontend                 | Streamlit (multipage: Dashboard / Chat / Blog Generator)                           |
| Dashboard Charts         | Plotly (donut, horizontal bar, gauge, sparkline)                                   |
| Metadata / Titles / Docs | SQLite (`chatbot.db`)                                                              |
| Expense Data             | SQLite (`expenses.db`, via MCP server)                                             |
| Web Search (chat)        | DuckDuckGo (`duckduckgo-search`)                                                   |
| Web Research (blog)      | Tavily Search API, DuckDuckGo fallback                                             |
| Stock Prices             | Alpha Vantage API                                                                  |
| Translation              | Dedicated LangGraph subgraph, Groq LLM (detect → translate → sanity-check)         |
| HITL                     | LangGraph `interrupt()` + `Command(resume=...)`                                    |
| Image Generation         | HuggingFace Inference (FLUX.1) → Pollinations AI → Google Imagen (3-tier fallback) |
| PDF Export (blog)        | ReportLab (optional, lazy-imported)                                                |
| Document Loaders         | `PyPDFLoader`, `Docx2txtLoader`                                                    |
| Text Splitting           | `RecursiveCharacterTextSplitter` (adaptive chunk size/overlap by doc length)       |

---

## Chat Graph Architecture

```
START
  └─► remember          ← extracts + saves LTM facts from the latest user message
        └─► chat_node    ← Groq LLM w/ bound tools; may request tool calls
              │
              ├─(tool_calls present)─► tools ──► chat_node   (loops until no more tool calls)
              │
              └─(no tool_calls)──────► translate
                                            │
                                            ├─(> STM_SUMMARIZE_AFTER msgs)─► summarize ─► END
                                            └─(else)───────────────────────────────────► END
```

**Nodes:**

- **`remember`** — Pulls the latest human message, runs it through `LongTermMemory.extract_and_save()`, which pre-filters obvious non-facts (greetings, one-word replies, short Devanagari small talk) before ever calling the LLM, then extracts atomic facts and deduplicates against existing memory.
- **`chat_node`** — Builds the system prompt with injected LTM context and RAG availability info, invokes the LLM with tools bound. If the model calls `add_expense`/`edit_expense`/`delete_expense`/`add_credit`, the graph pauses via `interrupt()` and surfaces an Approve/Reject card in the UI; on approval it resumes with `Command(resume={"approved": True/False})`.
- **`tools`** — A LangGraph `ToolNode` executing whichever tool was requested: web search, stock price, calculator, RAG retrieval, or any MCP-provided tool.
- **`translate`** — Detects Devanagari script or Romanized Nepali/Hindi trigger words in the _user's_ message (skipped entirely if the user asked for English), translates the _AI's_ reply via the translation subgraph, and discards the translation (falling back to English) if it looks corrupted (space-ratio sanity check).
- **`summarize`** — Once a thread exceeds `STM_SUMMARIZE_AFTER` (10) messages, condenses everything except the last 2 messages into a running summary and issues `RemoveMessage` deletions to keep the checkpointer state small.

---

## Blog Generation Graph Architecture

The blog generator is a **separate LangGraph app** (`blog_app`) with its own state and a nested reducer subgraph, invoked synchronously from the UI via `generate_blog(topic)`.

```
START
  └─► blog_router          ← decides: closed_book / hybrid / open_book, and research queries
        │
        ├─(needs_research)──► blog_research ──► blog_orchestrator
        └─(no research)──────────────────────► blog_orchestrator
                                                      │
                                                      ▼
                                          blog_fanout (Send per task)
                                                      │
                                          ┌───────────┴───────────┐
                                          ▼           ▼           ▼
                                    blog_worker  blog_worker  blog_worker   (parallel, one per section)
                                          │           │           │
                                          └───────────┬───────────┘
                                                      ▼
                                              blog_reducer (subgraph)
                                          ┌────────────────────────────┐
                                          │ blog_merge_content          │
                                          │        ↓                    │
                                          │ blog_decide_images          │
                                          │        ↓                    │
                                          │ blog_generate_and_place_images │
                                          └────────────────────────────┘
                                                      ▼
                                                     END
```

**Nodes:**

- **`blog_router`** — Structured-output call classifies the topic as `closed_book` (evergreen, no research needed), `hybrid` (evergreen + needs current examples), or `open_book` (news/pricing/"latest" — needs fresh research), and generates 3–10 scoped search queries plus a recency window.
- **`blog_research`** — Runs each query through **Tavily** (primary); if Tavily returns nothing (no API key or failure), falls back to **DuckDuckGo**. Results are deduplicated by URL and normalized into `BlogEvidenceItem` objects (title, url, snippet, published date, source domain).
- **`blog_orchestrator`** — Structured-output call produces a `BlogPlan`: title, audience, tone, blog kind (`explainer`/`tutorial`/`news_roundup`/`comparison`/`system_design`), and 5–9 `BlogTask`s each with 3–6 actionable bullets and a target word count. Includes anti-hallucination guardrails (use the topic name verbatim, don't "correct" real proper nouns).
- **`blog_fanout` → `blog_worker`** — Uses LangGraph's `Send` API to fan out one worker per planned section, running in parallel. Each worker writes a fully-cited Markdown section (superscript `[N]` citations tied to the evidence pack, truncated to protect against TPM rate limits) using the sync Groq call with exponential backoff (Groq limits are per-organization, so key rotation alone isn't enough here).
- **`blog_reducer`** (subgraph) —
  - `blog_merge_content`: stitches sections in task order, builds a table of contents, adds intro/conclusion.
  - `blog_decide_images`: structured-output call inserts `[[IMAGE_N]]` placeholders (1–3 per post) with detailed prompts, styled by topic type (technical vs. entertainment vs. news). A hero-image fallback is force-injected if the LLM ever returns zero images.
  - `blog_generate_and_place_images`: generates each image via the [image pipeline](#image-generation-pipeline), saves the file to `blogs/images/`, base64-embeds it as an inline `<img>` tag in the Markdown (so it renders correctly inside Streamlit), and writes the final `.md` + `_meta.json` to `blogs/`.

---

## MCP (Model Context Protocol) Architecture

The app connects to external tool servers using `langchain-mcp-adapters`' `MultiServerMCPClient`, configured with a dict of named servers:

```python
client = MultiServerMCPClient({
    "expense": {
        "transport": "stdio",
        "command": "path/to/uv.exe",
        "args": ["run", "--with", "fastmcp", "fastmcp", "run", "path/to/expense_server.py"],
    },
})
```

- **Transport**: `stdio` — the MCP server is spawned as a local subprocess (via `uv run fastmcp ...`) and communicates over stdin/stdout using JSON-RPC 2.0. This keeps the expense server's SQLite database and business logic fully decoupled from the chat backend.
- **Tool discovery**: `client.get_tools()` is called once at startup (`load_mcp_tools()`), converting every tool exposed by the MCP server into LangChain `BaseTool` objects, which are then merged with the local tools (`search_tool`, `get_stock_price`, `calculator`, `rag_tool`) and bound to the LLM as one flat tool list.
- **Local expense server** (`expense_server.py`, built with **FastMCP**) exposes `add_expense`, `edit_expense`, `delete_expense`, `add_credit`, `list_expenses`, `list_credits`, `summarize` — all backed by a local `expenses.db` SQLite file.
- **Failure handling**: if the MCP server can't be spawned or connected, `load_mcp_tools()` catches the exception and returns an empty list — the chatbot degrades gracefully rather than crashing, just without those tools.
- **Extensibility**: adding a new capability (e.g. a math server, a calendar server) means adding one more entry to the `MultiServerMCPClient` config dict — no changes needed to the graph itself, since tools are bound dynamically.

---

## RAG Workflow

1. **Upload** — PDF or DOCX dropped in the sidebar uploader (per active thread).
2. **Load & clean** — `PyPDFLoader`/`Docx2txtLoader` extracts text; excessive newlines and stray whitespace are normalized.
3. **Adaptive chunking** — Chunk size and overlap scale with total document size (from 500/50 for tiny docs up to 1500/300 for docs over 100k characters), via `RecursiveCharacterTextSplitter`.
4. **Adaptive retrieval width** — `k` (results returned) and `fetch_k` (candidates considered before MMR reranking) scale with chunk count, from `k=4/fetch_k=10` on small docs up to `k=8/fetch_k=40` on large ones.
5. **Embed & index** — Chunks are embedded with `all-MiniLM-L6-v2` and stored in a **per-thread persistent ChromaDB collection** (`chroma_db/<thread_id>/`).
6. **Persistence** — The raw file bytes + metadata are also stored in SQLite (`chatbot.db`), so if the process restarts, `_get_retriever()` transparently rebuilds the Chroma retriever on first access rather than requiring re-upload.
7. **Retrieval** — Exposed to the agent as the `rag_tool`, using **MMR (Maximal Marginal Relevance)** search so returned chunks are both relevant and non-redundant. The system prompt tells the LLM the tool is available (and the filename) only when a document is actually indexed for that thread — if a document was removed mid-conversation, the LLM is explicitly instructed not to answer from memory of it.
8. **Cleanup** — Removing a document releases the Chroma client, clears in-memory caches, deletes the SQLite row, and removes the persisted vector store directory from disk (with Windows file-lock-safe retry logic).

---

## Image Generation Pipeline

Blog hero/section images are generated through a **three-tier fallback chain**, each wrapped independently so a failure in one tier automatically tries the next:

| Tier         | Provider                                                                        | Requires                  | Notes                                                                                                                                                                                                                      |
| ------------ | ------------------------------------------------------------------------------- | ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1 (primary)  | **Hugging Face Inference** (`huggingface_hub.InferenceClient`, provider="auto") | `HF_TOKEN`                | Tries `black-forest-labs/FLUX.1-schnell` first, then `FLUX.1-dev`. Best quality.                                                                                                                                           |
| 2 (fallback) | **Pollinations AI**                                                             | Nothing — free, no signup | Direct HTTP GET to `image.pollinations.ai` with the `flux` model, time-based seed to avoid cache collisions, retries with exponential backoff on 5xx, streamed download, magic-byte validation (PNG/JPEG signature check). |
| 3 (fallback) | **Google Imagen** (`google-genai` SDK, `imagen-3.0-generate-002`)               | `GOOGLE_API_KEY`          | Aspect ratio mapped from requested width/height (1:1, 2:3, or 3:2).                                                                                                                                                        |

If all three fail, the blog still completes — the failed image slot is replaced with a styled "Image generation failed" placeholder card in the Markdown rather than silently breaking the whole pipeline (this was a specific fix: earlier, Gemini safety-filter blocks were swallowing errors and producing blank output with no indication of what went wrong).

Once bytes are obtained: format is detected from magic bytes (never trusted from filename), the file is saved physically under `blogs/images/`, and it's also base64-encoded directly into an HTML `<img>` tag with a data URI — this is what actually renders reliably inside Streamlit's markdown, versus a standard `![alt](path)` reference which Streamlit will often fail to resolve for generated files.

---

## Memory System

**Long-Term Memory (`memory_store.py`)**

- Pre-filter regexes skip obviously non-storable messages (greetings, "I'm fine", anything under ~15 chars, short Devanagari small talk) _before_ spending an LLM call.
- What passes the filter goes to a structured-output Groq call (`MemoryDecision`) which extracts atomic English facts (name, stable preferences, ongoing projects, tools/platforms, financial habits) and flags each as `is_new` relative to what's already stored, so duplicates aren't re-saved.
- Retrieval scales: ≤30 stored memories → return all of them; >30 → keyword-overlap score against the current query and return the top 10, so the system prompt doesn't balloon for long-time users.
- Backed by LangGraph's `PostgresStore`, namespaced per user (`("user", user_id, "details")`).

**Short-Term Memory (`memory_checkpointer.py`)**

- `AsyncPostgresSaver` on a dedicated `AsyncConnectionPool`, opened on a single shared background asyncio event loop (`_loop`) running in its own daemon thread — this is what lets Streamlit's sync request/response cycle call async LangGraph methods via `run_async()`/`submit_async_task()`.
- Falls back to `AsyncSqliteSaver` (`chatbot.db`) if Postgres is unreachable at startup.
- Cleanly closed via `atexit`.

---

## Multi-Key Rotation & Rate Limiting

Every subsystem that calls Groq (chat, memory extraction, translation, blog writing) pulls from `GROQ_API_KEYS` via its own `itertools.cycle`, so different subsystems aren't fighting over the same key sequence. Two retry strategies are used depending on context:

- **Async paths** (chat, memory, translation): `_invoke_with_fallback` rotates to the next key immediately on a detected rate-limit error and retries up to `len(_GROQ_KEYS)` times.
- **Blog worker path** (sync, runs inside a `Send` fan-out): uses `_invoke_blog_sync_with_fallback` with **exponential backoff** (2s → 4s → 8s… capped at 30s) _in addition to_ key rotation — because Groq's rate limits are enforced per-organization, not per-key, so rotating keys alone doesn't help when several parallel workers hit the limit simultaneously; a final 15s-backoff retry is attempted before giving up entirely.

---

## Project Structure

```
langgrapph_chat_ui/
├── app.py                       # Streamlit dashboard (home page — analytics)
├── pages/
│   ├── 1_Chat.py                 # Main chat interface
│   └── 2_Blog.py                 # Blog generator interface
├── lang_rag_backend.py           # Chat graph, blog graph, tools, RAG, image gen, MCP client
├── memory_store.py               # LongTermMemory (fact extraction + dedup)
├── memory_checkpointer.py        # STM/LTM initialization + shared asyncio loop
├── translation_subgraph.py       # Nepali/Hindi/Sanskrit detection + translation subgraph
├── expense_server.py             # Local MCP expense server (FastMCP, stdio)
├── categories.json               # Expense categories config
├── .env                          # API keys + DB URI (not committed)
├── chatbot.db                    # SQLite — thread titles, doc metadata, deleted/created threads
├── expenses.db                   # SQLite — expense + income data (via MCP server)
├── chroma_db/                    # Per-thread ChromaDB vector stores (auto-created, not committed)
├── blogs/                        # Generated blog markdown + metadata
│   └── images/                   # Generated blog images (physical files)
└── requirements.txt
```

---

## Setup

**1. Clone the repo**

```bash
git clone https://github.com/Roshanshah098/mcp_chat_ui.git
cd mcp_chat_ui
```

**2. Create and activate a virtual environment** (or use `uv` directly)

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Mac/Linux
source venv/bin/activate
```

**3. Install dependencies**

```bash
pip install -r requirements.txt
```

**4. Start PostgreSQL**

The default config expects:

```
postgresql://postgres:postgres@localhost:5442/postgres
```

Override with `POSTGRES_URI` if your setup differs. No pgvector extension is required for the current STM/LTM implementation (both use plain relational tables via LangGraph's Postgres checkpointer/store).

**5. Create a `.env` file**

```env
# Required — comma-separated for multi-key rotation
GROQ_API_KEYS=your_groq_api_key_1,your_groq_api_key_2

# Required for stock price lookups
ALPHAVANTAGE_API_KEY=your_alphavantage_api_key

# Required for STM/LTM
POSTGRES_URI=postgresql://postgres:postgres@localhost:5442/postgres?sslmode=disable
DOC_DB=chatbot.db

# Optional — image generation (blog module)
HF_TOKEN=your_huggingface_token          # Tier 1: FLUX.1 via HF Inference
GOOGLE_API_KEY=your_google_api_key       # Tier 3: Google Imagen
# Tier 2 (Pollinations) needs no key — always available as a free fallback

# Optional — blog research
TAVILY_API_KEY=your_tavily_api_key       # Falls back to DuckDuckGo if unset
```

**6. Point the MCP client at your local expense server**

In `lang_rag_backend.py`, update the `command`/`args` paths under `MultiServerMCPClient(...)` to match your local `uv.exe` and `expense_server.py` locations.

**7. Run the app**

```bash
streamlit run app.py --server.fileWatcherType none
```

---

## Environment Variables

| Variable               | Required | Description                                                                                                                               |
| ---------------------- | -------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `GROQ_API_KEYS`        | ✅       | Comma-separated Groq API keys (rotated automatically on rate limits). `GROQ_API_KEY` (singular) also works as a single-key fallback name. |
| `ALPHAVANTAGE_API_KEY` | ✅       | For the stock price tool. Free key at [alphavantage.co](https://www.alphavantage.co/support/#api-key).                                    |
| `POSTGRES_URI`         | ✅       | Connection string for STM checkpointer + LTM store.                                                                                       |
| `DOC_DB`               | Optional | Path to the SQLite file for thread titles/doc metadata (default `chatbot.db`).                                                            |
| `HF_TOKEN`             | Optional | Enables Tier 1 (FLUX.1) image generation for blogs. Get one at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens).  |
| `GOOGLE_API_KEY`       | Optional | Enables Tier 3 (Google Imagen) image fallback.                                                                                            |
| `TAVILY_API_KEY`       | Optional | Enables live web research for blog generation; falls back to DuckDuckGo if unset.                                                         |
| `BLOG_OUTPUT_DIR`      | Optional | Where generated blog markdown/images are saved (default `blogs/`).                                                                        |

---

## Usage

| What you want           | What to say                                                        |
| ----------------------- | ------------------------------------------------------------------ |
| Search the web          | `What is the latest news about OpenAI?`                            |
| Stock price             | `What is the current price of AAPL?`                               |
| Math                    | `What is 25 multiplied by 48?`                                     |
| Add expense             | `Add expense of 500 for food on 2026-06-03` → approve in the popup |
| Summarize expenses      | `Summarize my expenses for June 2026`                              |
| Ask about your document | Upload a PDF → `What is this document about?`                      |
| Store a memory          | `Remember that I prefer dark mode`                                 |
| Switch language         | `Reply in Nepali` / just type in Nepali or Romanized Nepali        |
| Generate a blog         | Go to the Blog page (or sidebar) → enter a topic → `Generate Blog` |

---

## Notes & Gotchas

- **ChromaDB** persists per-thread under `chroma_db/<thread_id>/` and is rebuilt on-demand from the SQLite-stored file bytes if the in-memory retriever cache is cold (e.g. after a restart) — no re-upload needed.
- **PostgreSQL** is required for both STM and LTM. If it's unreachable, STM silently falls back to SQLite and LTM is disabled entirely (memory features stop working, but chat still functions).
- Groq's free tier has per-organization rate limits — this is why the blog worker path uses exponential backoff _in addition to_ key rotation, since parallel workers can exhaust all keys simultaneously.
- `torchvision` warnings on startup are harmless; run with `--server.fileWatcherType none` to reduce noise from file-watcher restarts on Windows.
- If you hit Groq rate limits often, consider swapping to a faster/cheaper model like `llama-3.1-8b-instant` in the `_GROQ_MODEL` constant in `lang_rag_backend.py`.
- PDF export on the Blog page requires `reportlab` (`pip install reportlab`); it's lazy-imported so the app runs fine without it, just without that export option.
- The dashboard (`app.py`) reads message history directly from the LangGraph checkpointer and local SQLite tables — there's no separate analytics database to keep in sync.

---

## License

peronal project --> USE freely -->

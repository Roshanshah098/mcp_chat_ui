# MCP Chat — Agentic RAG Chatbot

An agentic AI chatbot built with **LangGraph** and **Groq**. Chat with your uploaded PDF or DOCX files, track expenses, do math, search the web, and check stock prices — all in a polished Streamlit dashboard with persistent memory, multi-session chat history, and a live analytics view.

---

## Features

- **Document Q&A (RAG)** — Upload a PDF or DOCX and ask questions about it. Uses **ChromaDB** vector store with MMR retrieval and HuggingFace embeddings. Documents persist across sessions via SQLite metadata.
- **Long-Term Memory (LTM)** — Remembers your name, preferences, and projects across conversations using a **PostgreSQL pgvector store**.
- **Short-Term Memory (STM)** — Per-conversation context managed by LangGraph's **PostgreSQL checkpointer** (`AsyncPostgresSaver`). Auto-summarizes long threads.
- **Web Search** — DuckDuckGo search for real-time information.
- **Stock Price Lookup** — Fetch live stock prices via Alpha Vantage API.
- **Math Operations** — Add, subtract, multiply, and generate random numbers via a remote MCP server.
- **Expense Tracking** — Add, list, edit, and summarize expenses via a local MCP server backed by SQLite.
- **Multi-Session Chat** — Switch between conversations from the sidebar. Titles generated from your first message.
- **Dashboard** — Live analytics: message counts, topic breakdown, vocabulary heatmap, activity gauges.
- **Multilingual** — Auto-detects Nepali / Hindi (Romanized or Unicode), replies in kind.
- **Human-in-the-Loop (HITL)** — Expense actions require your approval before execution.

---

## Tech Stack

| Layer             | Technology                                             |
| ----------------- | ------------------------------------------------------ |
| LLM               | Groq — `llama-3.3-70b-versatile` (multi-key rotation)  |
| Agent Framework   | LangGraph (`StateGraph`)                               |
| Vector Store      | **ChromaDB** (persistent, local)                       |
| Embeddings        | HuggingFace `all-MiniLM-L6-v2`                         |
| Short-Term Memory | LangGraph `AsyncPostgresSaver` (PostgreSQL)            |
| Long-Term Memory  | LangGraph `AsyncPostgresStore` (PostgreSQL + pgvector) |
| MCP Client        | `langchain-mcp-adapters` (FastMCP stdio + SSE)         |
| Frontend          | Streamlit 1.57                                         |
| Dashboard Charts  | Plotly                                                 |
| Metadata / Titles | SQLite (`chatbot.db`)                                  |
| Expense Data      | SQLite (`expenses.db`)                                 |
| Web Search        | DuckDuckGo (`duckduckgo-search`)                       |
| Stock Prices      | Alpha Vantage API                                      |
| Translation       | Groq LLM node in graph                                 |
| HITL              | LangGraph interrupt + `Command(resume=...)`            |

---

## Graph Architecture

```
START
  └─► remember          ← injects LTM memories into system prompt
        └─► chat_node   ← LLM reasoning + tool call decisions
              ├─► tools          (if tool_calls present)
              │     └─► chat_node  (loop until no tool calls)
              └─► translate      ← translates reply if non-English input
                    ├─► summarize  (if thread > STM_SUMMARIZE_AFTER msgs)
                    └─► END
```

**Nodes:**

- `remember` — pulls relevant LTM facts from PostgreSQL store, prepends to system prompt
- `chat_node` — Groq LLM with bound tools; handles multi-turn reasoning
- `tools` — LangGraph `ToolNode` executing MCP + local tools
- `translate` — detects non-English input, rewrites AI reply in user's language
- `summarize` — condenses old messages to keep context window small

---

## Project Structure

```
langgrapph_chat_ui/
├── app.py                      # Streamlit dashboard (analytics home page)
├── pages/
│   └── 1_Chat.py               # Main chat interface page
├── lang_rag_backend.py         # LangGraph backend — graph, tools, memory, MCP
├── expense_server.py           # Local MCP expense server (FastMCP stdio)
├── categories.json             # Expense categories config
├── .env                        # API keys + DB URI (not committed)
├── chatbot.db                  # SQLite — thread titles + doc metadata (auto-created)
├── expenses.db                 # SQLite — expense data (auto-created)
├── chroma_db/                  # ChromaDB vector store (auto-created, not committed)
└── requirements.txt
```

---

## Setup

**1. Clone the repo**

```bash
git clone https://github.com/your-username/your-repo-name.git
cd your-repo-name
```

**2. Create and activate virtual environment**

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

You need a running PostgreSQL instance with the `pgvector` extension. The default config expects:

```
postgresql://postgres:postgres@localhost:5442/postgres
```

Override with the `POSTGRES_URI` environment variable if your setup differs.

Enable pgvector once inside psql:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

**5. Create `.env` file**

```env
GROQ_API_KEY=your_groq_api_key_1,your_groq_api_key_2
ALPHAVANTAGE_API_KEY=your_alphavantage_api_key
POSTGRES_URI=postgresql://postgres:postgres@localhost:5442/postgres?sslmode=disable
DOC_DB=chatbot.db
```

> Multiple Groq keys are comma-separated — the backend rotates through them automatically on rate-limit errors.

**6. Run the app**

```bash
streamlit run app.py --server.fileWatcherType none
```

---

## MCP Servers

### Remote — Math Server

Hosted at `https://subhai-mcp-testing.fastmcp.app/mcp`  
Supports: `add`, `subtract`, `multiply`, `random_number`

### Local — Expense Server

Runs via stdio using `uv`. Update the path in `lang_rag_backend.py`:

```python
"expense": {
    "transport": "stdio",
    "command": "path/to/uv.exe",
    "args": ["run", "--with", "fastmcp", "fastmcp", "run", "path/to/expense_server.py"],
}
```

---

## Usage

| What you want      | What to say                                   |
| ------------------ | --------------------------------------------- |
| Search the web     | `What is the latest news about OpenAI?`       |
| Stock price        | `What is the current price of AAPL?`          |
| Math               | `What is 25 multiplied by 48?`                |
| Add expense        | `Add expense of 500 for food on 2026-06-03`   |
| Summarize expenses | `Summarize my expenses for June 2026`         |
| Ask about your doc | Upload a PDF → `What is this document about?` |
| Store a memory     | `Remember that I prefer dark mode`            |
| Switch language    | `Reply in Nepali` / just type in Nepali       |

---

## Environment Variables

| Variable               | Description                                                                     |
| ---------------------- | ------------------------------------------------------------------------------- |
| `GROQ_API_KEY`         | Comma-separated Groq API keys from [console.groq.com](https://console.groq.com) |
| `ALPHAVANTAGE_API_KEY` | Free key from [alphavantage.co](https://www.alphavantage.co/support/#api-key)   |
| `POSTGRES_URI`         | PostgreSQL connection string (needs pgvector extension)                         |
| `DOC_DB`               | Path to SQLite file for thread titles + doc metadata (default: `chatbot.db`)    |

---

## Notes

- **ChromaDB** replaces the old FAISS store — documents are now persisted to disk in `chroma_db/` and survive restarts without re-uploading.
- **PostgreSQL** is required for both STM (checkpointer) and LTM (pgvector store). The app degrades gracefully if unavailable but memory features won't work.
- `torchvision` warnings on startup are harmless — use `--server.fileWatcherType none` to suppress them.
- Groq free tier has a daily token limit. Multiple keys in `GROQ_API_KEY` are rotated automatically. Fallback: switch to `llama-3.1-8b-instant` in `lang_rag_backend.py`.
- The dashboard (`app.py`) reads message history directly from the LangGraph checkpointer — no separate analytics DB needed.

---

## License

MIT

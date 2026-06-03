# MCP + RAG Chatbot

An agentic AI chatbot built with **LangGraph** and **Groq**. Chat with your uploaded PDF or DOCX files, track expenses, do math, search the web, and check stock prices — all in one clean Streamlit interface with persistent chat history.

---

## Features

- **Document Q&A (RAG)** — Upload a PDF or DOCX and ask questions about it. Uses FAISS vector store with MMR retrieval and HuggingFace embeddings. Documents persist across sessions.
- **Web Search** — DuckDuckGo search for real-time information.
- **Stock Price Lookup** — Fetch live stock prices via Alpha Vantage API.
- **Math Operations** — Add, subtract, multiply, and generate random numbers via a remote MCP server.
- **Expense Tracking** — Add, list, edit, and summarize expenses via a local MCP server backed by SQLite.
- **Persistent Chat History** — Conversations saved using LangGraph's SQLite checkpointer. Reload any past chat from the sidebar.
- **Persistent Documents** — Uploaded files stored in SQLite and reloaded automatically on restart.
- **Chat Titles** — Each conversation titled from your first message for easy navigation.

---

## Tech Stack

| Layer | Technology |
|---|---|
| LLM | Groq — `llama-3.3-70b-versatile` |
| Agent Framework | LangGraph |
| Vector Store | FAISS |
| Embeddings | HuggingFace `all-MiniLM-L6-v2` |
| MCP Client | `langchain-mcp-adapters` |
| Frontend | Streamlit |
| Persistence | SQLite (aiosqlite + sqlite3) |
| Web Search | DuckDuckGo |
| Stock Prices | Alpha Vantage API |

---

## Project Structure

```
langgrapph_chat_ui/
├── streamlit_rag_frontend.py   # Streamlit UI
├── lang_back_mcp.py            # LangGraph backend + tools
├── expense_server.py           # Local MCP expense server (FastMCP)
├── categories.json             # Expense categories config
├── .env                        # API keys (not committed)
├── chatbot.db                  # SQLite — chat history + docs (auto-created)
├── expenses.db                 # SQLite — expense data (auto-created)
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

**4. Create `.env` file**
```
GROQ_API_KEY=your_groq_api_key
ALPHAVANTAGE_API_KEY=your_alphavantage_api_key
```

**5. Run the app**
```bash
streamlit run streamlit_rag_frontend.py --server.fileWatcherType none
```

---

## MCP Servers

### Remote — Math Server
Hosted at `https://subhai-mcp-testing.fastmcp.app/mcp`
Supports: `add`, `subtract`, `multiply`, `random_number`

### Local — Expense Server
Runs via stdio using `uv`. Update the path in `lang_back_mcp.py` to match your machine:

```python
"expense": {
    "transport": "stdio",
    "command": "path/to/uv.exe",
    "args": ["run", "--with", "fastmcp", "fastmcp", "run", "path/to/expense_server.py"],
}
```

Make sure `categories.json` exists in the same folder as `expense_server.py`.

---

## Usage

| What you want | What to say |
|---|---|
| Search the web | `What is the latest news about OpenAI?` |
| Stock price | `What is the current price of AAPL?` |
| Math | `What is 25 multiplied by 48?` |
| Add expense | `Add expense of 500 for food on 2026-06-03` |
| Summarize expenses | `Summarize my expenses for June 2026` |
| Ask about your doc | Upload a PDF → `What is this document about?` |

---

## Environment Variables

| Variable | Description |
|---|---|
| `GROQ_API_KEY` | Groq API key from [console.groq.com](https://console.groq.com) |
| `ALPHAVANTAGE_API_KEY` | Free key from [alphavantage.co](https://www.alphavantage.co/support/#api-key) |

---

## Notes

- The `torchvision` warnings on startup are harmless — Streamlit scans all of `transformers` including vision models not used here. Use `--server.fileWatcherType none` to suppress them.
- Groq free tier has a daily token limit. If you hit it, wait an hour or switch to `llama-3.1-8b-instant` temporarily in `lang_back_mcp.py`.
- FAISS runs fully in-memory — no external vector DB needed.

---

## License

MIT

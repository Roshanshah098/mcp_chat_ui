import re, json, sqlite3
from collections import Counter
from datetime import datetime
import streamlit as st
import plotly.graph_objects as go
import os

try:
    import msgpack as _msgpack

    _HAS_MSGPACK = True
except ImportError:
    _HAS_MSGPACK = False

POSTGRES_URI = os.getenv(
    "POSTGRES_URI",
    "postgresql://postgres:postgres@localhost:5442/postgres?sslmode=disable",
)
DOC_DB = os.getenv("DOC_DB", "chatbot.db")

STOP_WORDS = {
    "the",
    "a",
    "an",
    "is",
    "it",
    "in",
    "on",
    "at",
    "to",
    "for",
    "of",
    "and",
    "or",
    "but",
    "i",
    "my",
    "me",
    "you",
    "your",
    "we",
    "do",
    "did",
    "can",
    "what",
    "how",
    "when",
    "where",
    "that",
    "this",
    "with",
    "from",
    "have",
    "has",
    "be",
    "was",
    "are",
    "will",
    "just",
    "its",
    "get",
    "got",
    "ok",
    "okay",
    "hi",
    "hello",
    "hey",
    "yes",
    "no",
    "please",
    "thanks",
    "thank",
    "want",
    "need",
    "could",
    "would",
    "should",
    "make",
    "let",
    "tell",
    "show",
    "give",
    "use",
    "also",
    "so",
    "if",
    "then",
    "than",
    "some",
    "all",
    "any",
    "more",
    "not",
    "up",
    "as",
    "about",
    "u",
    "ur",
    "im",
    "dont",
    "cant",
    "wont",
    "ive",
    "id",
    "thats",
    "yeah",
    "yep",
    "nope",
    "now",
    "think",
    "know",
    "talk",
    "lets",
    "ohh",
    "say",
    "like",
    "one",
    "two",
    "heh",
    "haha",
    "lol",
    "sir",
    "mate",
    "doing",
    "fine",
    "good",
    "great",
    "well",
    "are",
    "was",
}

st.set_page_config(
    page_title="MCP Chat · Dashboard",
    page_icon="📊",
    layout="wide",
)

# =============================================================
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

html,body,[data-testid="stAppViewContainer"]{
    background:#080810!important;color:#e2e2f0;font-family:'Inter',sans-serif;
}
[data-testid="stHeader"]  { background:transparent!important; }
[data-testid="stToolbar"] { display:none!important; }

::-webkit-scrollbar{width:4px;}
::-webkit-scrollbar-track{background:#0d0d1a;}
::-webkit-scrollbar-thumb{background:#6366f1;border-radius:4px;}

/* ═══════════════════════════════════════════════════════════════
   SIDEBAR — PERMANENTLY OPEN, NO COLLAPSE/REOPEN TOGGLE
   ═══════════════════════════════════════════════════════════════ */
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
    padding: 9px 12px !important;
    transition: all .18s !important;
    width: 100% !important;
    text-align: left !important;
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

[data-testid="stSidebar"] [data-testid="stPageLink"] a {
    background: linear-gradient(135deg,#6366f1,#8b5cf6) !important;
    color: #fff !important;
    border: none !important;
    border-radius: 10px !important;
    font-weight: 600 !important;
    font-size: 13px !important;
    padding: 10px 14px !important;
    display: block !important;
    text-decoration: none !important;
    box-shadow: 0 4px 14px rgba(99,102,241,.35) !important;
    margin-bottom: 8px !important;
    box-sizing: border-box !important;
}
[data-testid="stSidebar"] [data-testid="stPageLink"] a:hover {
    box-shadow: 0 6px 20px rgba(99,102,241,.55) !important;
    transform: translateY(-1px) !important;
}

[data-testid="stPageLink"] a {
    background: rgba(99,102,241,.1) !important;
    border: 1px solid rgba(99,102,241,.35) !important;
    border-radius: 10px !important;
    color: #a5b4fc !important;
    font-weight: 600 !important;
    font-size: 13px !important;
    padding: 9px 18px !important;
    display: inline-block !important;
    text-decoration: none !important;
    transition: all .2s !important;
}
[data-testid="stPageLink"] a:hover {
    background: rgba(99,102,241,.2) !important;
    border-color: #6366f1 !important;
    color: #e2e2f0 !important;
}

.sb-brand{padding:18px 4px 14px;border-bottom:1px solid #1a1a2e;margin-bottom:14px;}
.sb-brand-row{display:flex;align-items:center;gap:10px;margin-bottom:3px;}
.sb-icon{width:34px;height:34px;background:linear-gradient(135deg,#6366f1,#8b5cf6);
  border-radius:10px;display:flex;align-items:center;justify-content:center;
  font-size:16px;box-shadow:0 0 16px rgba(99,102,241,.4);}
.sb-name{font-size:15px;font-weight:700;color:#f1f1f3!important;letter-spacing:-.3px;}
.sb-tag {font-size:9.5px;color:#454560!important;letter-spacing:.6px;margin-left:44px;}
.sb-sec{font-size:9px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;
  color:#454560!important;margin:14px 2px 7px;display:flex;align-items:center;gap:6px;}
.sb-sec::after{content:'';flex:1;height:1px;background:#1a1a2e;}

.sb-stats{background:#0d0d1a;border:1px solid #1a1a2e;border-radius:11px;
  padding:10px 13px;margin-bottom:12px;}
.sb-stat-row{display:flex;align-items:center;gap:8px;font-size:11.5px;padding:2.5px 0;}
.sb-dot    {width:7px;height:7px;border-radius:50%;flex-shrink:0;}
.sb-dot.ok {background:#22c55e;box-shadow:0 0 5px rgba(34,197,94,.7);}
.sb-dot.warn{background:#eab308;box-shadow:0 0 5px rgba(234,179,8,.7);}
.sb-dot.bad{background:#ef4444;box-shadow:0 0 5px rgba(239,68,68,.7);}
.sb-stat-label  {color:#c4c4d8!important;}
.sb-stat-label b{color:#f1f1f3!important;}

.metric-card{background:#0d0d1a;border:1px solid #1a1a2e;border-radius:14px;
  padding:20px 22px;position:relative;overflow:hidden;}
.metric-card::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;
  background:linear-gradient(90deg,#6366f1,#8b5cf6);}
.metric-value{font-size:2.2rem;font-weight:700;line-height:1;color:#f1f1f3;
  font-family:'JetBrains Mono',monospace;}
.metric-label{font-size:.67rem;font-weight:700;letter-spacing:1.2px;
  text-transform:uppercase;color:#555568;margin-top:6px;}
.metric-sub{font-size:.74rem;color:#6366f1;margin-top:5px;}
.section-hd{font-size:.64rem;font-weight:700;letter-spacing:1.6px;text-transform:uppercase;
  color:#454560;margin:28px 0 12px;padding-bottom:8px;border-bottom:1px solid #1a1a2e;}
.feat-card{background:#0d0d1a;border:1px solid #1a1a2e;border-radius:14px;
  padding:20px;transition:border-color .2s,transform .2s;}
.feat-card:hover{border-color:#6366f1;transform:translateY(-2px);}
.feat-icon {font-size:1.7rem;margin-bottom:10px;}
.feat-title{font-size:.92rem;font-weight:600;color:#e2e2f0;margin-bottom:6px;}
.feat-desc {font-size:.76rem;color:#6b7280;line-height:1.6;}
.feat-badge{display:inline-block;background:rgba(99,102,241,.12);
  border:1px solid rgba(99,102,241,.3);border-radius:20px;
  padding:3px 9px;font-size:.67rem;color:#a5b4fc;margin-top:9px;margin-right:4px;}
.live-badge{display:inline-flex;align-items:center;gap:6px;
  background:rgba(34,197,94,.1);border:1px solid rgba(34,197,94,.3);
  border-radius:20px;padding:4px 12px;font-size:11px;color:#4ade80;}
.live-dot{width:6px;height:6px;border-radius:50%;background:#22c55e;
  box-shadow:0 0 6px rgba(34,197,94,.8);animation:pulse 2s infinite;}
@keyframes pulse{0%,100%{opacity:1;}50%{opacity:.3;}}
.hero{background:linear-gradient(135deg,rgba(99,102,241,.12),rgba(139,92,246,.08));
  border:1px solid #1e1e3a;border-radius:18px;padding:28px 32px;margin-bottom:20px;}
.hero-title{font-size:1.45rem;font-weight:700;color:#f1f1f3;letter-spacing:-.4px;margin-bottom:8px;}
.hero-title span{background:linear-gradient(135deg,#6366f1,#06b6d4);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;}
.hero-sub{font-size:.86rem;color:#9696b0;line-height:1.7;max-width:520px;}
.empty{text-align:center;padding:32px;color:#454560;font-size:.82rem;
  border:1px dashed #1a1a2e;border-radius:12px;}
.footer{text-align:center;padding:32px 0 16px;color:#2d2d4e;font-size:.67rem;
  border-top:1px solid #1a1a2e;margin-top:40px;}
.wc-item{display:inline-block;margin:3px;padding:4px 12px;border-radius:20px;
  background:rgba(99,102,241,.07);border:1px solid rgba(99,102,241,.18);}
.doc-row{background:#0d0d1a;border:1px solid #1a1a2e;border-radius:10px;
  padding:11px 14px;margin-bottom:8px;display:flex;justify-content:space-between;align-items:center;}

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
.loader-title{font-size:1.15rem;font-weight:700;color:#f1f1f3;text-align:center;letter-spacing:-.3px;}
.loader-sub{font-size:.82rem;color:#6b7280;text-align:center;margin-top:-8px;}
.loader-steps{position:relative;height:24px;width:360px;font-size:.8rem;color:#9696b0;text-align:center;}
.loader-steps span{position:absolute;left:0;right:0;opacity:0;animation:step-fade 10s infinite;}
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
  background-size:200% 100%;animation:bar-shimmer 2s linear infinite;}
@keyframes bar-shimmer{0%{background-position:200% 0;}100%{background-position:-200% 0;}}
.loader-timer{font-size:.72rem;color:#454560;font-family:'JetBrains Mono',monospace;}
.loader-patience{font-size:.78rem;color:#6366f1;text-align:center;
  background:rgba(99,102,241,.08);border:1px solid rgba(99,102,241,.2);
  border-radius:10px;padding:8px 20px;margin-top:4px;}
</style>
""",
    unsafe_allow_html=True,
)


# =============================================================
# FIRST-LOAD 3D LOADER
# =============================================================
import sys as _sys

_FIRST_LOAD = "lang_rag_backend" not in _sys.modules
_loader_slot = st.empty()
if _FIRST_LOAD:
    with _loader_slot.container():
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
          <div class="loader-title">Connecting to your AI assistant…</div>
          <div class="loader-sub">Loading models, memory, and tools</div>
          <div class="loader-steps">
            <span>🔑 &nbsp;Rotating in Groq API keys…</span>
            <span>🧠 &nbsp;Loading embedding model (MiniLM-L6-v2)…</span>
            <span>💾 &nbsp;Connecting short-term memory (PostgreSQL)…</span>
            <span>📚 &nbsp;Connecting long-term memory (LTM store)…</span>
          </div>
          <div class="loader-bar-wrap"><div class="loader-bar"></div></div>
          <div class="loader-timer" id="dash-loader-timer">Elapsed: 0s</div>
          <div class="loader-patience">
            ⏳ &nbsp;First load takes 15–30 seconds — please keep patience!
          </div>
        </div>
        <script>
        (function() {
          var start = Date.now();
          var el = document.getElementById('dash-loader-timer');
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


# =============================================================
# DB
# =============================================================
@st.cache_resource
def _sqlite():
    return sqlite3.connect(DOC_DB, check_same_thread=False)


@st.cache_resource
def _pg():
    try:
        import psycopg

        return psycopg.connect(POSTGRES_URI, autocommit=True)
    except Exception as e:
        print(f"[Dashboard/pg] {e}")
        return None


@st.cache_resource(show_spinner=False)
def _get_backend():
    import lang_rag_backend as backend

    return backend


# =============================================================
# DATA LOADERS
# =============================================================
@st.cache_data(ttl=30)
def _load_thread_titles():
    try:
        return dict(
            _sqlite().execute("SELECT thread_id,title FROM thread_titles").fetchall()
        )
    except Exception:
        return {}


@st.cache_data(ttl=30)
def _load_thread_docs():
    try:
        rows = (
            _sqlite()
            .execute(
                "SELECT thread_id,filename,filetype,metadata FROM thread_documents"
            )
            .fetchall()
        )
        result = []
        for tid, fname, ftype, mj in rows:
            meta = json.loads(mj) if mj else {}
            result.append(
                {"thread_id": tid, "filename": fname, "filetype": ftype, **meta}
            )
        return result
    except Exception:
        return []


@st.cache_data(ttl=15, show_spinner=False)
def _load_messages_and_threads():
    messages, thread_ids = [], set()
    try:
        backend = _get_backend()
        for checkpoint in backend.checkpointer.list(None):
            tid = checkpoint.config.get("configurable", {}).get("thread_id")
            if tid:
                thread_ids.add(str(tid))

        for tid in thread_ids:
            try:
                state = backend.chatbot.get_state(
                    config={
                        "configurable": {"thread_id": tid, "user_id": "default_user"}
                    }
                )
                for m in state.values.get("messages", []):
                    role = (
                        getattr(m, "type", None)
                        or m.__class__.__name__.replace("Message", "").lower()
                    )
                    content = m.content
                    if isinstance(content, list):
                        content = " ".join(
                            c2.get("text", "") if isinstance(c2, dict) else str(c2)
                            for c2 in content
                        )
                    if (
                        isinstance(content, str)
                        and content.strip()
                        and role in ("human", "ai", "assistant")
                    ):
                        messages.append(
                            {
                                "thread_id": tid,
                                "role": "human" if role == "human" else "ai",
                                "content": content.strip(),
                            }
                        )
            except Exception as e:
                print(f"[Dashboard/thread-{tid}] {e}")
    except Exception as e:
        print(f"[Dashboard/Messages] {e}")
    return messages, thread_ids


@st.cache_data(ttl=15)
def _load_thread_count():
    conn = _pg()
    if conn is None:
        return 0
    try:
        row = conn.execute(
            "SELECT COUNT(DISTINCT thread_id) FROM checkpoints"
        ).fetchone()
        return row[0] if row else 0
    except Exception:
        return 0


def _top_words(messages, n=20):
    words = []
    for m in messages:
        if m["role"] == "human":
            tokens = re.findall(r"\b[a-z]{3,}\b", m["content"].lower())
            words.extend(t for t in tokens if t not in STOP_WORDS)
    return Counter(words).most_common(n)


def _topics(messages):
    T = {
        "💸 Expenses": [
            "expense",
            "budget",
            "spend",
            "cost",
            "money",
            "price",
            "credit",
            "income",
        ],
        "🔍 Search": ["search", "find", "look", "news", "latest", "weather", "browse"],
        "📄 Documents": [
            "document",
            "pdf",
            "docx",
            "file",
            "upload",
            "page",
            "summarize",
        ],
        "📈 Stocks": ["stock", "price", "market", "symbol", "aapl", "tsla", "invest"],
        "🔢 Math": [
            "calculate",
            "math",
            "formula",
            "sum",
            "average",
            "percent",
            "factorial",
        ],
        "🧠 Memory": ["remember", "name", "preference", "dislike", "habit", "project"],
        "💬 General": [
            "help",
            "explain",
            "show",
            "what",
            "how",
            "tell",
            "joke",
            "funny",
        ],
    }
    counts = {k: 0 for k in T}
    for m in messages:
        if m["role"] != "human":
            continue
        text = m["content"].lower()
        for t, kws in T.items():
            if any(k in text for k in kws):
                counts[t] += 1
    return counts


# =============================================================
# PLOTLY HELPERS
# =============================================================
_B = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#c4c4d8", family="Inter", size=12),
    margin=dict(l=8, r=8, t=40, b=8),
)


def _donut(labels, values, title):
    fig = go.Figure(
        go.Pie(
            labels=labels,
            values=values,
            hole=0.58,
            marker=dict(
                colors=[
                    "#6366f1",
                    "#8b5cf6",
                    "#06b6d4",
                    "#22c55e",
                    "#eab308",
                    "#ef4444",
                    "#f97316",
                ]
            ),
            textinfo="label+percent",
            textfont=dict(size=11),
            hovertemplate="%{label}: %{value}<extra></extra>",
        )
    )
    fig.update_layout(
        **_B,
        title=dict(text=title, font=dict(size=13, color="#6b7280")),
        showlegend=False,
    )
    return fig


def _hbar(labels, values, title):
    fig = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker=dict(
                color=values,
                colorscale=[[0, "#6366f1"], [0.5, "#8b5cf6"], [1, "#06b6d4"]],
                showscale=False,
            ),
            text=values,
            textposition="outside",
        )
    )
    fig.update_layout(
        **_B,
        title=dict(text=title, font=dict(size=13, color="#6b7280")),
        yaxis=dict(autorange="reversed", gridcolor="#1a1a2e"),
        xaxis=dict(gridcolor="#1a1a2e"),
    )
    return fig


def _gauge(value, max_val, title, color="#6366f1"):
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=value,
            title=dict(text=title, font=dict(size=13, color="#555568")),
            number=dict(font=dict(size=28, color="#e2e2f0", family="JetBrains Mono")),
            gauge=dict(
                axis=dict(
                    range=[0, max_val],
                    tickcolor="#555568",
                    tickfont=dict(color="#555568", size=9),
                ),
                bar=dict(color=color, thickness=0.22),
                bgcolor="rgba(0,0,0,0)",
                bordercolor="#1a1a2e",
                steps=[
                    dict(range=[0, max_val * 0.5], color="#0d0d1a"),
                    dict(range=[max_val * 0.5, max_val * 0.8], color="#111128"),
                    dict(range=[max_val * 0.8, max_val], color="#14143a"),
                ],
                threshold=dict(
                    line=dict(color="#8b5cf6", width=3), thickness=0.75, value=value
                ),
            ),
        )
    )
    fig.update_layout(**_B, height=210)
    return fig


def _spark(x, y, title):
    fig = go.Figure(
        go.Scatter(
            x=x,
            y=y,
            mode="lines+markers",
            fill="tozeroy",
            line=dict(color="#6366f1", width=2),
            marker=dict(color="#8b5cf6", size=5),
            fillcolor="rgba(99,102,241,0.12)",
        )
    )
    fig.update_layout(
        **_B,
        title=dict(text=title, font=dict(size=13, color="#6b7280")),
        xaxis=dict(gridcolor="#1a1a2e", tickangle=-30, tickfont=dict(size=10)),
        yaxis=dict(gridcolor="#1a1a2e"),
    )
    return fig


def _role_bar(hc, ac):
    fig = go.Figure(
        go.Bar(
            x=["You", "AI"],
            y=[hc, ac],
            marker=dict(color=["#6366f1", "#06b6d4"]),
            text=[hc, ac],
            textposition="outside",
        )
    )
    fig.update_layout(
        **_B,
        title=dict(text="Message breakdown", font=dict(size=13, color="#6b7280")),
        xaxis=dict(gridcolor="#1a1a2e"),
        yaxis=dict(gridcolor="#1a1a2e"),
    )
    return fig


# =============================================================
# LOAD
# =============================================================
thread_titles = _load_thread_titles()
thread_docs = _load_thread_docs()
all_messages, _thread_ids = _load_messages_and_threads()

if _FIRST_LOAD:
    _loader_slot.empty()
    st.toast(
        f"✅ Connected — {len(_thread_ids) or len(thread_titles)} conversation(s), "
        f"{len(all_messages)} messages",
        icon="🚀",
    )

human_msgs = [m for m in all_messages if m["role"] == "human"]
ai_msgs = [m for m in all_messages if m["role"] == "ai"]
total_threads = len(_thread_ids) or len(thread_titles)
avg_words = (
    (sum(len(m["content"].split()) for m in human_msgs) // max(len(human_msgs), 1))
    if human_msgs
    else 0
)


# =============================================================
# SIDEBAR
# =============================================================
with st.sidebar:
    st.markdown(
        """
    <div class="sb-brand">
      <div class="sb-brand-row">
        <div class="sb-icon">📊</div>
        <div><div class="sb-name">MCP Chat</div></div>
      </div>
      <div class="sb-tag">Command Center · Analytics</div>
    </div>""",
        unsafe_allow_html=True,
    )

    def _dot(v):
        return "ok" if v > 0 else "warn"

    st.markdown(
        f"""
    <div class="sb-stats">
      <div class="sb-stat-row"><span class="sb-dot {_dot(len(all_messages))}"></span>
        <span class="sb-stat-label"><b>{len(all_messages)}</b> messages tracked</span></div>
      <div class="sb-stat-row"><span class="sb-dot {_dot(total_threads)}"></span>
        <span class="sb-stat-label"><b>{total_threads}</b> conversations</span></div>
      <div class="sb-stat-row"><span class="sb-dot {_dot(len(human_msgs))}"></span>
        <span class="sb-stat-label"><b>{len(human_msgs)}</b> from you · <b>{len(ai_msgs)}</b> AI</span></div>
      <div class="sb-stat-row"><span class="sb-dot {_dot(len(thread_docs))}"></span>
        <span class="sb-stat-label"><b>{len(thread_docs)}</b> doc(s) indexed</span></div>
    </div>""",
        unsafe_allow_html=True,
    )

    st.page_link("pages/1_Chat.py", label="💬  Open Chatbot")
    st.page_link("pages/2_Blog.py", label="📝  Blog Generator")
    st.markdown("<div style='margin:6px 0'></div>", unsafe_allow_html=True)

    if st.button("🔄  Refresh Data", width="stretch", key="refresh_data_btn"):
        st.cache_data.clear()
        st.rerun()

    st.markdown('<div class="sb-sec">🕐 Recent Chats</div>', unsafe_allow_html=True)
    if thread_titles:
        for tid, title in list(thread_titles.items())[:12]:
            st.markdown(
                f'<div style="font-size:11.5px;color:#6b7280;padding:4px 4px 4px 10px;'
                f"border-left:2px solid #1e1e2e;margin-bottom:5px;border-radius:0 6px 6px 0;"
                f'background:rgba(99,102,241,.03)">💬 {title[:32]}{"…" if len(title)>32 else ""}</div>',
                unsafe_allow_html=True,
            )
    else:
        st.markdown(
            '<div style="font-size:11.5px;color:#454560;padding:6px 4px;line-height:1.6">'
            "No chats yet. Start a conversation!</div>",
            unsafe_allow_html=True,
        )

    if not _HAS_MSGPACK:
        st.markdown(
            '<div style="font-size:10px;color:#eab308;margin-top:12px;padding:8px;'
            'background:rgba(234,179,8,.08);border:1px solid rgba(234,179,8,.25);border-radius:8px">'
            "⚠️ <b>msgpack</b> not installed<br><code>pip install msgpack</code></div>",
            unsafe_allow_html=True,
        )

    st.markdown(
        f'<div style="font-size:9.5px;color:#2d2d4e;margin-top:16px;text-align:center">'
        f'Updated {datetime.now().strftime("%H:%M:%S")}</div>',
        unsafe_allow_html=True,
    )


# =============================================================
# MAIN
# =============================================================
st.markdown(
    f'<div style="display:flex;justify-content:flex-end;margin-bottom:8px">'
    f'<span class="live-badge"><span class="live-dot"></span>'
    f'Live · {datetime.now().strftime("%H:%M:%S")}</span></div>',
    unsafe_allow_html=True,
)

st.markdown(
    """
<div class="hero">
  <div class="hero-title">👋 Welcome to <span>MCP Chat</span></div>
  <div class="hero-sub">
    Your command center — track conversations, explore your activity,
    and jump into a chat whenever you're ready.
    The more you chat, the richer this dashboard gets.
  </div>
</div>""",
    unsafe_allow_html=True,
)

hc1, hc2, _ = st.columns([1.2, 1.4, 4])
with hc1:
    st.page_link("pages/1_Chat.py", label="💬  Chat Now")
with hc2:
    st.page_link("pages/1_Chat.py", label="📄  Start RAG Journey")

# KPIs
st.markdown('<div class="section-hd">Overview</div>', unsafe_allow_html=True)


def _kpi(col, val, label, sub=""):
    col.markdown(
        f"""
    <div class="metric-card">
      <div class="metric-value">{val}</div>
      <div class="metric-label">{label}</div>
      {"<div class='metric-sub'>"+sub+"</div>" if sub else ""}
    </div>""",
        unsafe_allow_html=True,
    )


k1, k2, k3, k4, k5 = st.columns(5)
_kpi(
    k1,
    len(all_messages),
    "Total Messages",
    f"{len(human_msgs)} you · {len(ai_msgs)} AI",
)
_kpi(k2, total_threads, "Conversations", f"{len(thread_titles)} titled")
_kpi(k3, avg_words, "Avg Words/Msg", "Your messages")
_kpi(k4, len(thread_docs), "Docs Indexed", "Across all threads")
_kpi(k5, len(thread_titles), "Titled Chats", "With saved titles")

# Gauges
st.markdown('<div class="section-hd">Activity Usage</div>', unsafe_allow_html=True)
g1, g2, g3 = st.columns(3)
with g1:
    st.plotly_chart(
        _gauge(
            len(human_msgs), max(len(human_msgs) * 2, 100), "Your Messages", "#6366f1"
        ),
        width="stretch",
        config={"displayModeBar": False},
    )
with g2:
    st.plotly_chart(
        _gauge(
            len(all_messages),
            max(len(all_messages) * 2, 200),
            "Total Messages",
            "#06b6d4",
        ),
        width="stretch",
        config={"displayModeBar": False},
    )
with g3:
    st.plotly_chart(
        _gauge(total_threads, max(total_threads * 2, 20), "Active Threads", "#22c55e"),
        width="stretch",
        config={"displayModeBar": False},
    )

# Engagement
st.markdown('<div class="section-hd">Engagement Analysis</div>', unsafe_allow_html=True)
if human_msgs:
    ea1, ea2 = st.columns(2)
    with ea1:
        active = {k: v for k, v in _topics(all_messages).items() if v > 0}
        if active:
            st.plotly_chart(
                _donut(
                    list(active.keys()),
                    list(active.values()),
                    "What you engage with most",
                ),
                width="stretch",
                config={"displayModeBar": False},
            )
        else:
            st.markdown(
                '<div class="empty">Topic breakdown appears after more messages.</div>',
                unsafe_allow_html=True,
            )
    with ea2:
        words = _top_words(all_messages, 18)
        if words:
            lb, ct = zip(*words)
            st.plotly_chart(
                _hbar(list(lb), list(ct), "Your most-used words"),
                width="stretch",
                config={"displayModeBar": False},
            )
        else:
            st.markdown(
                '<div class="empty">Vocabulary heatmap appears after chatting.</div>',
                unsafe_allow_html=True,
            )

    spark_tids = list(dict.fromkeys(m["thread_id"] for m in all_messages))
    if len(spark_tids) > 1:
        sp1, sp2 = st.columns([2, 1])
        with sp1:
            tc = [
                sum(1 for m in all_messages if m["thread_id"] == t) for t in spark_tids
            ]
            tl = [thread_titles.get(t, f"Chat {i+1}") for i, t in enumerate(spark_tids)]
            st.plotly_chart(
                _spark(tl, tc, "Messages per conversation"),
                width="stretch",
                config={"displayModeBar": False},
            )
        with sp2:
            st.plotly_chart(
                _role_bar(len(human_msgs), len(ai_msgs)),
                width="stretch",
                config={"displayModeBar": False},
            )

    all_words = _top_words(all_messages, n=40)
    if all_words:
        mx = all_words[0][1] or 1
        html = ""
        for word, cnt in all_words:
            sz = 0.72 + (cnt / mx) * 1.0
            op = 0.45 + (cnt / mx) * 0.55
            hue = 200 + int((cnt / mx) * 90)
            html += f'<span class="wc-item" title="{cnt} uses" style="font-size:{sz:.2f}rem;opacity:{op:.2f};color:hsl({hue},65%,68%)">{word}</span>'
        st.markdown(
            '<div class="section-hd">Vocabulary Heatmap</div>', unsafe_allow_html=True
        )
        st.markdown(
            f'<div style="background:#0d0d1a;border:1px solid #1a1a2e;border-radius:12px;padding:22px 26px;line-height:2.8">{html}</div>',
            unsafe_allow_html=True,
        )
else:
    st.markdown(
        '<div class="empty" style="padding:60px"><div style="font-size:2rem;margin-bottom:16px">💬</div>'
        '<b style="color:#e2e2f0;font-size:1rem">No conversation data yet</b><br><br>'
        "Start chatting then click <b>🔄 Refresh Data</b>.</div>",
        unsafe_allow_html=True,
    )

# Docs
if thread_docs:
    st.markdown(
        '<div class="section-hd">Indexed Documents</div>', unsafe_allow_html=True
    )
    d1, d2 = st.columns(2)
    for i, doc in enumerate(thread_docs):
        icon = "📝" if doc.get("filetype") == ".docx" else "📄"
        title = thread_titles.get(doc["thread_id"], f'Chat {doc["thread_id"][-6:]}')
        col = d1 if i % 2 == 0 else d2
        col.markdown(
            f'<div class="doc-row"><div><span style="font-size:1rem">{icon}</span>'
            f'<span style="font-weight:600;margin-left:8px;color:#e2e2f0;font-size:.88rem">{doc.get("filename","—")}</span>'
            f'<span style="color:#454560;font-size:.7rem;margin-left:8px">in "{title}"</span></div>'
            f'<div style="color:#6366f1;font-size:.72rem">{doc.get("chunks","?")} chunks</div></div>',
            unsafe_allow_html=True,
        )

# Tools
st.markdown(
    '<div class="section-hd">🛠 What This Chatbot Can Do</div>', unsafe_allow_html=True
)
tools_data = [
    (
        "🔍",
        "Web Search",
        "Real-time DuckDuckGo search for current events.",
        ["Live", "Source-aware"],
    ),
    (
        "📈",
        "Stock Prices",
        "Latest quotes for any ticker via Alpha Vantage.",
        ["Real-time", "Any ticker"],
    ),
    (
        "🔢",
        "Calculator",
        "Exact math evaluation — never hallucinates.",
        ["Exact", "All operators"],
    ),
    (
        "💸",
        "Expenses",
        "Natural language tracking with HITL approval.",
        ["HITL", "Categories"],
    ),
    ("📄", "Doc Q&A", "Upload PDF/DOCX, ask via MMR semantic search.", ["PDF", "DOCX"]),
    (
        "🧠",
        "Memory",
        "Remembers your name, projects, and preferences.",
        ["Cross-session", "Deduped"],
    ),
    (
        "🌐",
        "Multilingual",
        "Auto-detects Nepali/Hindi, replies in kind.",
        ["Nepali", "Hindi"],
    ),
    (
        "⚡",
        "MCP Tools",
        "FastMCP stdio — add new tools in minutes.",
        ["FastMCP", "Extensible"],
    ),
]
cols = st.columns(4)
for i, (icon, title, desc, badges) in enumerate(tools_data):
    with cols[i % 4]:
        bh = "".join(f'<span class="feat-badge">{b}</span>' for b in badges)
        st.markdown(
            f'<div class="feat-card"><div class="feat-icon">{icon}</div>'
            f'<div class="feat-title">{title}</div><div class="feat-desc">{desc}</div>'
            f'<div style="margin-top:10px">{bh}</div></div>',
            unsafe_allow_html=True,
        )
    if (i + 1) % 4 == 0 and i + 1 < len(tools_data):
        st.markdown("<br>", unsafe_allow_html=True)
        cols = st.columns(4)

st.markdown(
    f'<div class="footer">MCP Chat · {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>',
    unsafe_allow_html=True,
)

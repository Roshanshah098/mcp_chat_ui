import os
import sqlite3
import requests
from typing import Annotated, List
from typing_extensions import TypedDict

from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.messages import BaseMessage
from langchain_core.tools import tool
from langchain_community.tools import DuckDuckGoSearchRun
from langgraph.graph import StateGraph, START
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.sqlite import SqliteSaver

load_dotenv()

# ── Tools ─────────────────────────────────────────────────────
search_tool = DuckDuckGoSearchRun(region="us-en", safesearch="Off", time="y")


@tool
def calculator(query: str) -> str:
    """A calculator tool that can evaluate simple math expressions.
    Perform a basic arithmetic operation on two numbers.
    Supported operations: +, -, *, /
    Usage: <number> <operator> <number>
    """
    try:
        parts = query.split()
        if len(parts) != 3:
            return "Invalid format. Use: <number> <operator> <number>"

        num1, operator, num2 = parts
        num1, num2 = float(num1), float(num2)

        if operator == "+":
            return str(num1 + num2)
        elif operator == "-":
            return str(num1 - num2)
        elif operator == "*":
            return str(num1 * num2)
        elif operator == "/":
            if num2 == 0:
                return "Error: Division by zero"
            return str(num1 / num2)
        else:
            return "Unsupported operator. Use one of: +, -, *, /"

    except Exception as e:
        return f"Error: {str(e)}"


@tool
def get_nepse_stock_price(symbol: str) -> dict:
    """
    Fetch latest stock price for any NEPSE-listed company. No API key needed.
    Examples: 'NABIL', 'NIBL', 'CHCL', 'NLIC', 'SCB'
    """
    url = f"https://nepsetty.kokomo.workers.dev/api?symbol={symbol.strip().upper()}"
    r = requests.get(url, timeout=10)

    if r.status_code == 404:
        return {"error": f"'{symbol}' not found on NEPSE. Check the symbol."}
    if r.status_code != 200:
        return {"error": f"HTTP {r.status_code}"}

    d = r.json()

    return {
        "symbol": symbol.upper(),
        "price": d.get("currentPrice") or d.get("ltp"),
        "change": d.get("change") or d.get("pointChange"),
        "change%": d.get("changePercent") or d.get("percentageChange"),
        "volume": d.get("volume") or d.get("totalTradeQuantity"),
        "date": d.get("lastUpdated") or d.get("asOf"),
    }


@tool
def get_stock_price(symbol: str) -> dict:
    """
    Fetch latest stock price for any international stock using Yahoo Finance.
    No API key needed. Works for US, India, UK, Crypto etc.

    Examples:
        'AAPL'          → Apple (US)
        'TSLA'          → Tesla (US)
        'RELIANCE.NS'   → Reliance Industries (NSE India)
        'BTC-USD'       → Bitcoin
        'HSBA.L'        → HSBC (London)
    """
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol.strip().upper()}?interval=1d&range=1d"
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, headers=headers, timeout=10)

    if r.status_code != 200:
        return {
            "error": f"HTTP {r.status_code} — check symbol (e.g. 'AAPL', 'TSLA', 'RELIANCE.NS')"
        }

    try:
        meta = r.json()["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice")
        prev_close = meta.get("chartPreviousClose") or meta.get("previousClose")
        change = round(price - prev_close, 2) if price and prev_close else None
        change_pct = (
            round(change / prev_close * 100, 2) if change and prev_close else None
        )

        return {
            "symbol": symbol.upper(),
            "name": meta.get("longName") or meta.get("shortName"),
            "price": price,
            "change": f"{'+' if change >= 0 else ''}{change}" if change else None,
            "change%": (
                f"{'+' if change_pct >= 0 else ''}{change_pct}%" if change_pct else None
            ),
            "volume": meta.get("regularMarketVolume"),
            "currency": meta.get("currency"),
            "exchange": meta.get("exchangeName"),
        }

    except (KeyError, IndexError, TypeError):
        return {
            "error": f"No data found for '{symbol}'. It may be delisted or invalid."
        }


# ── LLM + Tools ───────────────────────────────────────────────

tool_list = [search_tool, calculator, get_nepse_stock_price, get_stock_price]

llm = ChatGroq(model="llama-3.1-8b-instant")

llm_with_tools = llm.bind_tools(tool_list)


# ── State ─────────────────────────────────────────────────────


class ChatState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]


# ── Nodes ─────────────────────────────────────────────────────


def chat_node(state: ChatState) -> ChatState:
    """LLM node that may answer or request a tool call."""
    messages = state["messages"]
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}


tool_node = ToolNode(tools=tool_list)

# ── Graph + Checkpointer ──────────────────────────────────────

conn = sqlite3.connect(database="chatbot.db", check_same_thread=False)
checkpointer = SqliteSaver(conn=conn)

graph = StateGraph(ChatState)
graph.add_node("chat_node", chat_node)
graph.add_node("tools", tool_node)

graph.add_edge(START, "chat_node")
graph.add_conditional_edges("chat_node", tools_condition)
graph.add_edge("tools", "chat_node")

botbhai = graph.compile(checkpointer=checkpointer)


# ── Helper ────────────────────────────────────────────────────
def retrieve_all_threads():
    all_threads = set()  # for unique thread ids
    for checkpoint in checkpointer.list(None):
        all_threads.add(checkpoint.config["configurable"]["thread_id"])
    return list(all_threads)

from fastmcp import FastMCP
import os
import sqlite3
import json

DB_PATH = os.path.join(os.path.dirname(__file__), "expenses.db")
CATEGORIES_PATH = os.path.join(os.path.dirname(__file__), "categories.json")

mcp = FastMCP("ExpenseTracker")


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    with get_conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                subcategory TEXT DEFAULT '',
                note TEXT DEFAULT '',
                type TEXT DEFAULT 'expense'
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS credits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                amount REAL NOT NULL,
                source TEXT NOT NULL,
                note TEXT DEFAULT ''
            )
        """)


init_db()


@mcp.resource("expense://categories", mime_type="application/json")
def get_categories():
    """Returns all available expense categories and their subcategories."""
    with open(CATEGORIES_PATH, "r", encoding="utf-8") as f:
        return f.read()


@mcp.tool()
def add_expense(
    date: str, amount: float, category: str, subcategory: str = "", note: str = ""
):
    """
    Add a new expense. Date format: YYYY-MM-DD.
    Always read the resource at expense://categories first to pick the correct
    category and subcategory. If the mentioned category or subcategory is not
    present in the list, use the closest matching one based on context.
    """
    with get_conn() as c:
        cur = c.execute(
            "INSERT INTO expenses(date, amount, category, subcategory, note, type) VALUES (?,?,?,?,?,?)",
            (date, amount, category, subcategory, note, "expense"),
        )
        return {"status": "ok", "id": cur.lastrowid}


@mcp.tool()
def list_expenses(start_date: str, end_date: str):
    """List expense entries within an inclusive date range. Date format: YYYY-MM-DD"""
    with get_conn() as c:
        cur = c.execute(
            """
            SELECT id, date, amount, category, subcategory, note
            FROM expenses
            WHERE type='expense' AND date BETWEEN ? AND ?
            ORDER BY date ASC
            """,
            (start_date, end_date),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


@mcp.tool()
def edit_expense(
    id: int,
    date: str = None,
    amount: float = None,
    category: str = None,
    subcategory: str = None,
    note: str = None,
):
    """Edit an existing expense by id. Only pass fields you want to change."""
    with get_conn() as c:
        row = c.execute(
            "SELECT date, amount, category, subcategory, note FROM expenses WHERE id=?",
            (id,),
        ).fetchone()
        if not row:
            return {"status": "error", "message": f"No expense with id {id}"}
        d, a, cat, sub, n = row
        c.execute(
            "UPDATE expenses SET date=?, amount=?, category=?, subcategory=?, note=? WHERE id=?",
            (
                date if date is not None else d,
                amount if amount is not None else a,
                category if category is not None else cat,
                subcategory if subcategory is not None else sub,
                note if note is not None else n,
                id,
            ),
        )
        return {"status": "ok", "updated_id": id}


@mcp.tool()
def delete_expense(id: int):
    """Delete an expense by id"""
    with get_conn() as c:
        cur = c.execute("DELETE FROM expenses WHERE id=?", (id,))
        if cur.rowcount == 0:
            return {"status": "error", "message": f"No expense with id {id}"}
        return {"status": "ok", "deleted_id": id}


@mcp.tool()
def add_credit(date: str, amount: float, source: str, note: str = ""):
    """Add income or salary. Date format: YYYY-MM-DD. Source example: salary, freelance, bonus"""
    with get_conn() as c:
        cur = c.execute(
            "INSERT INTO credits(date, amount, source, note) VALUES (?,?,?,?)",
            (date, amount, source, note),
        )
        return {"status": "ok", "id": cur.lastrowid}


@mcp.tool()
def list_credits(start_date: str, end_date: str):
    """List credit/income entries within an inclusive date range. Date format: YYYY-MM-DD"""
    with get_conn() as c:
        cur = c.execute(
            """
            SELECT id, date, amount, source, note
            FROM credits
            WHERE date BETWEEN ? AND ?
            ORDER BY date ASC
            """,
            (start_date, end_date),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


@mcp.tool()
def summarize(start_date: str, end_date: str):
    """
    Summarize expenses vs income and show balance within a date range.
    Date format: YYYY-MM-DD
    Example: summarize(start_date='2026-05-01', end_date='2026-05-31')
    """
    with get_conn() as c:
        total_exp = c.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM expenses WHERE type='expense' AND date BETWEEN ? AND ?",
            (start_date, end_date),
        ).fetchone()[0]

        total_credit = c.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM credits WHERE date BETWEEN ? AND ?",
            (start_date, end_date),
        ).fetchone()[0]

        by_category = c.execute(
            """
            SELECT category, COALESCE(SUM(amount), 0)
            FROM expenses
            WHERE type='expense' AND date BETWEEN ? AND ?
            GROUP BY category
            """,
            (start_date, end_date),
        ).fetchall()

        return {
            "period": f"{start_date} to {end_date}",
            "total_expenses": round(total_exp, 2),
            "total_credits": round(total_credit, 2),
            "balance": round(total_credit - total_exp, 2),
            "by_category": {row[0]: round(row[1], 2) for row in by_category},
        }


if __name__ == "__main__":
    mcp.run(transport="stdio")

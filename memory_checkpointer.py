import asyncio
import atexit
import os
import selectors
import sys
import threading
import logging

# Suppress harmless Windows asyncio connection-reset warnings
logging.getLogger("asyncio").setLevel(logging.CRITICAL)

POSTGRES_URI = os.getenv(
    "POSTGRES_URI",
    "postgresql://postgres:postgres@localhost:5442/postgres?sslmode=disable",
)

# ── Single shared event loop ───────────────────────────────────
if sys.platform == "win32":
    _loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
else:
    _loop = asyncio.new_event_loop()

_ASYNC_THREAD = threading.Thread(target=_loop.run_forever, daemon=True)
_ASYNC_THREAD.start()


def _run(coro):
    return asyncio.run_coroutine_threadsafe(coro, _loop).result()


_async_pool = None


def _shutdown_async_pool():
    global _async_pool
    if _async_pool is None:
        return
    try:
        future = asyncio.run_coroutine_threadsafe(_async_pool.close(), _loop)
        future.result(timeout=5)
        print("[STM] async pool closed cleanly.")
    except Exception as e:
        print(f"[STM] pool close warning (safe to ignore): {e}")
    finally:
        _async_pool = None


atexit.register(_shutdown_async_pool)


# STM — AsyncPostgresSaver (per thread_id)
def init_stm():
    global _async_pool
    try:
        from psycopg_pool import AsyncConnectionPool
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        async def _make_pg_stm():
            pool = AsyncConnectionPool(
                conninfo=POSTGRES_URI,
                max_size=10,
                open=False,
                kwargs={"autocommit": True},
            )
            await pool.open()
            saver = AsyncPostgresSaver(pool)
            await saver.setup()
            return pool, saver

        pool, saver = _run(_make_pg_stm())
        _async_pool = pool
        print("[STM] ✅ AsyncPostgresSaver connected (short-term memory)")
        return saver
    except Exception as pg_err:
        print(f"[STM] ⚠️ AsyncPostgresSaver unavailable: {pg_err}")

    try:
        import aiosqlite
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        async def _make_sqlite_stm():
            conn = await aiosqlite.connect("chatbot.db")
            return AsyncSqliteSaver(conn)

        saver = _run(_make_sqlite_stm())
        print("[STM] AsyncSqliteSaver fallback active (short-term memory)")
        return saver
    except Exception as sq_err:
        print(f"[STM] ❌ SQLite fallback also failed: {sq_err}")
        return None


# LTM — PostgresStore (per user_id)
def init_ltm():
    try:
        from psycopg_pool import ConnectionPool
        from langgraph.store.postgres import PostgresStore

        pool = ConnectionPool(
            conninfo=POSTGRES_URI,
            max_size=10,
            kwargs={"autocommit": True},
        )
        store = PostgresStore(pool)
        store.setup()
        print("[LTM] ✅ PostgresStore connected (long-term memory)")
        return store
    except Exception as pg_err:
        print(f"[LTM] ⚠️ PostgresStore unavailable — LTM disabled: {pg_err}")
        return None

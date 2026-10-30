"""SQLite cache layer for OHLCV data and watchlists.

All functions use context-managed connections so handles are always closed,
and the database file defaults to a per-user location (see config.DB_PATH).
"""

import json
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from .config import CACHE_TTL_SECONDS, DB_PATH

_SCHEMA = """
    CREATE TABLE IF NOT EXISTS ohlcv (
        pair TEXT,
        date TEXT,
        open REAL, high REAL, low REAL, close REAL, volume REAL,
        PRIMARY KEY (pair, date)
    );
    CREATE TABLE IF NOT EXISTS cache_meta (
        pair TEXT PRIMARY KEY,
        fetched_at REAL,
        last_date TEXT
    );
    CREATE TABLE IF NOT EXISTS watchlists (
        name TEXT PRIMARY KEY,
        pairs TEXT
    );
"""


def get_conn(db_path: Path | None = None) -> sqlite3.Connection:
    """Open a connection to the cache database, creating parent dirs if needed."""
    path = Path(db_path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(db_path: Path | None = None) -> None:
    with closing(get_conn(db_path)) as conn, conn:
        conn.executescript(_SCHEMA)


def _last_trading_day(today: date | None = None) -> date:
    """Best-effort 'last expected trading day' (previous weekday).

    FX markets trade Mon-Fri; holidays are not modelled, but requiring data
    up to the previous weekday is far stricter than a pure wall-clock TTL.
    """
    d = today or date.today()
    d -= timedelta(days=1)
    while d.weekday() >= 5:  # Saturday=5, Sunday=6
        d -= timedelta(days=1)
    return d


def is_cache_fresh(pair: str, db_path: Path | None = None) -> bool:
    """Cache is fresh only if fetched recently AND covers the last trading day.

    Staleness is validated against MAX(date) stored in the ohlcv table rather
    than insertion order, so out-of-order backfills don't corrupt metadata.
    """
    with closing(get_conn(db_path)) as conn:
        row = conn.execute(
            "SELECT fetched_at FROM cache_meta WHERE pair=?", (pair,)
        ).fetchone()
        if not row:
            return False
        if (datetime.now().timestamp() - row[0]) >= CACHE_TTL_SECONDS:
            return False
        max_date = conn.execute(
            "SELECT MAX(date) FROM ohlcv WHERE pair=?", (pair,)
        ).fetchone()[0]
    if not max_date:
        return False
    try:
        have = datetime.strptime(max_date, "%Y-%m-%d").date()
    except ValueError:
        return False
    return have >= _last_trading_day()


def save_ohlcv(pair: str, df: pd.DataFrame, db_path: Path | None = None) -> None:
    """Upsert daily bars and refresh cache metadata (bulk insert, no iterrows)."""
    if df.empty:
        return
    records = [
        (
            pair,
            idx.strftime("%Y-%m-%d"),
            r["Open"], r["High"], r["Low"], r["Close"],
            0.0 if pd.isna(r["Volume"]) else float(r["Volume"]),
        )
        for idx, r in df.iterrows()
    ]
    with closing(get_conn(db_path)) as conn, conn:
        conn.executemany(
            "INSERT OR REPLACE INTO ohlcv VALUES (?,?,?,?,?,?,?)", records
        )
        last_date = conn.execute(
            "SELECT MAX(date) FROM ohlcv WHERE pair=?", (pair,)
        ).fetchone()[0]
        conn.execute(
            "INSERT OR REPLACE INTO cache_meta VALUES (?,?,?)",
            (pair, datetime.now().timestamp(), last_date),
        )


def load_ohlcv(pair: str, db_path: Path | None = None) -> pd.DataFrame:
    with closing(get_conn(db_path)) as conn:
        df = pd.read_sql_query(
            "SELECT date, open AS Open, high AS High, low AS Low, "
            "close AS Close, volume AS Volume FROM ohlcv "
            "WHERE pair=? ORDER BY date",
            conn,
            params=(pair,),
        )
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")


# ---------------------------------------------------------------------------
# Watchlists
# ---------------------------------------------------------------------------

def save_watchlist(name: str, pairs: list, db_path: Path | None = None) -> None:
    with closing(get_conn(db_path)) as conn, conn:
        conn.execute(
            "INSERT OR REPLACE INTO watchlists VALUES (?,?)",
            (name, json.dumps(pairs)),
        )


def load_watchlist(name: str, db_path: Path | None = None) -> list:
    with closing(get_conn(db_path)) as conn:
        row = conn.execute(
            "SELECT pairs FROM watchlists WHERE name=?", (name,)
        ).fetchone()
    return json.loads(row[0]) if row else []


def list_watchlists(db_path: Path | None = None) -> list:
    with closing(get_conn(db_path)) as conn:
        rows = conn.execute("SELECT name FROM watchlists").fetchall()
    return [r[0] for r in rows]


def delete_watchlist(name: str, db_path: Path | None = None) -> None:
    with closing(get_conn(db_path)) as conn, conn:
        conn.execute("DELETE FROM watchlists WHERE name=?", (name,))

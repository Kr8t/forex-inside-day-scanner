"""
Forex Inside-Day Scanner
Scans major FX pairs for daily inside-day compressions and creates a trading plan.
"""

import sqlite3
import time
import json
import argparse
from pathlib import Path
import pandas as pd
import yfinance as yf
from rich.console import Console
from rich.table import Table
from rich import box

# ============================================================================
# CONFIGURATION
# ============================================================================

MAJOR_PAIRS = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF",
    "AUDUSD", "USDCAD", "NZDUSD"
]

YEN_EUR_CROSSES = [
    "EURJPY", "EURGBP", "EURCHF", "EURAUD",
    "EURCAD", "EURNZD", "GBPJPY", "CHFJPY",
    "AUDJPY", "CADJPY", "NZDJPY"
]

ALL_PAIRS = MAJOR_PAIRS + YEN_EUR_CROSSES

CACHE_TTL_SECONDS = 4 * 3600  # 4 hours
LOOKBACK_DAYS = 60
BREAKOUT_BUFFER = 0.0

DB_PATH = Path("forex.db")

# ============================================================================
# CACHE LAYER
# ============================================================================

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    conn = get_conn()
    conn.executescript("""
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
    """)
    conn.commit()
    conn.close()

def is_cache_fresh(pair: str) -> bool:
    conn = get_conn()
    row = conn.execute(
        "SELECT fetched_at FROM cache_meta WHERE pair=?", (pair,)
    ).fetchone()
    conn.close()
    if not row:
        return False
    return (time.time() - row[0]) < CACHE_TTL_SECONDS

def save_ohlcv(pair: str, df: pd.DataFrame):
    if df.empty:
        return
    conn = get_conn()
    records = [
        (pair, idx.strftime("%Y-%m-%d"),
         r.Open, r.High, r.Low, r.Close,
         0.0 if pd.isna(r.Volume) else float(r.Volume))
        for idx, r in df.iterrows()
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO ohlcv VALUES (?,?,?,?,?,?,?)", records
    )
    conn.execute(
        "INSERT OR REPLACE INTO cache_meta VALUES (?,?,?)",
        (pair, time.time(), records[-1][1])
    )
    conn.commit()
    conn.close()

def load_ohlcv(pair: str) -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query(
        "SELECT date, open AS Open, high AS High, low AS Low, close AS Close, volume AS Volume FROM ohlcv "
        "WHERE pair=? ORDER BY date",
        conn, params=(pair,)
    )
    conn.close()
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    return df

def save_watchlist(name: str, pairs: list):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO watchlists VALUES (?,?)",
        (name, json.dumps(pairs))
    )
    conn.commit()
    conn.close()

def load_watchlist(name: str) -> list:
    conn = get_conn()
    row = conn.execute(
        "SELECT pairs FROM watchlists WHERE name=?", (name,)
    ).fetchone()
    conn.close()
    return json.loads(row[0]) if row else []

def list_watchlists() -> list:
    conn = get_conn()
    rows = conn.execute("SELECT name FROM watchlists").fetchall()
    conn.close()
    return [r[0] for r in rows]

def delete_watchlist(name: str):
    conn = get_conn()
    conn.execute("DELETE FROM watchlists WHERE name=?", (name,))
    conn.commit()
    conn.close()

# ============================================================================
# DATA FETCHER
# ============================================================================

def to_ticker(pair: str) -> str:
    return f"{pair}=X"

def fetch_pair(pair: str, force: bool = False) -> pd.DataFrame:
    if not force and is_cache_fresh(pair):
        df = load_ohlcv(pair)
        if not df.empty:
            return df

    ticker = yf.Ticker(to_ticker(pair))
    df = ticker.history(period=f"{LOOKBACK_DAYS}d", interval="1d")
    if df.empty:
        return df
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.index = df.index.tz_localize(None)
    save_ohlcv(pair, df)
    return df

def fetch_all(pairs: list, force: bool = False) -> dict:
    init_db()
    out = {}
    for p in pairs:
        try:
            out[p] = fetch_pair(p, force=force)
        except Exception as e:
            print(f"[warn] {p}: {e}")
            out[p] = pd.DataFrame()
    return out

# ============================================================================
# SCANNER LOGIC
# ============================================================================

def classify_inside_day(row) -> str:
    if row["Close"] > row["Open"]:
        return "green"
    elif row["Close"] < row["Open"]:
        return "red"
    return "neutral"

def _pip_size(pair: str) -> float:
    return 0.01 if pair.endswith("JPY") else 0.0001

def get_daily_plan(pair: str, df: pd.DataFrame) -> dict | None:
    if df is None or len(df) < 3:
        return None
    
    prev_candle = df.iloc[-2] 
    day_before_prev = df.iloc[-3] 
    
    if prev_candle["High"] < day_before_prev["High"] and prev_candle["Low"] > day_before_prev["Low"]:
        return {
            "pair": pair,
            "inside_date": df.index[-2],
            "color": classify_inside_day(prev_candle),
            "breakout_up": prev_candle["High"],
            "breakout_down": prev_candle["Low"],
            "range": round(prev_candle["High"] - prev_candle["Low"], 5)
        }
    return None

# ============================================================================
# WATCHLIST MANAGEMENT
# ============================================================================

def create_watchlist(name: str, pairs: list):
    unknown = [p for p in pairs if p not in ALL_PAIRS]
    if unknown:
        raise ValueError(f"Unknown pairs: {unknown}")
    save_watchlist(name, pairs)

def get_watchlist(name: str) -> list:
    return load_watchlist(name)

# ============================================================================
# UI / OUTPUT
# ============================================================================

console = Console()
COLOR_MAP = {"green": "bold green", "red": "bold red", "neutral": "yellow"}

def print_daily_plan(plans: list):
    if not plans:
        console.print("[bold yellow]No Inside-Day setups found for today's plan.[/bold yellow]\n")
        return
        
    table = Table(title="🎯 TODAY'S PLAN (Based on Previous Day's Inside Day)", box=box.DOUBLE_EDGE)
    table.add_column("Pair", style="cyan")
    table.add_column("ID Date")
    table.add_column("Color")
    table.add_column("Buy Stop (Break ↑)", style="green")
    table.add_column("Sell Stop (Break ↓)", style="red")
    table.add_column("Range (Pips)")
    
    for p in plans:
        pip_size = 0.01 if p["pair"].endswith("JPY") else 0.0001
        pips = round(p["range"] / pip_size, 1)
        
        table.add_row(
            p["pair"],
            p["inside_date"].strftime("%Y-%m-%d"),
            p["color"],
            f"{p['breakout_up']:.5f}",
            f"{p['breakout_down']:.5f}",
            f"{pips} pips",
            style=COLOR_MAP[p["color"]],
        )
    console.print(table)
    console.print()

# ============================================================================
# MAIN EXECUTION
# ============================================================================

def run_scan(pairs: list, force: bool):
    data = fetch_all(pairs, force=force)
    daily_plans = []
    
    for p in pairs:
        df = data.get(p)
        if df is None or df.empty:
            continue
        
        plan = get_daily_plan(p, df)
        if plan:
            daily_plans.append(plan)

    print_daily_plan(daily_plans)

def main():
    ap = argparse.ArgumentParser(description="Forex Inside-Day Scanner")
    sub = ap.add_subparsers(dest="cmd")

    p_scan = sub.add_parser("scan", help="Scan pairs for inside days & breakouts")
    p_scan.add_argument("--set", choices=["majors", "crosses", "all"], default="all")
    p_scan.add_argument("--watchlist", help="Use a saved watchlist")
    p_scan.add_argument("--force", action="store_true", help="Bypass cache")

    p_wl = sub.add_parser("wl", help="Manage watchlists")
    wlsub = p_wl.add_subparsers(dest="wlcmd")
    wlsub.add_parser("list")
    w_create = wlsub.add_parser("create")
    w_create.add_argument("name")
    w_create.add_argument("pairs", nargs="+")
    w_rm = wlsub.add_parser("rm")
    w_rm.add_argument("name")
    w_show = wlsub.add_parser("show")
    w_show.add_argument("name")

    args = ap.parse_args()

    if args.cmd == "scan":
        if args.watchlist:
            pairs = get_watchlist(args.watchlist)
            if not pairs:
                print(f"Watchlist '{args.watchlist}' is empty or missing.")
                return
        else:
            pairs = {
                "majors": MAJOR_PAIRS,
                "crosses": YEN_EUR_CROSSES,
                "all": ALL_PAIRS,
            }[args.set]
        run_scan(pairs, force=args.force)

    elif args.cmd == "wl":
        if args.wlcmd == "list":
            for n in list_watchlists():
                print(f"  • {n}: {load_watchlist(n)}")
        elif args.wlcmd == "create":
            create_watchlist(args.name, args.pairs)
            print(f"Created watchlist '{args.name}' with {args.pairs}")
        elif args.wlcmd == "rm":
            delete_watchlist(args.name)
            print(f"Removed '{args.name}'")
        elif args.wlcmd == "show":
            print(load_watchlist(args.name))
    else:
        ap.print_help()

if __name__ == "__main__":
    main()
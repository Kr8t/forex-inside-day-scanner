"""Configuration constants for the Forex Inside-Day Scanner."""

import os
from pathlib import Path

MAJOR_PAIRS = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF",
    "AUDUSD", "USDCAD", "NZDUSD",
]

YEN_EUR_CROSSES = [
    "EURJPY", "EURGBP", "EURCHF", "EURAUD",
    "EURCAD", "EURNZD", "GBPJPY", "CHFJPY",
    "AUDJPY", "CADJPY", "NZDJPY",
]

ALL_PAIRS = MAJOR_PAIRS + YEN_EUR_CROSSES

# Cache freshness: data older than this is re-fetched.
CACHE_TTL_SECONDS = 4 * 3600  # 4 hours
LOOKBACK_DAYS = 60

# Extra distance (in pips) beyond the inside-day high/low where
# breakout stop orders are placed. 0.0 means exactly at the level.
BREAKOUT_BUFFER_PIPS = float(os.environ.get("FOREX_BREAKOUT_BUFFER_PIPS", "0.0"))

# Number of most-recent completed sessions checked for inside days
# (1 = only the immediately previous session).
PLAN_LOOKBACK_SESSIONS = int(os.environ.get("FOREX_PLAN_LOOKBACK", "1"))

# Closed-in-Breakout (CIB) filter: a daily session whose *closing price* ends
# above the previous day's High, or below the previous day's Low.
# Optional pip buffer: set FOREX_CIB_BUFFER_PIPS to require the close to clear
# the prior range by N pips before the CIB flag triggers (0.0 = any breach).
# Legacy FOREX_BLACKOUT_* env vars are still honoured as fallbacks.
CIB_ENABLED = os.environ.get(
    "FOREX_CIB_ENABLED", os.environ.get("FOREX_BLACKOUT_ENABLED", "1")
) not in ("0", "false", "no")
CIB_BUFFER_PIPS = float(
    os.environ.get("FOREX_CIB_BUFFER_PIPS",
                   os.environ.get("FOREX_BLACKOUT_BUFFER_PIPS", "0.0"))
)

# Database path: override with FOREX_DB env var; defaults to a stable
# per-user location so the tool works from any directory.
DB_PATH = Path(
    os.environ.get("FOREX_DB", str(Path.home() / ".forex-scanner" / "forex.db"))
)

MIN_ROWS_FOR_ANALYSIS = 3

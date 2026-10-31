"""Inside-day detection, closed-in-breakout (CIB) filtering, and daily plan generation.

Terminology: a session that *closes* outside the previous day's high-low
range is called a **Closed in Breakout (CIB)** (historically also "blackout").
Internal keys keep the ``blackout`` name for cache/plan compatibility; user
- and CLI-facing text uses "Closed in Breakout (CIB)".
"""

import pandas as pd

from .config import (
    BLACKOUT_BUFFER_PIPS,
    BLACKOUT_ENABLED,
    BREAKOUT_BUFFER_PIPS,
    MIN_ROWS_FOR_ANALYSIS,
    PLAN_LOOKBACK_SESSIONS,
)


def pip_size(pair: str) -> float:
    """One pip is 0.01 for JPY-quoted pairs, 0.0001 otherwise."""
    return 0.01 if pair.endswith("JPY") else 0.0001


def classify_candle(row) -> str:
    if row["Close"] > row["Open"]:
        return "green"
    if row["Close"] < row["Open"]:
        return "red"
    return "neutral"


def completed_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Drop today's still-forming intraday bar from a daily series.

    yfinance returns the current (partial) session as the last row of the
    1d series; including it corrupts inside-day/CIB detection. A bar counts
    as partial when its date equals today (local). We conservatively treat
    any bar dated today as incomplete.
    """
    if df is None or df.empty:
        return df
    last = df.index[-1].normalize()
    if last == pd.Timestamp.today().normalize():
        return df.iloc[:-1]
    return df


def is_inside_day(candle, mother) -> bool:
    return candle["High"] < mother["High"] and candle["Low"] > mother["Low"]


def blackout_direction(candle, previous, buffer_pips: float = BLACKOUT_BUFFER_PIPS,
                       pip: float = 0.0001) -> str | None:
    """Return the direction a candle *closed* beyond the previous day's range.

    "Closed in Blackout" filter: the candle's close finishes outside the
    previous session's high-low range (above its high or below its low).
    ``buffer_pips`` (sized with ``pip``) lets callers require the close to
    clear the prior range by N pips before the flag triggers.

    Returns "up", "down", or None when the close stayed inside the range.
    """
    threshold = buffer_pips * pip
    if candle["Close"] > previous["High"] + threshold:
        return "up"
    if candle["Close"] < previous["Low"] - threshold:
        return "down"
    return None


def find_inside_day(bars: pd.DataFrame, lookback_sessions: int):
    """Return (candle_pos, mother_pos) of the newest inside day, or None."""
    n = min(lookback_sessions, len(bars) - 1)
    for offset in range(1, 1 + n):  # newest first
        candle = bars.iloc[-offset]
        mother = bars.iloc[-offset - 1]
        if is_inside_day(candle, mother):
            return -offset, -offset - 1
    return None


def get_daily_plan(pair: str, df: pd.DataFrame,
                   lookback_sessions: int = PLAN_LOOKBACK_SESSIONS,
                   apply_blackout_filter: bool = BLACKOUT_ENABLED) -> dict | None:
    """Build a daily plan combining inside-day setups and blackout closes.

    Two independent signals are evaluated over the most recent *completed*
    sessions (today's partial bar is excluded by ``completed_bars``):

    1. **Inside day** — the newest coil within ``lookback_sessions`` becomes
       the breakout plan; stop orders sit at the coil high/low plus the
       configured ``BREAKOUT_BUFFER_PIPS``.
    2. **Closed in Blackout** — the latest completed session closed *outside*
       the previous session's high-low range. Reported via the ``blackout``
       key as a dict (direction/date/color/high/low/range) or None. When
       ``apply_blackout_filter`` is True and the latest bar closed in
       blackout, any inside-day setup found further back is considered
       stale and suppressed (the coil has already been resolved).

    Returns None only when neither signal is present. Callers must treat
    empty/short data as fetch failures separately.
    """
    bars = completed_bars(df)
    if bars is None or len(bars) < MIN_ROWS_FOR_ANALYSIS:
        return None

    pip = pip_size(pair)
    buffer = BREAKOUT_BUFFER_PIPS * pip

    # --- Signal 2: Closed-in-Blackout on the latest completed bar ----------
    latest = bars.iloc[-1]
    previous = bars.iloc[-2]
    direction = blackout_direction(latest, previous, pip=pip)
    blackout = None
    if direction:
        blackout = {
            "direction": direction,
            "date": bars.index[-1],
            "previous_date": bars.index[-2],
            "color": classify_candle(latest),
            "close": round(float(latest["Close"]), 5),
            "prev_high": round(float(previous["High"]), 5),
            "prev_low": round(float(previous["Low"]), 5),
            "high": round(float(latest["High"]), 5),
            "low": round(float(latest["Low"]), 5),
            "range": round(float(latest["High"] - latest["Low"]), 5),
        }

    # --- Signal 1: Inside day ----------------------------------------------
    found = find_inside_day(bars, lookback_sessions)
    inside = None
    if found is not None:
        cpos, mpos = found
        candle = bars.iloc[cpos]
        inside = {
            "inside_date": bars.index[cpos],
            "mother_date": bars.index[mpos],
            "color": classify_candle(candle),
            "breakout_up": round(candle["High"] + buffer, 5),
            "breakout_down": round(candle["Low"] - buffer, 5),
            "range": round(candle["High"] - candle["Low"], 5),
        }

    # Blackout filter suppresses stale coils that were already resolved.
    if apply_blackout_filter and blackout:
        inside = None

    if inside is None and blackout is None:
        return None

    return {
        "pair": pair,
        "inside_day": inside,
        "blackout": blackout,
    }

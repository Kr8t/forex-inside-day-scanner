"""Inside-day detection, Closed-in-Breakout (CIB) filtering, and daily plans.

Definition: a session is a **Closed in Breakout (CIB)** when its *closing
price at the end of the day* finishes above the previous day's High, or
below the previous day's Low.  (A close merely touching the prior extreme
does not count; the close must finish beyond it.)

Historical note: this signal was previously labelled "blackout"; internal
keys still accept the legacy ``blackout`` name for backward compatibility,
but everything user-facing uses CIB.
"""

import pandas as pd

from .config import (
    BREAKOUT_BUFFER_PIPS,
    CIB_BUFFER_PIPS,
    CIB_ENABLED,
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
    any bar dated today as incomplete. Timestamps carrying a time component
    are compared by calendar day so intraday-stamped rows can't sneak past
    the guard.
    """
    if df is None or df.empty:
        return df
    last = pd.Timestamp(df.index[-1]).normalize()
    if last == pd.Timestamp.today().normalize():
        return df.iloc[:-1]
    return df


def is_inside_day(candle, mother) -> bool:
    return candle["High"] < mother["High"] and candle["Low"] > mother["Low"]


def cib_direction(candle, previous, buffer_pips: float = CIB_BUFFER_PIPS,
                  pip: float = 0.0001) -> str | None:
    """Return the direction a daily candle *closed* beyond the previous day.

    Closed in Breakout (CIB): the candle's closing price finishes above the
    previous day's High ("up") or below the previous day's Low ("down").
    A close exactly at — or inside — the prior extremes returns None.
    ``buffer_pips`` (sized with ``pip``) optionally requires the close to
    clear the prior High/Low by N pips before the flag triggers.
    """
    threshold = buffer_pips * pip
    if candle["Close"] > previous["High"] + threshold:
        return "up"
    if candle["Close"] < previous["Low"] - threshold:
        return "down"
    return None


# Deprecated alias kept so external callers/tests using the old name work.
blackout_direction = cib_direction


def find_inside_day(bars: pd.DataFrame, lookback_sessions: int):
    """Return (candle_pos, mother_pos) of the newest *actionable* inside day.

    Only a coil on the most recent completed session (offset 1) can be traded
    with fresh stop levels this week; older coils are historical and their
    breakout levels have likely already been triggered.  ``lookback_sessions``
    therefore caps how far back we bother checking, but setups older than the
    latest bar are never returned as plans.
    """
    if len(bars) < MIN_ROWS_FOR_ANALYSIS:
        return None
    candle = bars.iloc[-1]
    mother = bars.iloc[-2]
    if lookback_sessions >= 1 and is_inside_day(candle, mother):
        return -1, -2
    return None


def get_daily_plan(pair: str, df: pd.DataFrame,
                   lookback_sessions: int = PLAN_LOOKBACK_SESSIONS,
                   apply_cib_filter: bool = CIB_ENABLED,
                   apply_blackout_filter: bool | None = None) -> dict | None:
    """Build a daily plan combining inside-day setups and CIB closes.

    Two independent signals are evaluated over the most recent *completed*
    sessions (today's partial bar is excluded by ``completed_bars``):

    1. **Inside day** — the newest coil within ``lookback_sessions`` becomes
       the breakout plan; stop orders sit at the coil high/low plus the
       configured ``BREAKOUT_BUFFER_PIPS``.
    2. **Closed in Breakout (CIB)** — the latest completed daily session
       closed above the previous day's High or below its Low. Reported via
       the ``cib`` key as a dict (direction/date/color/close/prev_high/
       prev_low/high/low/range) or None. When ``apply_cib_filter`` is True
       and the latest bar is a CIB, any inside-day setup found further back
       is considered stale and suppressed (the coil has already resolved).

    ``apply_blackout_filter`` is accepted as a deprecated alias for
    ``apply_cib_filter``; the plan dict also keeps a mirrored ``blackout``
    key for backward compatibility.

    Returns None only when neither signal is present. Callers must treat
    empty/short data as fetch failures separately.
    """
    if apply_blackout_filter is not None:
        apply_cib_filter = apply_blackout_filter
    bars = completed_bars(df)
    if bars is None or len(bars) < MIN_ROWS_FOR_ANALYSIS:
        return None

    pip = pip_size(pair)
    buffer = BREAKOUT_BUFFER_PIPS * pip

    # --- Signal 2: Closed in Breakout (CIB) on the latest completed bar ----
    latest = bars.iloc[-1]
    previous = bars.iloc[-2]
    direction = cib_direction(latest, previous, pip=pip)
    cib = None
    if direction:
        cib = {
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

    # CIB filter suppresses stale coils that were already resolved.
    if apply_cib_filter and cib:
        inside = None

    if inside is None and cib is None:
        return None

    return {
        "pair": pair,
        "inside_day": inside,
        "cib": cib,
        # Deprecated mirror of the same dict under the old "blackout" name.
        "blackout": cib,
    }

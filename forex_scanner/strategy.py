"""Inside-day detection and daily trading-plan generation."""

import pandas as pd

from .config import BREAKOUT_BUFFER_PIPS, MIN_ROWS_FOR_ANALYSIS, PLAN_LOOKBACK_SESSIONS


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
    1d series; including it corrupts inside-day detection. A bar counts as
    partial when its date is strictly after the most recent *expected* close.
    We conservatively treat any bar dated today (local) as incomplete.
    """
    if df is None or df.empty:
        return df
    last = df.index[-1].normalize()
    if last == pd.Timestamp.today().normalize():
        return df.iloc[:-1]
    return df


def is_inside_day(candle, mother) -> bool:
    return candle["High"] < mother["High"] and candle["Low"] > mother["Low"]


def get_daily_plan(pair: str, df: pd.DataFrame,
                   lookback_sessions: int = PLAN_LOOKBACK_SESSIONS) -> dict | None:
    """Build a breakout plan from the most recent inside-day pattern.

    Scans the last ``lookback_sessions`` completed sessions (candle i vs.
    mother candle i+1). The newest inside day wins. Breakout levels include
    the configured buffer (in pips). Returns None when no setup exists —
    callers must separately handle empty/short data as fetch failures.
    """
    bars = completed_bars(df)
    if bars is None or len(bars) < MIN_ROWS_FOR_ANALYSIS:
        return None

    pip = pip_size(pair)
    buffer = BREAKOUT_BUFFER_PIPS * pip

    n = min(lookback_sessions, len(bars) - 1)
    for offset in range(1, 1 + n):  # iloc[-1], iloc[-2], ... newest first
        candle = bars.iloc[-offset]
        mother = bars.iloc[-offset - 1]
        if is_inside_day(candle, mother):
            return {
                "pair": pair,
                "inside_date": bars.index[-offset],
                "mother_date": bars.index[-offset - 1],
                "color": classify_candle(candle),
                "breakout_up": round(candle["High"] + buffer, 5),
                "breakout_down": round(candle["Low"] - buffer, 5),
                "range": round(candle["High"] - candle["Low"], 5),
            }
    return None

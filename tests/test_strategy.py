"""Unit tests for inside-day detection and plan generation."""

import pandas as pd

from forex_scanner import strategy
from tests.conftest import make_df

# Mother day: wide range 1.00–1.10; Inside day: 1.02–1.05 (green).
MOTHER = (1.05, 1.10, 1.00, 1.04)   # red mother
INSIDE = (1.02, 1.05, 1.02, 1.05)   # green inside
OUTSIDE = (1.00, 1.12, 0.99, 1.11)  # not inside


def test_detects_inside_day():
    df = make_df([MOTHER, MOTHER, INSIDE])
    plan = strategy.get_daily_plan("EURUSD", df)
    assert plan is not None
    assert plan["pair"] == "EURUSD"
    assert plan["color"] == "green"
    assert plan["breakout_up"] == 1.05
    assert plan["breakout_down"] == 1.02


def test_no_inside_day_returns_none():
    df = make_df([MOTHER, INSIDE, OUTSIDE])
    assert strategy.get_daily_plan("EURUSD", df) is None


def test_requires_min_rows():
    df = make_df([MOTHER, INSIDE])  # only 2 bars
    assert strategy.get_daily_plan("EURUSD", df) is None
    assert strategy.get_daily_plan("EURUSD", None) is None
    assert strategy.get_daily_plan("EURUSD", pd.DataFrame()) is None


def test_partial_today_bar_is_excluded():
    """A forming bar dated today must not be used as the inside candle."""
    good = make_df([MOTHER, MOTHER, INSIDE])
    # Append a *partial* bar dated today that breaks the pattern.
    today = pd.Timestamp.today().normalize()
    partial = pd.DataFrame(
        {"Open": [1.20], "High": [1.30], "Low": [1.19], "Close": [1.29], "Volume": [0.0]},
        index=[today],
    )
    df = pd.concat([good, partial])
    plan = strategy.get_daily_plan("EURUSD", df)
    assert plan is not None
    assert plan["inside_date"] == good.index[-1]


def test_lookback_sessions_finds_older_inside_day():
    df = make_df([MOTHER, INSIDE, OUTSIDE])
    assert strategy.get_daily_plan("EURUSD", df, lookback_sessions=1) is None
    plan = strategy.get_daily_plan("EURUSD", df, lookback_sessions=2)
    assert plan is not None
    assert plan["inside_date"] == df.index[1]


def test_buffer_applied_to_levels(monkeypatch):
    monkeypatch.setattr(strategy, "BREAKOUT_BUFFER_PIPS", 5.0)
    df = make_df([MOTHER, MOTHER, INSIDE])
    plan = strategy.get_daily_plan("EURUSD", df)
    assert plan["breakout_up"] == round(1.05 + 5 * 0.0001, 5)
    assert plan["breakout_down"] == round(1.02 - 5 * 0.0001, 5)
    # JPY pairs use 0.01 pip size
    jpy = make_df([(100.0, 110.0, 95.0, 105.0)] * 2 + [(102.0, 105.0, 101.0, 104.0)])
    plan_jpy = strategy.get_daily_plan("USDJPY", jpy)
    assert plan_jpy["breakout_up"] == round(105.0 + 5 * 0.01, 5)


def test_pip_size():
    assert strategy.pip_size("USDJPY") == 0.01
    assert strategy.pip_size("EURUSD") == 0.0001
    assert strategy.pip_size("GBPJPY") == 0.01


def test_classify_candle():
    assert strategy.classify_candle({"Open": 1.0, "Close": 1.1}) == "green"
    assert strategy.classify_candle({"Open": 1.1, "Close": 1.0}) == "red"
    assert strategy.classify_candle({"Open": 1.0, "Close": 1.0}) == "neutral"

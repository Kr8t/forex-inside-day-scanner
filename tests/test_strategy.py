"""Unit tests for inside-day detection, blackout filtering, and plan generation."""

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
    inside = plan["inside_day"]
    assert inside is not None
    assert inside["color"] == "green"
    assert inside["breakout_up"] == 1.05
    assert inside["breakout_down"] == 1.02
    assert plan["blackout"] is None


def test_no_signal_returns_none():
    # Last bar neither inside nor closing outside the prior range.
    df = make_df([MOTHER, INSIDE, (1.03, 1.06, 1.03, 1.05)])
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
    assert plan["inside_day"]["inside_date"] == good.index[-1]


def test_lookback_sessions_finds_older_inside_day():
    df = make_df([MOTHER, INSIDE, (1.03, 1.06, 1.03, 1.05)])
    assert strategy.get_daily_plan("EURUSD", df, lookback_sessions=1) is None
    plan = strategy.get_daily_plan("EURUSD", df, lookback_sessions=2)
    assert plan is not None
    assert plan["inside_day"]["inside_date"] == df.index[1]


def test_buffer_applied_to_levels(monkeypatch):
    monkeypatch.setattr(strategy, "BREAKOUT_BUFFER_PIPS", 5.0)
    df = make_df([MOTHER, MOTHER, INSIDE])
    plan = strategy.get_daily_plan("EURUSD", df)
    assert plan["inside_day"]["breakout_up"] == round(1.05 + 5 * 0.0001, 5)
    assert plan["inside_day"]["breakout_down"] == round(1.02 - 5 * 0.0001, 5)
    # JPY pairs use 0.01 pip size
    jpy = make_df([(100.0, 110.0, 95.0, 105.0)] * 2 + [(102.0, 105.0, 101.0, 104.0)])
    plan_jpy = strategy.get_daily_plan("USDJPY", jpy)
    assert plan_jpy["inside_day"]["breakout_up"] == round(105.0 + 5 * 0.01, 5)


def test_pip_size():
    assert strategy.pip_size("USDJPY") == 0.01
    assert strategy.pip_size("EURUSD") == 0.0001
    assert strategy.pip_size("GBPJPY") == 0.01


def test_classify_candle():
    assert strategy.classify_candle({"Open": 1.0, "Close": 1.1}) == "green"
    assert strategy.classify_candle({"Open": 1.1, "Close": 1.0}) == "red"
    assert strategy.classify_candle({"Open": 1.0, "Close": 1.0}) == "neutral"


# ---------------------------------------------------------------------------
# Closed in Blackout filter
# ---------------------------------------------------------------------------

def test_blackout_direction_up_down_none():
    prev = {"High": 1.10, "Low": 1.00}
    assert strategy.blackout_direction({"Close": 1.11}, prev) == "up"
    assert strategy.blackout_direction({"Close": 0.99}, prev) == "down"
    assert strategy.blackout_direction({"Close": 1.10}, prev) is None  # at high, not beyond
    assert strategy.blackout_direction({"Close": 1.05}, prev) is None


def test_blackout_direction_respects_buffer():
    prev = {"High": 1.10, "Low": 1.00}
    candle = {"Close": 1.1030}
    # 30-pip breach: triggers with no buffer...
    assert strategy.blackout_direction(candle, prev, buffer_pips=0.0) == "up"
    # ...but not when a 50-pip clearance is required.
    assert strategy.blackout_direction(candle, prev, buffer_pips=50.0) is None


def test_plan_reports_closed_in_blackout_up():
    # Bars: mother, then latest closes above mother's high -> blackout up.
    df = make_df([MOTHER, MOTHER, (1.08, 1.12, 1.07, 1.11)])
    plan = strategy.get_daily_plan("EURUSD", df)
    assert plan is not None
    assert plan["inside_day"] is None
    bo = plan["blackout"]
    assert bo["direction"] == "up"
    assert bo["close"] == 1.11
    assert bo["prev_high"] == 1.10
    assert bo["date"] == df.index[-1]


def test_plan_reports_closed_in_blackout_down():
    df = make_df([MOTHER, MOTHER, (1.02, 1.03, 0.97, 0.98)])
    plan = strategy.get_daily_plan("EURUSD", df)
    assert plan is not None
    assert plan["blackout"]["direction"] == "down"
    assert plan["blackout"]["prev_low"] == 1.00


def test_blackout_filter_suppresses_stale_coil():
    # Older inside day, but the newest bar closed in blackout above it.
    df = make_df([MOTHER, INSIDE, (1.08, 1.12, 1.07, 1.11)])
    suppressed = strategy.get_daily_plan("EURUSD", df, lookback_sessions=2,
                                        apply_blackout_filter=True)
    assert suppressed["inside_day"] is None
    assert suppressed["blackout"]["direction"] == "up"
    # With the filter off, the coil is still reported alongside the blackout.
    both = strategy.get_daily_plan("EURUSD", df, lookback_sessions=2,
                                  apply_blackout_filter=False)
    assert both["inside_day"] is not None
    assert both["blackout"] is not None


def test_blackout_ignores_partial_today_bar():
    good = make_df([MOTHER, MOTHER, INSIDE])
    today = pd.Timestamp.today().normalize()
    partial = pd.DataFrame(
        {"Open": [1.05], "High": [1.20], "Low": [1.05], "Close": [1.19], "Volume": [0.0]},
        index=[today],
    )
    df = pd.concat([good, partial])
    plan = strategy.get_daily_plan("EURUSD", df)
    # The partial close above yesterday's high must NOT flag a blackout.
    assert plan["blackout"] is None
    assert plan["inside_day"] is not None

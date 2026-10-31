"""Unit tests for inside-day detection, CIB filtering, and plan generation."""

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
    assert plan["cib"] is None


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
# Closed in Breakout (CIB): close beyond previous day's High or Low
# ---------------------------------------------------------------------------

def test_cib_direction_up_down_none():
    prev = {"High": 1.10, "Low": 1.00}
    assert strategy.cib_direction({"Close": 1.11}, prev) == "up"     # above prev High
    assert strategy.cib_direction({"Close": 0.99}, prev) == "down"   # below prev Low
    assert strategy.cib_direction({"Close": 1.10}, prev) is None     # AT prev High: not beyond
    assert strategy.cib_direction({"Close": 1.00}, prev) is None     # AT prev Low: not beyond
    assert strategy.cib_direction({"Close": 1.05}, prev) is None     # inside range


def test_cib_direction_respects_buffer():
    prev = {"High": 1.10, "Low": 1.00}
    candle = {"Close": 1.1030}
    # 30-pip breach: triggers with no buffer...
    assert strategy.cib_direction(candle, prev, buffer_pips=0.0) == "up"
    # ...but not when a 50-pip clearance is required.
    assert strategy.cib_direction(candle, prev, buffer_pips=50.0) is None


def test_legacy_blackout_alias_still_works():
    prev = {"High": 1.10, "Low": 1.00}
    assert strategy.blackout_direction({"Close": 1.11}, prev) == "up"


def test_plan_reports_cib_up():
    # Latest daily bar CLOSES above the previous day's High -> CIB up.
    df = make_df([MOTHER, MOTHER, (1.08, 1.12, 1.07, 1.11)])
    plan = strategy.get_daily_plan("EURUSD", df)
    assert plan is not None
    assert plan["inside_day"] is None
    cib = plan["cib"]
    assert cib["direction"] == "up"
    assert cib["close"] == 1.11
    assert cib["prev_high"] == 1.10
    assert cib["date"] == df.index[-1]
    # Backward-compatible mirror key.
    assert plan["blackout"] is cib


def test_plan_reports_cib_down():
    # Latest daily bar CLOSES below the previous day's Low -> CIB down.
    df = make_df([MOTHER, MOTHER, (1.02, 1.03, 0.97, 0.98)])
    plan = strategy.get_daily_plan("EURUSD", df)
    assert plan is not None
    assert plan["cib"]["direction"] == "down"
    assert plan["cib"]["prev_low"] == 1.00


def test_wick_beyond_prev_range_but_close_inside_is_not_cib():
    """A high/low that pokes past yesterday but CLOSES back inside is NOT a CIB."""
    # Prev day: H 1.10 L 1.00. Today wicks to 1.13 but closes at 1.06.
    df = make_df([MOTHER, MOTHER, (1.04, 1.13, 1.00, 1.06)])
    plan = strategy.get_daily_plan("EURUSD", df)
    assert plan is None  # no inside day, no CIB (close finished inside)


def test_close_exactly_at_prev_high_is_not_cib():
    df = make_df([MOTHER, MOTHER, (1.04, 1.11, 1.03, 1.10)])  # closes AT prev high
    plan = strategy.get_daily_plan("EURUSD", df)
    assert plan is None


def test_cib_filter_suppresses_stale_coil():
    # Older inside day, but the newest bar closed in breakout above it.
    df = make_df([MOTHER, INSIDE, (1.08, 1.12, 1.07, 1.11)])
    suppressed = strategy.get_daily_plan("EURUSD", df, lookback_sessions=2,
                                         apply_cib_filter=True)
    assert suppressed["inside_day"] is None
    assert suppressed["cib"]["direction"] == "up"
    # With the filter off, the coil is still reported alongside the CIB.
    both = strategy.get_daily_plan("EURUSD", df, lookback_sessions=2,
                                   apply_cib_filter=False)
    assert both["inside_day"] is not None
    assert both["cib"] is not None
    # Legacy kwarg still honoured.
    legacy = strategy.get_daily_plan("EURUSD", df, lookback_sessions=2,
                                     apply_blackout_filter=True)
    assert legacy["inside_day"] is None


def test_cib_ignores_partial_today_bar():
    good = make_df([MOTHER, MOTHER, INSIDE])
    today = pd.Timestamp.today().normalize()
    partial = pd.DataFrame(
        {"Open": [1.05], "High": [1.20], "Low": [1.05], "Close": [1.19], "Volume": [0.0]},
        index=[today],
    )
    df = pd.concat([good, partial])
    plan = strategy.get_daily_plan("EURUSD", df)
    # The partial close above yesterday's high must NOT flag a CIB.
    assert plan["cib"] is None
    assert plan["inside_day"] is not None


def test_completed_bars_handles_time_of_day_timestamps():
    """Rows carrying a session time (not midnight) dated today are still dropped."""
    today = pd.Timestamp.today().normalize()
    idx = [today - pd.Timedelta(days=2), today - pd.Timedelta(days=1),
           today + pd.Timedelta(hours=14, minutes=30)]
    df = pd.DataFrame({"Open": [1.0]*3, "High": [1.1]*3, "Low": [0.9]*3,
                       "Close": [1.05]*3}, index=pd.DatetimeIndex(idx))
    bars = strategy.completed_bars(df)
    assert len(bars) == 2

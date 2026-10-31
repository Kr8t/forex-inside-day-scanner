"""Tests for CLI behaviour: watchlist validation and scan summaries."""

import pandas as pd
import pytest

from forex_scanner import cli
from tests.conftest import make_df

MOTHER = (1.05, 1.10, 1.00, 1.04)
INSIDE = (1.02, 1.05, 1.02, 1.05)


def test_normalize_pair():
    assert cli.normalize_pair(" eurusd ") == "EURUSD"


def test_create_watchlist_validates_unknown_pairs():
    with pytest.raises(ValueError) as exc:
        cli.create_watchlist("w", ["EURUSD", "FAKEPAIR"])
    msg = str(exc.value)
    assert "FAKEPAIR" in msg
    assert "EURUSD" in msg  # lists valid pairs as a hint


def test_create_watchlist_rejects_duplicates():
    with pytest.raises(ValueError):
        cli.create_watchlist("w", ["EURUSD", "eurusd"])


def test_create_watchlist_normalizes_and_saves():
    cli.create_watchlist("w", ["eurusd", "gbpjpy"])
    from forex_scanner.cache import load_watchlist
    assert load_watchlist("w") == ["EURUSD", "GBPJPY"]


def test_run_scan_reports_failures(monkeypatch, capsys):
    ok = make_df([MOTHER, MOTHER, INSIDE])
    data = {"EURUSD": ok, "GBPUSD": pd.DataFrame()}
    monkeypatch.setattr(cli, "fetch_all", lambda pairs, force=False: data)
    rc = cli.run_scan(["EURUSD", "GBPUSD"], force=False)
    out = capsys.readouterr().out
    assert rc == 0  # partial success
    assert "Scanned 1/2" in out
    assert "GBPUSD" in out  # failed pair named explicitly


def test_run_scan_total_failure_returns_exit_code_1(monkeypatch, capsys):
    data = {"EURUSD": pd.DataFrame(), "GBPUSD": pd.DataFrame()}
    monkeypatch.setattr(cli, "fetch_all", lambda pairs, force=False: data)
    rc = cli.run_scan(["EURUSD", "GBPUSD"], force=False)
    assert rc == 1
    out = capsys.readouterr().out.replace("\n", "")  # rich may soft-wrap lines
    assert "Fetch failed" in out


def test_main_no_args_prints_help(capsys):
    rc = cli.main([])
    assert rc == 0
    assert "usage" in capsys.readouterr().out.lower()


def test_main_wl_bad_pair_exit_code(capsys):
    rc = cli.main(["wl", "create", "x", "NOTAPAIR"])
    assert rc == 1
    assert "Unknown pairs" in capsys.readouterr().out


def test_main_wl_bare_subcommand_shows_help(capsys):
    rc = cli.main(["wl"])
    assert rc == 1
    assert "usage" in capsys.readouterr().out.lower()


# ---------------------------------------------------------------------------
# Split-grid output (Inside Day grid + Closed in Breakout (CIB) grid)
# ---------------------------------------------------------------------------

def _inside_plan():
    return {"pair": "EURUSD",
            "inside_day": {
                "inside_date": pd.Timestamp("2026-01-07"),
                "mother_date": pd.Timestamp("2026-01-06"),
                "color": "green",
                "breakout_up": 1.05000, "breakout_down": 1.02000,
                "range": 0.03},
            "cib": None}


def _cib_plan(direction="up", color="green"):
    cib = {"direction": direction,
           "date": pd.Timestamp("2026-01-08"),
           "previous_date": pd.Timestamp("2026-01-07"),
           "color": color, "close": 1.11, "prev_high": 1.10, "prev_low": 1.00,
           "high": 1.12, "low": 1.05, "range": 0.07}
    return {"pair": "GBPJPY" if direction == "up" else "AUDUSD",
            "inside_day": None, "cib": cib, "blackout": cib}


def test_signal_tables_splits_into_two_grids():
    inside, cib = cli._signal_tables([_inside_plan(), _cib_plan()])
    assert [p for p, _ in inside] == ["EURUSD"]
    assert [p for p, _ in cib] == ["GBPJPY"]


def test_print_daily_plan_renders_both_grids(capsys):
    cli.print_daily_plan([_inside_plan(), _cib_plan(), _cib_plan("down", "red")])
    out = capsys.readouterr().out
    assert "INSIDE DAY" in out
    assert "CLOSED IN BREAKOUT (CIB)" in out
    assert "EURUSD" in out and "GBPJPY" in out and "AUDUSD" in out


def test_cib_grid_has_no_signal_column_or_stop_labels(capsys):
    cli.print_daily_plan([_inside_plan(), _cib_plan()])
    out = capsys.readouterr().out
    assert "Signal" not in out
    assert "Buy Stop" not in out
    assert "Sell Stop" not in out


def test_cib_direction_colours_follow_candle_colour():
    # Colour always matches the candle column: green close => green text.
    assert cli._cib_style("green", "up") == "green"
    assert cli._cib_style("red", "down") == "red"
    assert cli._cib_style("red", "up") == "red"     # direction never flips colour
    assert cli._cib_style("neutral", "up") == "yellow"


def test_print_daily_plan_empty_message(capsys):
    cli.print_daily_plan([])
    out = capsys.readouterr().out
    assert "No Inside-Day or Closed-in-Breakout (CIB) setups" in out


def test_cib_grid_shows_direction_words_not_prices(capsys):
    from io import StringIO

    from rich.console import Console
    _, cib = cli._signal_tables([_cib_plan("up"), _cib_plan("down", "red")])
    buf = StringIO()
    target = Console(file=buf, width=140)
    target.print(cli._build_cib_table(cib))
    out = buf.getvalue().replace("\n", "")
    assert "Above Prev High" in out
    assert "Below Prev Low" in out
    # Removed per user request: no Breach column, and Prev High/Low are no
    # longer standalone columns (they only appear inside the Direction text).
    assert "Breach" not in out


def test_headings_have_no_icons(capsys):
    cli.print_daily_plan([_inside_plan(), _cib_plan()])
    out = capsys.readouterr().out
    for glyph in ("🟢", "🔴", "🟩", "🟥"):
        assert glyph not in out


def test_scan_flag_names_are_cib():
    ap, _ = cli.build_parser()
    args = ap.parse_args(["scan", "--no-cib-filter"])
    assert args.cib_filter is False
    args = ap.parse_args(["scan", "--cib-filter"])
    assert args.cib_filter is True
    args = ap.parse_args(["scan"])
    assert args.cib_filter is None

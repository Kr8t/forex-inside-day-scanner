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
    assert "Fetch failed" in capsys.readouterr().out


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

"""Tests for the SQLite cache layer."""

from datetime import date, datetime, timedelta

import pandas as pd

from forex_scanner import cache
from tests.conftest import make_df

MOTHER = (1.05, 1.10, 1.00, 1.04)


def _df_until(d: date):
    n = 5
    idx = pd.bdate_range(end=d.strftime("%Y-%m-%d"), periods=n)
    df = pd.DataFrame(
        [MOTHER] * n, columns=["Open", "High", "Low", "Close"], index=idx
    )
    df["Volume"] = 0.0
    return df


def test_save_and_load_roundtrip(tmp_db):
    df = make_df([MOTHER] * 4)
    cache.save_ohlcv("EURUSD", df, tmp_db)
    loaded = cache.load_ohlcv("EURUSD", tmp_db)
    assert len(loaded) == 4
    assert loaded["High"].iloc[0] == 1.10


def test_upsert_is_idempotent(tmp_db):
    df = make_df([MOTHER] * 4)
    cache.save_ohlcv("EURUSD", df, tmp_db)
    cache.save_ohlcv("EURUSD", df, tmp_db)
    assert len(cache.load_ohlcv("EURUSD", tmp_db)) == 4


def test_fresh_only_when_recent_and_complete(tmp_db, monkeypatch):
    last_td = cache._last_trading_day()
    cache.save_ohlcv("EURUSD", _df_until(last_td), tmp_db)
    monkeypatch.setattr(cache, "DB_PATH", tmp_db)
    assert cache.is_cache_fresh("EURUSD") is True


def test_stale_when_missing_last_trading_day(tmp_db, monkeypatch):
    old = cache._last_trading_day() - timedelta(days=3)
    cache.save_ohlcv("EURUSD", _df_until(old), tmp_db)
    monkeypatch.setattr(cache, "DB_PATH", tmp_db)
    assert cache.is_cache_fresh("EURUSD") is False


def test_stale_when_ttl_expired(tmp_db, monkeypatch):
    last_td = cache._last_trading_day()
    cache.save_ohlcv("EURUSD", _df_until(last_td), tmp_db)
    # Age the fetched_at timestamp beyond the TTL.
    with cache.get_conn(tmp_db) as conn:
        conn.execute(
            "UPDATE cache_meta SET fetched_at=? WHERE pair='EURUSD'",
            (datetime.now().timestamp() - cache.CACHE_TTL_SECONDS - 1,),
        )
    monkeypatch.setattr(cache, "DB_PATH", tmp_db)
    assert cache.is_cache_fresh("EURUSD") is False


def test_unknown_pair_not_fresh(tmp_db):
    assert cache.is_cache_fresh("NOPEUSD") is False


def test_last_trading_day_skips_weekend():
    # Monday -> previous Friday
    assert cache._last_trading_day(date(2026, 10, 26)).weekday() == 4
    # Saturday -> Friday
    assert cache._last_trading_day(date(2026, 10, 31)) == date(2026, 10, 30)


def test_watchlist_crud(tmp_db):
    cache.save_watchlist("mine", ["EURUSD", "GBPUSD"], tmp_db)
    assert cache.list_watchlists(tmp_db) == ["mine"]
    assert cache.load_watchlist("mine", tmp_db) == ["EURUSD", "GBPUSD"]
    cache.delete_watchlist("mine", tmp_db)
    assert cache.load_watchlist("mine", tmp_db) == []
    assert cache.list_watchlists(tmp_db) == []


def test_legacy_intraday_dates_are_normalised(tmp_db):
    """Old cache rows stamped 'YYYY-MM-DD HH:MM:SS' must load as midnight."""
    import sqlite3
    from contextlib import closing

    with closing(sqlite3.connect(tmp_db)) as conn, conn:
        conn.execute(
            "INSERT INTO ohlcv VALUES ('EURUSD','2026-10-29 14:30:00',"
            "1.11,1.12,1.10,1.115,0)"
        )
    cache.init_db(tmp_db)  # triggers the migration
    df = cache.load_ohlcv("EURUSD", tmp_db)
    assert df.index[-1] == pd.Timestamp("2026-10-29")


def test_save_ohlcv_strips_time_component(tmp_db):
    idx = pd.to_datetime(["2026-10-27 09:30", "2026-10-28 09:30"])
    df = pd.DataFrame(
        {"Open": [1.0, 1.1], "High": [1.2, 1.3], "Low": [0.9, 1.0],
         "Close": [1.1, 1.2], "Volume": [0.0, 0.0]}, index=idx)
    cache.save_ohlcv("GBPUSD", df, tmp_db)
    loaded = cache.load_ohlcv("GBPUSD", tmp_db)
    assert list(loaded.index) == [pd.Timestamp("2026-10-27"),
                                  pd.Timestamp("2026-10-28")]

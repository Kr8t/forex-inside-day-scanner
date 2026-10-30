"""Shared test fixtures: synthetic OHLCV frames and a temp database."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forex_scanner import cache, config  # noqa: E402


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    """Point all cache/config DB access at a per-test temporary file."""
    db = tmp_path / "test.db"
    monkeypatch.setattr(config, "DB_PATH", db)
    monkeypatch.setattr(cache, "DB_PATH", db)
    cache.init_db(db)
    return db


def make_df(rows, start="2026-01-05"):
    """Build an OHLCV frame from (open, high, low, close) tuples.

    Dates are consecutive weekdays starting at ``start`` so no bar is ever
    dated 'today' and therefore treated as a partial session.
    """
    idx = pd.bdate_range(start=start, periods=len(rows))
    data = pd.DataFrame(
        rows, columns=["Open", "High", "Low", "Close"], index=idx
    )
    data["Volume"] = 0.0
    return data

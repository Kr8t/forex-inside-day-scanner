"""Data fetching layer (yfinance) with batching, retries, and caching."""

import logging
import time

import pandas as pd
import yfinance as yf

from .cache import init_db, is_cache_fresh, load_ohlcv, save_ohlcv
from .config import LOOKBACK_DAYS

log = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2.0


def to_ticker(pair: str) -> str:
    return f"{pair}=X"


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise an OHLCV frame: plain OHLC(V) columns, naive date index, no NaNs."""
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        # Newer yfinance returns (Price, Ticker) levels; keep the price field.
        flat = []
        for tup in df.columns.tolist():
            flat.append(next((v for v in reversed(tup)
                              if v in {"Open", "High", "Low", "Close", "Volume", "Adj Close"}),
                             tup[-1]))
        df.columns = pd.Index(flat)
        if df.columns.duplicated().any():
            df = df.loc[:, ~df.columns.duplicated()]
    if "Volume" not in df.columns:
        df["Volume"] = 0.0
    df = df[["Open", "High", "Low", "Close", "Volume"]]
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_localize(None)
    # Daily bars must be stamped at midnight. Yahoo intraday feeds sometimes
    # return timestamps with a session time component; normalising keeps the
    # "is this today's partial bar?" guard in strategy.completed_bars working.
    try:
        df.index = df.index.normalize()
    except (AttributeError, TypeError, ValueError):
        pass
    df = df[~df.index.duplicated(keep="last")]
    return df.dropna(subset=["Open", "High", "Low", "Close"]).sort_index()


def _download_with_retry(tickers: list, period: str) -> pd.DataFrame:
    """Batch-download daily bars, retrying with linear backoff on transient errors."""
    last_err: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            raw = yf.download(
                tickers, period=period, interval="1d",
                group_by="ticker", auto_adjust=True,
                threads=True, progress=False,
            )
            if raw is not None and not raw.empty:
                return raw
            last_err = RuntimeError("empty response")
        except Exception as e:  # noqa: BLE001 - network layer, must be broad
            last_err = e
        if attempt < MAX_RETRIES:
            sleep = RETRY_BACKOFF_SECONDS * attempt
            log.warning("Batch download failed (attempt %d/%d): %s; retrying in %.1fs",
                        attempt, MAX_RETRIES, last_err, sleep)
            time.sleep(sleep)
    raise RuntimeError(f"Download failed after {MAX_RETRIES} attempts: {last_err}")


def _slice_pair(raw: pd.DataFrame, pair: str) -> pd.DataFrame:
    """Extract one pair's columns from a multi-ticker batch frame."""
    if isinstance(raw.columns, pd.MultiIndex):
        if pair not in set(raw.columns.get_level_values(0)):
            return pd.DataFrame()
        sub = raw.loc[:, raw.columns.get_level_values(0) == pair]
    else:
        # Single ticker was requested; the frame has plain OHLC columns.
        sub = raw
    if sub.empty:
        return pd.DataFrame()
    try:
        return _clean(sub)
    except KeyError:
        return pd.DataFrame()


def fetch_all(pairs: list, force: bool = False) -> dict:
    """Fetch daily bars for all pairs, using the cache where fresh.

    Returns {pair: DataFrame}. Pairs whose fetch failed map to an empty
    DataFrame so callers can distinguish 'no setup' from 'no data'.
    """
    init_db()
    out: dict = {}
    stale: list = []

    for p in pairs:
        if not force and is_cache_fresh(p):
            df = load_ohlcv(p)
            if not df.empty:
                out[p] = df
                continue
        stale.append(p)

    if not stale:
        return {p: out[p] for p in pairs}

    raw = pd.DataFrame()
    try:
        raw = _download_with_retry([to_ticker(p) for p in stale],
                                   period=f"{LOOKBACK_DAYS}d")
    except Exception as e:  # noqa: BLE001
        log.error("Batch download failed entirely (%s); falling back to per-pair fetch.", e)

    for p in stale:
        df = _slice_pair(raw, p) if not raw.empty else pd.DataFrame()
        if df.empty:
            # Fallback: individual fetch (covers gaps in the batch result).
            try:
                single = yf.download(to_ticker(p), period=f"{LOOKBACK_DAYS}d",
                                     interval="1d", auto_adjust=True, progress=False)
                if single is not None and not single.empty:
                    df = _clean(single)
            except Exception as e:  # noqa: BLE001
                log.warning("%s: fetch failed: %s", p, e)
                df = pd.DataFrame()
        if not df.empty:
            save_ohlcv(p, df)
        out[p] = df

    return {p: out.get(p, pd.DataFrame()) for p in pairs}

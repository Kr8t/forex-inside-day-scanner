# Forex Scanner — Inside Day & Closed in Breakout (CIB)

Scans major FX pairs for two daily signals and prints each as its own
colour-coded grid:

| Grid | Meaning |
| --- | --- |
| 🟩🟥 **INSIDE DAY** | A session whose range sits fully inside the previous day's. Rows are coloured by candle direction (green close = green, red close = red) and show the breakout levels (`Breakout ↑ / ↓`). |
| 🟢🔴 **CLOSED IN BREAKOUT (CIB)** | A daily session whose **closing price ends above the previous day's High or below its Low**. Close *above* prev High → **green** row (↑); close *below* prev Low → **red** row (↓). Wicks beyond but a close back inside do **not** count. |

## Install & run

```bash
pip install -r requirements.txt
python forex_scanner.py scan --set all           # every supported pair
python forex_scanner.py scan --set majors        # only the 7 majors
python forex_scanner.py scan --watchlist mylist  # saved watchlist
python forex_scanner.py scan --force             # bypass the local cache
```

Or install as a package and use the `forex-scanner` entry point:

```bash
pip install .
forex-scanner scan --set all
```

### What is a Closed in Breakout (CIB)?

A pair is flagged **CIB** when its **closing price at the end of the day**
finishes **above the previous day's High** or **below the previous day's Low**.
It is the *close* that matters — a wick that pokes beyond yesterday but snaps
back to close inside the prior range is **not** a CIB, and a close exactly AT
the previous High/Low does not count either (it must finish beyond).

The scanner shows CIB rows in their own grid: green ↑ when the close finished
above the prior day's High, red ↓ when below the prior day's Low.

### CIB filter flags

The scanner always *reports* CIB sessions on the latest completed day. When
the filter is enabled it also *suppresses* older inside-day setups once the
newest day has already resolved out of the prior range (the coil is stale):

```bash
python forex_scanner.py scan --cib-filter       # force filter ON
python forex_scanner.py scan --no-cib-filter    # force filter OFF
```

If neither flag is given, the default comes from `FOREX_CIB_ENABLED`
(`FOREX_BLACKOUT_ENABLED` still works as a legacy fallback).

## Configuration (environment variables)

| Variable | Default | Meaning |
| --- | --- | --- |
| `FOREX_DB` | `~/.forex-scanner/forex.db` | SQLite cache location |
| `FOREX_BREAKOUT_BUFFER_PIPS` | `0.0` | Pips beyond the inside-day high/low where stops sit |
| `FOREX_PLAN_LOOKBACK` | `1` | Completed sessions scanned for an inside day |
| `FOREX_CIB_ENABLED` | `1` | Apply the CIB filter by default (`0` disables); legacy alias `FOREX_BLACKOUT_ENABLED` |
| `FOREX_CIB_BUFFER_PIPS` | `0.0` | Extra pips the close must clear the previous day's High/Low by before the CIB flag triggers; legacy alias `FOREX_BLACKOUT_BUFFER_PIPS` |

Example: require a 10-pip clearance beyond the previous day's High/Low before
a close counts as CIB, and keep older coils visible:

```bash
FOREX_CIB_BUFFER_PIPS=10 FOREX_CIB_ENABLED=0 \
    python forex_scanner.py scan --set all
```

## Watchlists

```bash
python forex_scanner.py wl create mylist eurusd gbpjpy   # case-insensitive
python forex_scanner.py wl list
python forex_scanner.py wl show mylist
python forex_scanner.py wl rm mylist
```

## Windows

Double-click `RunScanner.bat` (checks that Python is installed and reports
the scanner's exit code).

## Development

Requires Python 3.10+.

```bash
pip install -r requirements.txt
pip install pytest ruff
pytest                 # unit tests
ruff check forex_scanner tests
```

CI runs lint + tests on every push via GitHub Actions
(`.github/workflows/ci.yml`).

## Disclaimer

This tool provides technical analysis for educational purposes only. It is
not financial advice. Trading foreign exchange carries significant risk.
\Forex Inside-Day Scanner  
Scans major FX pairs for daily inside-day compressions.  
\Run python forex_scanner.py scan --set all  
\Windows Double-click RunScanner.bat  

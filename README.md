# Forex Scanner — Inside Day & Closed in Breakout (CIB)

Scans major FX pairs for two daily signals and prints each as its own
colour-coded grid:

| Grid | Meaning |
| --- | --- |
| 🟩🟥 **INSIDE DAY** | A session whose range sits fully inside the previous day's. Rows are coloured by candle direction (green close = green, red close = red) and show the breakout levels (`Breakout ↑ / ↓`). |
| ⚫ **CLOSED IN BREAKOUT (CIB)** | A session that **closes outside the previous day's high-low range**. Closing *above* the prior high → **green** row (↑); closing *below* the prior low → **red** row (↓). |

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

### CIB filter flags

The scanner always *reports* closed-in-breakout bars on the latest completed
session. When the filter is enabled it also *suppresses* older inside-day
setups once the newest bar has already resolved out of the prior range (the
coil is stale):

```bash
python forex_scanner.py scan --blackout-filter      # force filter ON
python forex_scanner.py scan --no-blackout-filter   # force filter OFF
```

If neither flag is given, the default comes from `FOREX_BLACKOUT_ENABLED`.

## Configuration (environment variables)

| Variable | Default | Meaning |
| --- | --- | --- |
| `FOREX_DB` | `~/.forex-scanner/forex.db` | SQLite cache location |
| `FOREX_BREAKOUT_BUFFER_PIPS` | `0.0` | Pips beyond the inside-day high/low where stops sit |
| `FOREX_PLAN_LOOKBACK` | `1` | Completed sessions scanned for an inside day |
| `FOREX_BLACKOUT_ENABLED` | `1` | Apply the CIB filter by default (`0` disables) |
| `FOREX_BLACKOUT_BUFFER_PIPS` | `0.0` | Extra pips the close must clear the prior range by before the CIB flag triggers |

Example: require a 10-pip clearance beyond the previous day's range before a
close counts as CIB, and keep older coils visible:

```bash
FOREX_BLACKOUT_BUFFER_PIPS=10 FOREX_BLACKOUT_ENABLED=0 \
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

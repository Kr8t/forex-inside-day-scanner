# Forex Inside-Day & Blackout Scanner

Scans major FX pairs for two daily signals:

* **Inside Day** — a session whose range is contained within the previous
  day's, used to build breakout stop-order levels.
* **Closed in Blackout** — a session that *closes* outside the previous
  day's high-low range (above its high or below its low).

## Run

```bash
python forex_scanner.py scan --set all           # scan every supported pair
python forex_scanner.py scan --set majors        # only the 7 majors
python forex_scanner.py scan --watchlist mylist  # saved watchlist
python forex_scanner.py scan --force             # bypass the local cache
```

### Blackout filter flags

The scanner always *reports* closed-in-blackout bars on the latest completed
session. In addition, when the filter is enabled it also *suppresses* any
older inside-day setup once the newest bar has already resolved out of the
prior range (the coil is stale):

```bash
python forex_scanner.py scan --blackout-filter      # force filter ON
python forex_scanner.py scan --no-blackout-filter   # force filter OFF
```

If neither flag is given, the default comes from `FOREX_BLACKOUT_ENABLED`
(see below).

## Configuration (environment variables)

| Variable | Default | Meaning |
| --- | --- | --- |
| `FOREX_DB` | `~/.forex-scanner/forex.db` | SQLite cache location |
| `FOREX_BREAKOUT_BUFFER_PIPS` | `0.0` | Pips beyond the inside-day high/low where stops sit |
| `FOREX_PLAN_LOOKBACK` | `1` | Completed sessions scanned for an inside day |
| `FOREX_BLACKOUT_ENABLED` | `1` | Apply the blackout filter by default (`0` disables) |
| `FOREX_BLACKOUT_BUFFER_PIPS` | `0.0` | Extra pips the close must clear the prior range by before the flag triggers |

Example: require a 10-pip clearance beyond the previous day's range before
a close counts as a blackout, and keep older coils visible:

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

Double-click `RunScanner.bat`.

## Development

```bash
pip install -r requirements.txt
pytest                 # unit tests
ruff check forex_scanner tests
```

## Disclaimer

This tool provides technical analysis for educational purposes only. It is
not financial advice. Trading foreign exchange carries significant risk.

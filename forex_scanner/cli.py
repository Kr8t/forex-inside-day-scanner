"""Command-line interface for the Forex Inside-Day Scanner."""

import argparse
import logging
import sys

from rich import box
from rich.console import Console
from rich.table import Table

from .cache import delete_watchlist, init_db, list_watchlists, load_watchlist
from .config import ALL_PAIRS, MAJOR_PAIRS, YEN_EUR_CROSSES
from .data import fetch_all
from .strategy import get_daily_plan, pip_size

console = Console()
COLOR_MAP = {"green": "green", "red": "red", "neutral": "yellow"}


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )


# ---------------------------------------------------------------------------
# Watchlist helpers
# ---------------------------------------------------------------------------

def normalize_pair(pair: str) -> str:
    return pair.strip().upper()


def create_watchlist(name: str, pairs: list) -> None:
    """Validate and save a watchlist. Raises ValueError listing valid pairs."""
    pairs = [normalize_pair(p) for p in pairs]
    unknown = sorted({p for p in pairs if p not in ALL_PAIRS})
    if unknown:
        raise ValueError(
            f"Unknown pairs: {', '.join(unknown)}.\n"
            f"Valid pairs: {', '.join(ALL_PAIRS)}"
        )
    dupes = sorted({p for p in pairs if pairs.count(p) > 1})
    if dupes:
        raise ValueError(f"Duplicate pairs: {', '.join(dupes)}")
    from .cache import save_watchlist
    save_watchlist(name, pairs)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _cib_style(color: str, direction: str) -> str:
    """Colour a CIB row by the candle's own colour (matches the Candle column):
    green close => green text, red close => red text; direction only picks the
    arrow glyph, never the colour."""
    return COLOR_MAP.get(color, "")


def _signal_tables(plans: list) -> tuple[list, list]:
    """Split flat plans into (inside-day rows, closed-in-blackout rows)."""
    inside_rows, cib_rows = [], []
    for p in plans:
        if p.get("inside_day"):
            inside_rows.append((p["pair"], p["inside_day"]))
        if p.get("cib") or p.get("blackout"):
            cib_rows.append((p["pair"], p.get("cib") or p["blackout"]))
    return inside_rows, cib_rows


def _render_tables(target: Console, inside_rows: list, cib_rows: list) -> None:
    """Print the inside-day and CIB grids onto ``target``."""
    if inside_rows:
        t = _build_inside_table(inside_rows)
        target.print(t)
        target.print()
    if cib_rows:
        t = _build_cib_table(cib_rows)
        target.print(t)
        target.print()


def _build_inside_table(rows: list) -> Table:
    table = Table(title="INSIDE DAY - BREAKOUT LEVELS", box=box.DOUBLE_EDGE)
    table.add_column("Pair", style="cyan")
    table.add_column("Date")
    table.add_column("Candle")
    table.add_column("Breakout ↑", style="green")
    table.add_column("Breakout ↓", style="red")
    table.add_column("Range (Pips)")

    for pair, inside in rows:
        pips = round(inside["range"] / pip_size(pair), 1)
        table.add_row(
            pair,
            inside["inside_date"].strftime("%Y-%m-%d"),
            inside["color"],
            f"{inside['breakout_up']:.5f}",
            f"{inside['breakout_down']:.5f}",
            f"{pips} pips",
            style=COLOR_MAP[inside["color"]],
        )
    return table


def _build_cib_table(rows: list) -> Table:
    table = Table(title="CLOSED IN BREAKOUT (CIB)", box=box.DOUBLE_EDGE)
    table.add_column("Pair", style="cyan")
    table.add_column("Date")
    table.add_column("Candle")
    table.add_column("Close")
    table.add_column("Direction")

    for pair, bo in rows:
        arrow = "Above Prev High" if bo["direction"] == "up" else "Below Prev Low"
        table.add_row(
            pair,
            bo["date"].strftime("%Y-%m-%d"),
            bo["color"],
            f"{bo['close']:.5f}",
            arrow,
            style=_cib_style(bo["color"], bo["direction"]),
        )
    return table


def print_daily_plan(plans: list) -> None:
    """Render the two signals as separate, colour-coded grids.

    Falls back to a wide fixed-width console on narrow terminals so tables
    are never silently dropped or crash the scan.
    """
    inside_rows, cib_rows = _signal_tables(plans)
    if not inside_rows and not cib_rows:
        console.print("[bold yellow]No Inside-Day or Closed-in-Breakout (CIB) setups "
                      "found for today's plan.[/bold yellow]\n")
        return

    try:
        _render_tables(console, inside_rows, cib_rows)
    except Exception:  # noqa: BLE001 - rendering fallback must be broad
        # Rich raises when columns don't fit narrow/piped terminals; retry
        # once on a guaranteed-wide console.
        try:
            _render_tables(Console(width=110), inside_rows, cib_rows)
        except Exception:  # pragma: no cover - extreme environments only  # noqa: BLE001
            console.print("[red]Unable to render tables in this terminal; "
                          "run with a wider window.[/red]")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def run_scan(pairs: list, force: bool, cib_filter: bool | None = None) -> int:
    """Scan pairs; returns an exit code (0 ok, 1 total fetch failure).

    ``cib_filter`` overrides the configured default for the
    Closed-in-Breakout (CIB) filter when not None.
    """
    kwargs = {} if cib_filter is None else {"apply_cib_filter": cib_filter}
    data = fetch_all(pairs, force=force)
    daily_plans = []
    failed = []

    for p in pairs:
        df = data.get(p)
        if df is None or df.empty:
            failed.append(p)
            continue
        plan = get_daily_plan(p, df, **kwargs)
        if plan:
            # Audit trail: show the exact bars each signal was computed from
            # so a questionable flag can be checked against your chart.
            bo = plan.get("cib") or plan.get("blackout")
            if bo:
                arrow = "↑" if bo["direction"] == "up" else "↓"
                console.print(
                    f"[dim]{p}: CIB {arrow} on {bo['date']:%Y-%m-%d} — "
                    f"close {bo['close']:.5f} vs prev day "
                    f"({bo['previous_date']:%Y-%m-%d}) "
                    f"H {bo['prev_high']:.5f} / L {bo['prev_low']:.5f}[/dim]"
                )
            if plan.get("inside_day"):
                idy = plan["inside_day"]
                console.print(
                    f"[dim]{p}: inside day {idy['inside_date']:%Y-%m-%d} "
                    f"in mother {idy['mother_date']:%Y-%m-%d}[/dim]"
                )
            daily_plans.append(plan)

    print_daily_plan(daily_plans)

    scanned = len(pairs) - len(failed)
    n_inside = sum(1 for p in daily_plans if p.get("inside_day"))
    n_cib = sum(1 for p in daily_plans if p.get("cib"))
    summary = (f"Scanned {scanned}/{len(pairs)} pairs — "
               f"{n_inside} inside-day setup(s), {n_cib} CIB (closed beyond prev day High/Low).")
    if failed:
        summary += f" Fetch failed for: {', '.join(failed)}"
        console.print(f"[bold red]{summary}[/bold red]")
    else:
        console.print(f"[dim]{summary}[/dim]")

    return 1 if failed and scanned == 0 else 0


def cmd_scan(args) -> int:
    if args.watchlist:
        pairs = load_watchlist(args.watchlist)
        if not pairs:
            names = list_watchlists()
            hint = (f"Existing watchlists: {', '.join(names)}" if names
                    else "No watchlists exist yet.")
            console.print(f"[red]Watchlist '{args.watchlist}' is empty or missing. {hint}[/red]")
            return 1
    else:
        pairs = {
            "majors": MAJOR_PAIRS,
            "crosses": YEN_EUR_CROSSES,
            "all": ALL_PAIRS,
        }[args.set]
    return run_scan(pairs, force=args.force, cib_filter=args.cib_filter)


def cmd_wl(args, wl_parser: argparse.ArgumentParser) -> int:
    if not args.wlcmd:
        wl_parser.print_help()
        return 1
    if args.wlcmd == "list":
        names = list_watchlists()
        if not names:
            console.print("[dim]No watchlists. Create one with: wl create <name> <PAIR1> ...[/dim]")
        for n in names:
            console.print(f"  • [cyan]{n}[/cyan]: {load_watchlist(n)}")
    elif args.wlcmd == "create":
        try:
            create_watchlist(args.name, args.pairs)
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            return 1
        console.print(f"Created watchlist '{args.name}' with {args.pairs}")
    elif args.wlcmd == "rm":
        if args.name not in list_watchlists():
            console.print(f"[red]Watchlist '{args.name}' not found.[/red]")
            return 1
        delete_watchlist(args.name)
        console.print(f"Removed '{args.name}'")
    elif args.wlcmd == "show":
        pairs = load_watchlist(args.name)
        if not pairs:
            console.print(f"[red]Watchlist '{args.name}' is empty or missing.[/red]")
            return 1
        console.print(pairs)
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_parser():
    ap = argparse.ArgumentParser(
        prog="forex_scanner",
        description="Forex scanner — detects daily inside-day compressions and "
                    "closed-in-breakout (CIB) sessions across major FX pairs.",
        epilog="Disclaimer: educational analysis tool only — not financial advice.",
    )
    ap.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = ap.add_subparsers(dest="cmd")

    p_scan = sub.add_parser("scan", help="Scan pairs for inside days & closed-in-breakout sessions")
    p_scan.add_argument("--set", choices=["majors", "crosses", "all"], default="all")
    p_scan.add_argument("--watchlist", help="Use a saved watchlist")
    p_scan.add_argument("--force", action="store_true", help="Bypass cache")
    p_scan.add_argument("--no-cib-filter", dest="cib_filter",
                        action="store_false", default=None,
                        help="Keep inside-day setups even after a "
                             "Closed-in-Breakout (CIB) day")
    p_scan.add_argument("--cib-filter", dest="cib_filter",
                        action="store_true",
                        help="Suppress inside-day setups once the latest daily "
                             "bar closes beyond the previous day's High/Low")

    p_wl = sub.add_parser("wl", help="Manage watchlists")
    wlsub = p_wl.add_subparsers(dest="wlcmd")
    wlsub.add_parser("list", help="List all watchlists")
    w_create = wlsub.add_parser("create", help="Create a watchlist")
    w_create.add_argument("name")
    w_create.add_argument("pairs", nargs="+", metavar="PAIR")
    w_rm = wlsub.add_parser("rm", help="Delete a watchlist")
    w_rm.add_argument("name")
    w_show = wlsub.add_parser("show", help="Show a watchlist")
    w_show.add_argument("name")

    return ap, p_wl


def main(argv: list | None = None) -> int:
    ap, p_wl = build_parser()
    args = ap.parse_args(argv)
    setup_logging(args.verbose)
    init_db()

    if args.cmd == "scan":
        rc = cmd_scan(args)
    elif args.cmd == "wl":
        rc = cmd_wl(args, p_wl)
    else:
        ap.print_help()
        rc = 0

    console.print("\n[dim]Note: this tool provides technical analysis only, "
                  "not financial advice.[/dim]")
    return rc


if __name__ == "__main__":
    sys.exit(main())

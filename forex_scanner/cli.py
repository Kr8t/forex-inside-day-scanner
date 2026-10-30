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
COLOR_MAP = {"green": "bold green", "red": "bold red", "neutral": "yellow"}


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

def print_daily_plan(plans: list) -> None:
    if not plans:
        console.print("[bold yellow]No Inside-Day setups found for today's plan.[/bold yellow]\n")
        return

    table = Table(title="🎯 TODAY'S PLAN (Based on Previous Day's Inside Day)",
                  box=box.DOUBLE_EDGE)
    table.add_column("Pair", style="cyan")
    table.add_column("ID Date")
    table.add_column("Color")
    table.add_column("Buy Stop (Break ↑)", style="green")
    table.add_column("Sell Stop (Break ↓)", style="red")
    table.add_column("Range (Pips)")

    for p in plans:
        pips = round(p["range"] / pip_size(p["pair"]), 1)
        table.add_row(
            p["pair"],
            p["inside_date"].strftime("%Y-%m-%d"),
            p["color"],
            f"{p['breakout_up']:.5f}",
            f"{p['breakout_down']:.5f}",
            f"{pips} pips",
            style=COLOR_MAP[p["color"]],
        )
    console.print(table)
    console.print()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def run_scan(pairs: list, force: bool) -> int:
    """Scan pairs; returns an exit code (0 ok, 1 total fetch failure)."""
    data = fetch_all(pairs, force=force)
    daily_plans = []
    failed = []

    for p in pairs:
        df = data.get(p)
        if df is None or df.empty:
            failed.append(p)
            continue
        plan = get_daily_plan(p, df)
        if plan:
            daily_plans.append(plan)

    print_daily_plan(daily_plans)

    scanned = len(pairs) - len(failed)
    summary = f"Scanned {scanned}/{len(pairs)} pairs, {len(daily_plans)} setup(s) found."
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
    return run_scan(pairs, force=args.force)


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
        description="Forex Inside-Day Scanner — scans major FX pairs for "
                    "daily inside-day compressions and builds a breakout plan.",
        epilog="Disclaimer: educational analysis tool only — not financial advice.",
    )
    ap.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = ap.add_subparsers(dest="cmd")

    p_scan = sub.add_parser("scan", help="Scan pairs for inside days & breakouts")
    p_scan.add_argument("--set", choices=["majors", "crosses", "all"], default="all")
    p_scan.add_argument("--watchlist", help="Use a saved watchlist")
    p_scan.add_argument("--force", action="store_true", help="Bypass cache")

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

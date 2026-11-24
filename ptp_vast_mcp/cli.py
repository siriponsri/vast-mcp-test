"""Independent human terminal. No flag can bypass human confirmation."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

from .api import VastAPI, VastError, get_key
from . import lifecycle as life
from .planner import Limits, digest, discover


def emit(value):
    print(json.dumps(value, indent=2, ensure_ascii=True))


def confirm(expected: str):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise VastError("This paid or destructive action requires an independent human terminal.")
    print(f"To authorize exactly this action, enter {expected}:")
    if input("> ").strip() != expected:
        raise VastError("Confirmation did not match; no mutation sent.")


def state_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / ".local" / "state"))
    return base / "ptp-vast-mcp" / "leases.sqlite3"


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ptp-vast")
    sub = p.add_subparsers(dest="cmd", required=True)
    for cmd in ("search", "rent"):
        sp = sub.add_parser(cmd)
        sp.add_argument("--vram-mb", type=int, default=16000)
        sp.add_argument("--disk-gb", type=int, default=24)
        sp.add_argument("--minutes", type=int, default=30)
        sp.add_argument("--max-hourly-usd", default="0.75")
        sp.add_argument("--max-estimated-usd", default="0.50")
        if cmd == "rent":
            sp.add_argument("offer_id", type=int)
        else:
            sp.add_argument("--limit", type=int, default=8)
    for cmd in ("receipt", "status", "connection", "stop", "destroy", "reconcile"):
        sub.add_parser(cmd)
    sub.add_parser("adopt").add_argument("instance_id", type=int)
    return p


def execute(args):
    if args.cmd in ("search", "rent"):
        limits = Limits(args.vram_mb, args.disk_gb, args.minutes, args.max_hourly_usd, args.max_estimated_usd)
    if args.cmd == "search":
        with VastAPI(get_key("VAST_SEARCH_API_KEY")) as api:
            emit({"offers": discover(api, limits, args.limit), "mode": "SEARCH_ONLY"})
        return 0
    ledger = life.Ledger(state_path())
    record = ledger.open()
    if args.cmd == "receipt":
        emit(record or {"state": "NO_OPEN_LOCAL_LEASE", "note": "Not proof that no Vast instances exist."})
        return 0
    if args.cmd == "rent" and record is not None:
        raise VastError("An active or unresolved local lease exists. Review receipt and reconcile.")
    if args.cmd != "rent" and record is None:
        raise VastError("There is no open lease in this local ledger.")
    if args.cmd in ("rent", "stop", "destroy") and (not sys.stdin.isatty() or not sys.stdout.isatty()):
        raise VastError("This paid or destructive action requires an independent human terminal.")
    with VastAPI(get_key("VAST_LIFECYCLE_API_KEY"), writable=args.cmd in ("rent", "stop", "destroy")) as api:
        if args.cmd == "rent":
            quote, deadline = life.prepare_rental(api, limits, args.offer_id)
            quote_hash = digest(quote)
            emit({"quote": quote, "quote_sha256": quote_hash, "valid_seconds": life.QUOTE_VALID_SECONDS})
            print("Confirm this Vast account has no saved secrets in account/container environment settings; Vast can inject them automatically.")
            print("Starts one billable instance. Planned minutes are NOT auto-stop or a billing cap. Network/fees and actual runtime can cost more.")
            confirm(f"RENT {quote['offer_id']} {quote_hash[:16]}")
            emit(life.rent(api, ledger, limits, quote, deadline))
            return 0
        if args.cmd == "status":
            emit(life.status(api, record))
            return 0
        if args.cmd == "connection":
            emit(life.connection(api, record))
            return 0
        if args.cmd == "adopt":
            emit(life.adopt(api, ledger, record, args.instance_id))
            return 0
        if args.cmd == "reconcile":
            new = life.reconcile(api, ledger, record)
            emit(new)
            return 0 if new["state"] == "CLOSED" or new["state"] == "MANAGED" else 2
        if not record.get("instance_id") or record["state"] != "MANAGED":
            raise VastError("Pending/unknown action. Review receipt/reconcile before a new command.")
        life.read_owned(api, record)
        if args.cmd == "stop":
            print("Stopping GPU compute can leave storage charges. Destroy after exporting outputs.")
            confirm(f"STOP {record['instance_id']}")
            new = life.stop(api, ledger, record)
            emit(new)
            return 0 if new["state"] == "MANAGED" else 2
        if args.cmd == "destroy":
            print("Destroy permanently deletes instance-local data. Export and verify outputs first.")
            confirm(f"DESTROY {record['instance_id']}")
            new = life.destroy(api, ledger, record)
            emit(new)
            return 0 if new["state"] == "CLOSED" else 2
    return 2


def main() -> int:
    try:
        return execute(parser().parse_args())
    except (VastError, ValueError, sqlite3.Error) as exc:
        print(str(exc) if isinstance(exc, (VastError, ValueError)) else "Local receipt database unavailable. Inspect it before trying again.", file=sys.stderr)
        return 2
    except (EOFError, KeyboardInterrupt):
        print("Cancelled or interrupted. Check the local receipt and Vast console before any retry.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

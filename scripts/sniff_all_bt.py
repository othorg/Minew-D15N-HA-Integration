#!/usr/bin/env python3
"""Unfiltered BLE sniffer — cross-check for Phase 1 capture #7 (A3).

Captures every advertisement seen in range and writes them to
captures/d15n_cross_check.jsonl. Used after the D15N captures to verify
that our matcher (service UUID + local-name prefix) is specific enough.

Run for as long as is realistic for the household scenario (recommended:
≥ 5 min after running through the rooms with the BT adapter).

Examples:
    python scripts/sniff_all_bt.py --duration 5m
    python scripts/sniff_all_bt.py --duration 10m --out-dir captures
"""

from __future__ import annotations

import sys

from sniff_d15n import main as _sniff_main


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not any(a.startswith("--scenario") for a in args):
        args.extend(["--scenario", "cross_check"])
    # Explicitly drop any filters that may have leaked from the shell history.
    for flag in ("--filter-name", "--filter-mac", "--filter-uuid"):
        while flag in args:
            i = args.index(flag)
            del args[i : i + 2]
    return _sniff_main(args)


if __name__ == "__main__":
    sys.exit(main())

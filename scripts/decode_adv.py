#!/usr/bin/env python3
"""Decode and diff Minew D15N advertisement captures (Phase 1).

Reads one or more JSONL files produced by sniff_d15n.py and emits a
human-readable byte-diff table per service-data UUID across scenarios.
The goal is to spot which byte(s) encode trigger-source / battery /
counter on the D15N — exactly what is needed to write parser.py.

Examples:
    # Quick overview of one capture
    python scripts/decode_adv.py captures/d15n_idle.jsonl

    # Side-by-side diff across all tap scenarios
    python scripts/decode_adv.py captures/d15n_idle.jsonl \\
        captures/d15n_single_tap.jsonl captures/d15n_double_tap.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

# Well-known UUIDs/IDs we recognise in the table output.
EDDYSTONE_UUID = "0000feaa-0000-1000-8000-00805f9b34fb"
MINEW_CONFIG_UUID = "a3c87500-8ed3-4bdf-8a39-a01bebede295"
APPLE_MFR_ID = "76"  # 0x004C as decimal string — iBeacon


def _load(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def _scenario_of(records: list[dict[str, Any]], fallback: str) -> str:
    for rec in records:
        scn = rec.get("scenario")
        if isinstance(scn, str):
            return scn
    return fallback


def _summarise(records: list[dict[str, Any]]) -> dict[str, Any]:
    addrs = Counter(r["address"] for r in records)
    names = Counter(r.get("local_name") for r in records if r.get("local_name"))
    addr_types = Counter(r.get("address_type") for r in records)
    connectable = Counter(r.get("connectable") for r in records)
    service_uuids = Counter(u for r in records for u in r.get("service_uuids", []))
    service_data_keys = Counter(k for r in records for k in r.get("service_data_hex", {}))
    mfr_keys = Counter(k for r in records for k in r.get("manufacturer_data_hex", {}))
    rssi_values = [r["rssi"] for r in records if isinstance(r.get("rssi"), int)]
    rssi_min = min(rssi_values) if rssi_values else None
    rssi_max = max(rssi_values) if rssi_values else None
    return {
        "n": len(records),
        "unique_addresses": dict(addrs),
        "local_names": dict(names),
        "address_types": dict(addr_types),
        "connectable_flag": dict(connectable),
        "service_uuids": dict(service_uuids),
        "service_data_uuids": dict(service_data_keys),
        "manufacturer_ids": dict(mfr_keys),
        "rssi_range": (rssi_min, rssi_max),
    }


def _annotate_uuid(uuid: str) -> str:
    if uuid == EDDYSTONE_UUID:
        return f"{uuid}  (Eddystone 0xFEAA)"
    if uuid == MINEW_CONFIG_UUID:
        return f"{uuid}  (Minew config service)"
    return uuid


def _annotate_mfr(mid: str) -> str:
    if mid == APPLE_MFR_ID:
        return f"{mid}  (Apple 0x004C — iBeacon)"
    return mid


def _print_summary(scenario: str, summary: dict[str, Any]) -> None:
    print(f"=== {scenario} — {summary['n']} frames ===")
    print(f"  RSSI range: {summary['rssi_range']}")
    print(f"  Addresses : {summary['unique_addresses']}")
    print(f"  Local names: {summary['local_names']}")
    print(f"  Address types: {summary['address_types']}")
    print(f"  Connectable flag: {summary['connectable_flag']}")
    if summary["service_uuids"]:
        print("  Service UUIDs:")
        for uuid, n in sorted(summary["service_uuids"].items(), key=lambda kv: -kv[1]):
            print(f"    {n:4d}x {_annotate_uuid(uuid)}")
    if summary["service_data_uuids"]:
        print("  Service-Data UUIDs:")
        for uuid, n in sorted(summary["service_data_uuids"].items(), key=lambda kv: -kv[1]):
            print(f"    {n:4d}x {_annotate_uuid(uuid)}")
    if summary["manufacturer_ids"]:
        print("  Manufacturer IDs:")
        for mid, n in sorted(summary["manufacturer_ids"].items(), key=lambda kv: -kv[1]):
            print(f"    {n:4d}x {_annotate_mfr(mid)}")
    print()


def _first_payload_per_uuid(
    records: list[dict[str, Any]],
) -> dict[str, str]:
    out: dict[str, str] = {}
    for rec in records:
        for uuid, hex_str in rec.get("service_data_hex", {}).items():
            if uuid not in out:
                out[uuid] = hex_str
    return out


def _first_payload_per_mfr(records: list[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for rec in records:
        for mid, hex_str in rec.get("manufacturer_data_hex", {}).items():
            if mid not in out:
                out[mid] = hex_str
    return out


def _diff_hex(payloads: dict[str, str], *, color: bool = True) -> None:
    """Print one row per scenario, marking byte positions that vary."""
    if not payloads:
        return
    longest = max(len(hex_str) for hex_str in payloads.values()) // 2
    label_w = max(len(label) for label in payloads)

    print(f"  {'':{label_w}}  byte: " + " ".join(f"{i:02d}" for i in range(longest)))

    rows: dict[str, list[str]] = {}
    for label, hex_str in payloads.items():
        chunks = [hex_str[i : i + 2] for i in range(0, len(hex_str), 2)]
        chunks += ["--"] * (longest - len(chunks))
        rows[label] = chunks

    varies_at: list[int] = []
    if len(rows) > 1:
        labels = list(rows)
        for i in range(longest):
            vals = {rows[label][i] for label in labels}
            if len(vals) > 1:
                varies_at.append(i)

    for label, chunks in rows.items():
        annotated: list[str] = []
        for i, b in enumerate(chunks):
            if color and i in varies_at:
                annotated.append(f"\033[33m{b}\033[0m")
            else:
                annotated.append(b)
        print(f"  {label:{label_w}}        " + " ".join(annotated))
    if varies_at:
        print(f"  byte positions that differ: {varies_at}")
    print()


def _print_uuid_diff(
    per_scn_records: dict[str, list[dict[str, Any]]], *, color: bool = True
) -> None:
    print("\n=== Service-data byte diff across scenarios ===")
    uuids: set[str] = set()
    for records in per_scn_records.values():
        uuids.update(u for r in records for u in r.get("service_data_hex", {}))
    for uuid in sorted(uuids):
        print(f"\nService UUID: {_annotate_uuid(uuid)}")
        payloads: dict[str, str] = {}
        for scenario, records in per_scn_records.items():
            first = _first_payload_per_uuid(records).get(uuid)
            if first is not None:
                payloads[scenario] = first
        _diff_hex(payloads, color=color)


def _print_mfr_diff(
    per_scn_records: dict[str, list[dict[str, Any]]], *, color: bool = True
) -> None:
    print("\n=== Manufacturer-data byte diff across scenarios ===")
    flat: set[str] = set()
    for records in per_scn_records.values():
        for r in records:
            flat.update(r.get("manufacturer_data_hex", {}))
    for mid in sorted(flat):
        print(f"\nManufacturer ID: {_annotate_mfr(mid)}")
        payloads: dict[str, str] = {}
        for scenario, records in per_scn_records.items():
            first = _first_payload_per_mfr(records).get(mid)
            if first is not None:
                payloads[scenario] = first
        _diff_hex(payloads, color=color)


def _print_address_stability(per_scn_records: dict[str, list[dict[str, Any]]]) -> None:
    print("\n=== Address stability (A1 gate) ===")
    addrs_per_scn: dict[str, set[str]] = defaultdict(set)
    for scn, records in per_scn_records.items():
        for r in records:
            addrs_per_scn[scn].add(r["address"])
    all_addrs: set[str] = set()
    for s in addrs_per_scn.values():
        all_addrs |= s
    print(f"  Unique addresses across all captures: {len(all_addrs)}")
    for scn, addrs in addrs_per_scn.items():
        print(f"    {scn}: {sorted(addrs)}")
    if len(all_addrs) == 1:
        print("  MAC stable across captures (OK)")
    else:
        print("  MAC NOT stable - matcher should not rely on address alone")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="decode_adv.py", description=__doc__)
    p.add_argument("inputs", type=Path, nargs="+", help="JSONL capture files")
    p.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI escape codes (for piping into a file).",
    )
    args = p.parse_args(argv)
    color = not args.no_color

    per_scn_records: dict[str, list[dict[str, Any]]] = {}
    for path in args.inputs:
        records = _load(path)
        scenario = _scenario_of(records, fallback=path.stem)
        per_scn_records[scenario] = records
        summary = _summarise(records)
        _print_summary(scenario, summary)

    _print_uuid_diff(per_scn_records, color=color)
    _print_mfr_diff(per_scn_records, color=color)
    _print_address_stability(per_scn_records)
    return 0


if __name__ == "__main__":
    sys.exit(main())

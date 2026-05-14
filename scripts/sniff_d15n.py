#!/usr/bin/env python3
"""BLE sniffer for the Minew D15N beacon (Phase 1).

Captures each matching advertisement to a JSON-Lines file under
captures/d15n_<scenario>.jsonl for later analysis with decode_adv.py.

Examples:
    # 60 s idle baseline
    python scripts/sniff_d15n.py --scenario idle --duration 60

    # Single-tap capture filtered by local-name prefix
    python scripts/sniff_d15n.py --scenario single_tap \\
        --duration 60 --filter-name MinewT_

    # 24 h MAC-stability long-run (A1 gate)
    python scripts/sniff_d15n.py --scenario long_run \\
        --long-run 24h --filter-name MinewT_

Filters are OR-combined inside this script (any match → log the frame).
Passing zero filters logs every advertisement seen — useful for the very
first probe to find the beacon's MAC / name.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import platform
import re
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from bleak import BleakScanner

if TYPE_CHECKING:
    from collections.abc import Iterable

    from bleak.backends.device import BLEDevice
    from bleak.backends.scanner import AdvertisementData

DURATION_RE = re.compile(r"^(\d+(?:\.\d+)?)([smhd])?$")


def parse_duration(value: str) -> float:
    """Parse a duration like '60', '90s', '5m', '24h', '1d' → seconds."""
    match = DURATION_RE.match(value.strip().lower())
    if not match:
        raise argparse.ArgumentTypeError(
            f"invalid duration {value!r}; expected e.g. '60', '90s', '5m', '24h', '1d'"
        )
    n = float(match.group(1))
    unit = match.group(2) or "s"
    factor = {"s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}[unit]
    return n * factor


def _is_connectable(adv: AdvertisementData) -> bool | None:
    """Best-effort extraction of the connectable flag from platform_data.

    macOS (CoreBluetooth): platform_data[1] is a dict with key
        'kCBAdvDataIsConnectable' (bool).
    Linux (BlueZ): platform_data[0] is a dict with key 'Connectable' (bool).
    Windows: not exposed; returns None.
    """
    pd = adv.platform_data
    if not pd:
        return None
    for item in pd:
        if isinstance(item, dict):
            for key in ("kCBAdvDataIsConnectable", "Connectable", "connectable"):
                if key in item:
                    return bool(item[key])
    return None


def _extract_address_type(device: BLEDevice) -> str | None:
    """Best-effort extraction of the BLE address type.

    BlueZ exposes 'AddressType' ∈ {'public', 'random'} on the device proxy.
    CoreBluetooth abstracts addresses to UUIDs and does not expose the type.
    """
    details = device.details
    if isinstance(details, dict):
        for key in ("AddressType", "address_type"):
            value = details.get(key)
            if isinstance(value, str):
                return value
    if isinstance(details, tuple):
        for item in details:
            if isinstance(item, dict):
                for key in ("AddressType", "address_type"):
                    value = item.get(key)
                    if isinstance(value, str):
                        return value
    return None


def _adv_to_record(device: BLEDevice, adv: AdvertisementData) -> dict[str, Any]:
    """Serialise one advertisement into a JSON-compatible record."""
    return {
        "ts_iso": datetime.now(tz=UTC).isoformat(timespec="microseconds"),
        "ts_monotonic": time.monotonic(),
        "address": device.address,
        "name": device.name,
        "local_name": adv.local_name,
        "rssi": adv.rssi,
        "tx_power": adv.tx_power,
        "service_uuids": list(adv.service_uuids),
        "service_data_hex": {uuid: data.hex() for uuid, data in adv.service_data.items()},
        "manufacturer_data_hex": {
            str(mid): data.hex() for mid, data in adv.manufacturer_data.items()
        },
        "connectable": _is_connectable(adv),
        "address_type": _extract_address_type(device),
    }


def _matches_filters(
    device: BLEDevice,
    adv: AdvertisementData,
    name_prefix: str | None,
    mac: str | None,
    service_uuid: str | None,
) -> bool:
    if name_prefix is None and mac is None and service_uuid is None:
        return True  # no filters → log everything
    if name_prefix is not None:
        for candidate in (adv.local_name, device.name):
            if candidate and candidate.startswith(name_prefix):
                return True
    if mac is not None and device.address.lower() == mac.lower():
        return True
    return service_uuid is not None and service_uuid.lower() in (
        u.lower() for u in adv.service_uuids
    )


class Sink:
    """Append-only JSONL writer with periodic stdout progress."""

    def __init__(self, path: Path, *, progress_every: int = 50) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = path.open("a", encoding="utf-8")
        self._count = 0
        self._every = progress_every
        self._path = path
        self._start = time.monotonic()
        print(f"[sniff] writing to {path}")

    def write(self, record: dict[str, Any]) -> None:
        self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._fh.flush()
        self._count += 1
        if self._count % self._every == 0:
            elapsed = time.monotonic() - self._start
            rate = self._count / elapsed if elapsed > 0 else 0.0
            print(
                f"[sniff] {self._count:5d} frames in {elapsed:6.1f}s "
                f"({rate:5.1f} ADV/s) — last: rssi={record['rssi']} "
                f"addr={record['address']} name={record['local_name']!r}"
            )

    def close(self) -> None:
        self._fh.close()
        elapsed = time.monotonic() - self._start
        print(
            f"[sniff] done — {self._count} frames in {elapsed:.1f}s → {self._path}"
        )


async def run_capture(
    *,
    scenario: str,
    duration: float,
    out_dir: Path,
    name_prefix: str | None,
    mac: str | None,
    service_uuid: str | None,
    scanning_mode: Literal["active", "passive"],
) -> int:
    path = out_dir / f"d15n_{scenario}.jsonl"
    sink = Sink(path)

    stop_event = asyncio.Event()

    def _sig_handler(*_: object) -> None:
        if not stop_event.is_set():
            print("\n[sniff] signal received — stopping capture")
            stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _sig_handler)

    def callback(device: BLEDevice, adv: AdvertisementData) -> None:
        if not _matches_filters(device, adv, name_prefix, mac, service_uuid):
            return
        record = _adv_to_record(device, adv)
        record["scenario"] = scenario
        sink.write(record)

    scanner = BleakScanner(detection_callback=callback, scanning_mode=scanning_mode)

    print(
        f"[sniff] scenario={scenario!r} duration={duration:.0f}s "
        f"mode={scanning_mode} platform={platform.system()} "
        f"filters: name~{name_prefix!r} mac~{mac!r} uuid~{service_uuid!r}"
    )

    try:
        await scanner.start()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop_event.wait(), timeout=duration)
    finally:
        await scanner.stop()
        sink.close()
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sniff_d15n.py",
        description="Capture Minew D15N advertisements to JSONL.",
    )
    p.add_argument(
        "--scenario",
        required=True,
        help="Scenario label, used in the output filename "
        "(e.g. idle, single_tap, double_tap, triple_tap, long_press, long_run).",
    )
    duration_group = p.add_mutually_exclusive_group()
    duration_group.add_argument(
        "--duration",
        type=parse_duration,
        default=parse_duration("60s"),
        help="Capture duration (default: 60s). Accepts e.g. 90s, 5m, 24h.",
    )
    duration_group.add_argument(
        "--long-run",
        type=parse_duration,
        dest="long_run",
        help="Alias for --duration; intended for the 24h MAC-stability run.",
    )
    p.add_argument(
        "--filter-name",
        dest="name_prefix",
        help="Match advertisements whose local_name starts with this prefix.",
    )
    p.add_argument(
        "--filter-mac",
        dest="mac",
        help="Match advertisements from this exact device address.",
    )
    p.add_argument(
        "--filter-uuid",
        dest="service_uuid",
        help="Match advertisements containing this service UUID.",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=Path("captures"),
        help="Directory for JSONL output (default: ./captures).",
    )
    p.add_argument(
        "--scanning-mode",
        choices=("active", "passive"),
        default="active",
        help="BleakScanner scanning_mode (default: active). 'passive' mirrors "
        "Home Assistant's bluetooth integration but requires BlueZ on Linux.",
    )
    return p


def main(argv: Iterable[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    duration: float = args.long_run if args.long_run is not None else args.duration
    return asyncio.run(
        run_capture(
            scenario=args.scenario,
            duration=duration,
            out_dir=args.out_dir,
            name_prefix=args.name_prefix,
            mac=args.mac,
            service_uuid=args.service_uuid,
            scanning_mode=args.scanning_mode,
        )
    )


if __name__ == "__main__":
    sys.exit(main())

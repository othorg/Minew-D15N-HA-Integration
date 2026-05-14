"""Pytest fixtures for the minewtech_d15n integration tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from custom_components.minewtech_d15n.const import (
    SERVICE_UUID_EDDYSTONE,
    SERVICE_UUID_VENDOR,
)
from habluetooth.models import BluetoothServiceInfoBleak

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    """Read a JSON fixture from tests/fixtures/."""
    with (FIXTURES_DIR / name).open("r", encoding="utf-8") as fh:
        result: dict[str, Any] = json.load(fh)
        return result


def make_service_info(
    *,
    service_data_hex: str,
    address: str = "c3:00:00:4b:06:53",
    name: str | None = None,
    rssi: int = -45,
    tx_power: int | None = -24,
    time: float = 0.0,
    extra_service_uuids: tuple[str, ...] = (SERVICE_UUID_VENDOR,),
    manufacturer_data: dict[int, bytes] | None = None,
) -> BluetoothServiceInfoBleak:
    """Build a BluetoothServiceInfoBleak instance from raw hex service-data.

    Mirrors the structure HA produces in production. All optional fields
    default to values that match the real D15N (no local_name, no
    manufacturer_data, vendor UUID present in the ADV header).
    """
    payload = bytes.fromhex(service_data_hex)
    return BluetoothServiceInfoBleak(
        name=name,
        address=address,
        rssi=rssi,
        manufacturer_data=manufacturer_data or {},
        service_data={SERVICE_UUID_EDDYSTONE: payload},
        service_uuids=[SERVICE_UUID_EDDYSTONE, *extra_service_uuids],
        source="hci0",
        device=None,
        advertisement=None,
        connectable=False,
        time=time,
        tx_power=tx_power,
        raw=None,
    )


@pytest.fixture
def uid_fixture() -> dict[str, Any]:
    """Eddystone-UID fixture with expected parsed values."""
    return load_fixture("eddystone_uid_idle.json")


@pytest.fixture
def url_fixture() -> dict[str, Any]:
    """Eddystone-URL fixture with expected parsed values."""
    return load_fixture("eddystone_url_idle.json")


@pytest.fixture
def tlm_fixture() -> dict[str, Any]:
    """Eddystone-TLM fixture with expected parsed values."""
    return load_fixture("eddystone_tlm_idle.json")


@pytest.fixture
def ibeacon_fixture() -> dict[str, Any]:
    """iBeacon fixture captured via HA on hci0 (Linux/BlueZ)."""
    return load_fixture("ibeacon_d15n.json")

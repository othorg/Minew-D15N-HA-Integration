"""Pytest fixtures for the minewtech_d15n integration tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

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


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: Any) -> None:
    """Make the local `custom_components/` tree available to every test.

    Without this fixture HA's loader treats the integration as not-
    installed and ``async_init`` of the config flow raises
    ``UnknownHandler``. The upstream fixture is parametrised per-test;
    yielding via autouse keeps the integration discoverable across the
    whole suite.
    """
    return None


@pytest.fixture(autouse=True)
def stub_bluetooth_history_loader() -> Any:
    """Mock the bluetooth manager's adapter-history bootstrap.

    HA's ``async_load_history_from_system`` crashes inside the test
    environment because there is no real BlueZ / CoreBluetooth backend
    to serve adapter metadata. The function only matters at startup
    (recovering the last-seen advertisement cache after restart) — we
    can replace it with a no-op that returns empty dicts for the
    duration of every test.
    """
    with patch(
        "homeassistant.components.bluetooth.manager.async_load_history_from_system",
        return_value=({}, {}),
    ):
        yield

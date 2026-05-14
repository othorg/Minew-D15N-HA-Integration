"""Tests for the D15N sensor and device_tracker entities.

Strategy:
- Entity state-tests use a real hass fixture (needed to register entities
  in the entity registry and call async_write_ha_state through the HA
  state machine).
- Coordinator-listener wiring and is_connected logic are unit-tested
  directly on the classes to avoid hass overhead.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from custom_components.minewtech_d15n.const import (
    CONF_ADDRESS,
    CONF_MAX_AGE_SECONDS,
    CONF_STABLE_ID,
    DEFAULT_MAX_AGE_SECONDS,
    DOMAIN,
)
from custom_components.minewtech_d15n.coordinator import D15NPassiveCoordinator
from custom_components.minewtech_d15n.device_tracker import D15NDeviceTracker
from custom_components.minewtech_d15n.parser import AddressType, D15NAdvertisement
from custom_components.minewtech_d15n.sensor import (
    D15NBatterySensor,
    D15NLastSeenSensor,
    D15NRssiSensor,
)
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

STABLE_ID = "eddystone:00112233445566778899:abcde76b01f4"
MAC = "c3:00:00:4b:06:53"


def _make_advertisement(
    *,
    battery_pct: int | None = 85,
    rssi: int = -45,
    timestamp: float | None = None,
) -> D15NAdvertisement:
    return D15NAdvertisement(
        stable_id=STABLE_ID,
        address=MAC,
        address_type=AddressType.RANDOM_STATIC,
        local_name=None,
        rssi=rssi,
        battery_pct=battery_pct,
        trigger_event=None,
        trigger_counter=None,
        timestamp=timestamp if timestamp is not None else time.monotonic(),
        raw=b"",
    )


def _make_bare_coordinator() -> D15NPassiveCoordinator:
    """Build a coordinator without invoking the HA base __init__."""
    coord: D15NPassiveCoordinator = D15NPassiveCoordinator.__new__(D15NPassiveCoordinator)
    coord._last_advertisement = None
    coord._last_battery_pct = None
    coord._update_listeners = []
    coord._processors = []
    coord.last_update_success = True
    coord.logger = MagicMock()
    coord._available = True
    coord.address = MAC
    return coord


def _make_config_entry(**options: Any) -> MagicMock:
    entry = MagicMock()
    entry.data = {CONF_STABLE_ID: STABLE_ID, CONF_ADDRESS: MAC}
    entry.options = {CONF_MAX_AGE_SECONDS: DEFAULT_MAX_AGE_SECONDS, **options}
    return entry


# ---------------------------------------------------------------------------
# Coordinator listener wiring
# ---------------------------------------------------------------------------


class TestCoordinatorListener:
    def test_listener_registered_and_called_on_update(self) -> None:
        coord = _make_bare_coordinator()
        received: list[int] = []
        coord.async_add_listener(lambda: received.append(1))
        coord._process_update(_make_advertisement())
        assert received == [1]

    def test_listener_removed_via_return_value(self) -> None:
        coord = _make_bare_coordinator()
        received: list[int] = []
        remove = coord.async_add_listener(lambda: received.append(1))
        remove()
        coord._process_update(_make_advertisement())
        assert received == []

    def test_none_update_still_notifies_listeners(self) -> None:
        coord = _make_bare_coordinator()
        received: list[int] = []
        coord.async_add_listener(lambda: received.append(1))
        coord._process_update(None)
        assert received == [1]

    def test_last_advertisement_unchanged_on_none_update(self) -> None:
        coord = _make_bare_coordinator()
        adv = _make_advertisement()
        coord._process_update(adv)
        coord._process_update(None)
        assert coord.last_advertisement is adv


# ---------------------------------------------------------------------------
# Sensor state logic
# ---------------------------------------------------------------------------


class TestSensorValues:
    def test_battery_returns_none_before_first_adv(self) -> None:
        coord = _make_bare_coordinator()
        sensor = D15NBatterySensor(coord, STABLE_ID)
        assert sensor.native_value is None

    def test_battery_reads_pct_from_tlm_frame(self) -> None:
        coord = _make_bare_coordinator()
        coord._process_update(_make_advertisement(battery_pct=72))
        sensor = D15NBatterySensor(coord, STABLE_ID)
        assert sensor.native_value == 72

    def test_battery_sticky_across_non_tlm_frames(self) -> None:
        # A UID/URL frame (battery_pct=None) must NOT reset the cached value
        # to None — that would cause the sensor to flap between 72 and unknown
        # as the beacon rotates through its advertisement slots.
        coord = _make_bare_coordinator()
        coord._process_update(_make_advertisement(battery_pct=72))
        coord._process_update(_make_advertisement(battery_pct=None))  # UID/URL
        sensor = D15NBatterySensor(coord, STABLE_ID)
        assert sensor.native_value == 72  # must stay at 72, not become None

    def test_rssi_returns_none_before_first_adv(self) -> None:
        coord = _make_bare_coordinator()
        sensor = D15NRssiSensor(coord, STABLE_ID)
        assert sensor.native_value is None

    def test_rssi_reads_from_advertisement(self) -> None:
        coord = _make_bare_coordinator()
        coord._last_advertisement = _make_advertisement(rssi=-62)
        sensor = D15NRssiSensor(coord, STABLE_ID)
        assert sensor.native_value == -62

    def test_last_seen_returns_none_before_first_adv(self) -> None:
        coord = _make_bare_coordinator()
        sensor = D15NLastSeenSensor(coord, STABLE_ID)
        assert sensor.native_value is None

    def test_last_seen_returns_utc_datetime_near_now(self) -> None:
        coord = _make_bare_coordinator()
        coord._last_advertisement = _make_advertisement(
            timestamp=time.monotonic()  # just-received ADV
        )
        sensor = D15NLastSeenSensor(coord, STABLE_ID)
        result = sensor.native_value
        assert result is not None
        assert result.tzinfo is UTC
        # Must be within 2 seconds of now (not ~1970 from a raw monotonic
        # timestamp passed to datetime.fromtimestamp).
        now = datetime.now(tz=UTC)
        assert abs((result - now).total_seconds()) < 2


# ---------------------------------------------------------------------------
# device_tracker is_connected logic
# ---------------------------------------------------------------------------


class TestDeviceTrackerIsConnected:
    def test_not_connected_before_first_advertisement(self) -> None:
        coord = _make_bare_coordinator()
        entry = _make_config_entry()
        tracker = D15NDeviceTracker(coord, STABLE_ID, entry)
        assert tracker.is_connected is False

    def test_connected_when_adv_within_max_age(self) -> None:
        coord = _make_bare_coordinator()
        entry = _make_config_entry(**{CONF_MAX_AGE_SECONDS: 300})
        coord._last_advertisement = _make_advertisement(timestamp=time.monotonic() - 10)
        tracker = D15NDeviceTracker(coord, STABLE_ID, entry)
        assert tracker.is_connected is True

    def test_not_connected_when_adv_older_than_max_age(self) -> None:
        coord = _make_bare_coordinator()
        entry = _make_config_entry(**{CONF_MAX_AGE_SECONDS: 30})
        coord._last_advertisement = _make_advertisement(timestamp=time.monotonic() - 60)
        tracker = D15NDeviceTracker(coord, STABLE_ID, entry)
        assert tracker.is_connected is False

    def test_max_age_read_live_from_options(self) -> None:
        """Changing entry.options reflects immediately without reload."""
        coord = _make_bare_coordinator()
        entry = _make_config_entry(**{CONF_MAX_AGE_SECONDS: 300})
        coord._last_advertisement = _make_advertisement(timestamp=time.monotonic() - 120)
        tracker = D15NDeviceTracker(coord, STABLE_ID, entry)
        assert tracker.is_connected is True  # 120 < 300

        # Reduce the window; should flip to not_home without reload.
        entry.options = {CONF_MAX_AGE_SECONDS: 60}
        assert tracker.is_connected is False  # 120 > 60


# ---------------------------------------------------------------------------
# Integration: setup + entity states via hass fixture
# ---------------------------------------------------------------------------


class TestEntitySetup:
    @pytest.mark.asyncio
    async def test_four_entities_created_per_entry(self, hass: Any) -> None:
        """async_setup_entry must register 3 sensors + 1 device_tracker."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id=STABLE_ID,
            data={CONF_STABLE_ID: STABLE_ID, CONF_ADDRESS: MAC},
            options={CONF_MAX_AGE_SECONDS: DEFAULT_MAX_AGE_SECONDS},
        )
        entry.add_to_hass(hass)

        with patch(
            "custom_components.minewtech_d15n.coordinator.D15NPassiveCoordinator"
        ) as MockCoord:
            fake_coord = _make_bare_coordinator()
            MockCoord.return_value = fake_coord
            fake_coord.async_start = MagicMock(return_value=MagicMock())
            assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        registry = er.async_get(hass)
        our_entities = [
            e for e in registry.entities.values() if e.config_entry_id == entry.entry_id
        ]
        sensor_entities = [e for e in our_entities if e.domain == "sensor"]
        tracker_entities = [e for e in our_entities if e.domain == "device_tracker"]
        assert len(sensor_entities) == 3, f"expected 3 sensors, got {sensor_entities}"
        assert len(tracker_entities) == 1, f"expected 1 tracker, got {tracker_entities}"

    @pytest.mark.asyncio
    async def test_sensor_state_updates_on_coordinator_listener(self, hass: Any) -> None:
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id=STABLE_ID,
            data={CONF_STABLE_ID: STABLE_ID, CONF_ADDRESS: MAC},
            options={CONF_MAX_AGE_SECONDS: DEFAULT_MAX_AGE_SECONDS},
        )
        entry.add_to_hass(hass)

        with patch(
            "custom_components.minewtech_d15n.coordinator.D15NPassiveCoordinator"
        ) as MockCoord:
            fake_coord = _make_bare_coordinator()
            MockCoord.return_value = fake_coord
            fake_coord.async_start = MagicMock(return_value=MagicMock())
            await hass.config_entries.async_setup(entry.entry_id)

        # Simulate a TLM advertisement arriving via _process_update so that
        # both _last_advertisement and _last_battery_pct are updated.
        fake_coord._process_update(_make_advertisement(battery_pct=90, rssi=-50))
        await hass.async_block_till_done()

        battery_state = hass.states.get(f"sensor.d15n_{MAC.replace(':', '')}_battery")
        if battery_state is None:
            # Entity ID may vary; find by unique_id suffix
            for eid in hass.states.async_entity_ids("sensor"):
                if "battery" in eid:
                    battery_state = hass.states.get(eid)
                    break
        assert battery_state is not None
        assert battery_state.state == "90"

    @pytest.mark.asyncio
    async def test_unload_removes_all_entities(self, hass: Any) -> None:
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id=STABLE_ID,
            data={CONF_STABLE_ID: STABLE_ID, CONF_ADDRESS: MAC},
            options={CONF_MAX_AGE_SECONDS: DEFAULT_MAX_AGE_SECONDS},
        )
        entry.add_to_hass(hass)

        with patch(
            "custom_components.minewtech_d15n.coordinator.D15NPassiveCoordinator"
        ) as MockCoord:
            fake_coord = _make_bare_coordinator()
            MockCoord.return_value = fake_coord
            fake_coord.async_start = MagicMock(return_value=MagicMock())
            await hass.config_entries.async_setup(entry.entry_id)

        await hass.async_block_till_done()
        registry = er.async_get(hass)
        our_entities_before = [
            e for e in registry.entities.values() if e.config_entry_id == entry.entry_id
        ]
        assert len(our_entities_before) >= 4

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

        # After unload all entity states must be unavailable (HA marks them
        # unavailable on unload; they are removed from the registry only on
        # entry deletion, which is not tested here).
        for reg_entry in our_entities_before:
            state = hass.states.get(reg_entry.entity_id)
            # State is either None (never written) or "unavailable".
            assert state is None or state.state == "unavailable", (
                f"{reg_entry.entity_id} still has state {state.state!r}"
            )

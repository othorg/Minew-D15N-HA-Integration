"""Sensor platform for the Minewtech D15N integration.

Provides three read-only sensors per beacon:

- Battery: TLM voltage converted to percentage (0-100 %).
- RSSI: received signal-strength indicator in dBm.
- Last Seen: ISO-8601 timestamp of the most recent advertisement.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, SIGNAL_STRENGTH_DECIBELS_MILLIWATT, EntityCategory

from .const import CONF_STABLE_ID
from .entity_base import D15NEntity

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import D15NPassiveCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up D15N sensor entities from a config entry."""
    coordinator: D15NPassiveCoordinator = entry.runtime_data
    stable_id: str = entry.data[CONF_STABLE_ID]
    async_add_entities(
        [
            D15NBatterySensor(coordinator, stable_id),
            D15NRssiSensor(coordinator, stable_id),
            D15NLastSeenSensor(coordinator, stable_id),
        ]
    )


class D15NBatterySensor(D15NEntity, SensorEntity):
    """Beacon battery level derived from the Eddystone-TLM voltage field."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: D15NPassiveCoordinator, stable_id: str) -> None:
        super().__init__(coordinator, stable_id)
        self._attr_unique_id = f"{stable_id}_battery"

    @property
    def native_value(self) -> int | None:
        # Use the coordinator's sticky cache instead of the raw
        # advertisement field: only TLM frames carry battery data, so
        # reading directly from last_advertisement causes the sensor to
        # flap between the real value and unknown every time a UID/URL/
        # iBeacon slot is received.
        return self._coordinator.last_battery_pct


class D15NRssiSensor(D15NEntity, SensorEntity):
    """Received signal-strength indicator (dBm) of the last advertisement."""

    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: D15NPassiveCoordinator, stable_id: str) -> None:
        super().__init__(coordinator, stable_id)
        self._attr_unique_id = f"{stable_id}_rssi"

    @property
    def native_value(self) -> int | None:
        adv = self._coordinator.last_advertisement
        return adv.rssi if adv is not None else None


class D15NLastSeenSensor(D15NEntity, SensorEntity):
    """UTC timestamp of the most recently received advertisement."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: D15NPassiveCoordinator, stable_id: str) -> None:
        super().__init__(coordinator, stable_id)
        self._attr_unique_id = f"{stable_id}_last_seen"

    @property
    def native_value(self) -> datetime | None:
        adv = self._coordinator.last_advertisement
        if adv is None:
            return None
        # adv.timestamp is service_info.time — monotonic uptime, not
        # Unix epoch. Convert to real-world UTC by subtracting the
        # elapsed seconds from now.
        elapsed = time.monotonic() - adv.timestamp
        return datetime.now(tz=UTC) - timedelta(seconds=elapsed)


__all__ = ["D15NBatterySensor", "D15NLastSeenSensor", "D15NRssiSensor", "async_setup_entry"]

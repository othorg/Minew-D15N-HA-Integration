"""Device tracker platform for the Minewtech D15N integration.

Provides one ``device_tracker`` entity per beacon that switches between
``home`` and ``not_home`` based on how recently an advertisement was
received. The inactivity window is controlled by the ``max_age_seconds``
option (configurable via the Options Flow, default 300 s).

The check is purely time-based using ``adv.timestamp`` (monotonic time
from HA's bluetooth scanner) rather than ``async_address_present``,
because the latter does not expose an age threshold and because using our
own timestamp allows the device_tracker to react instantly when the user
changes ``max_age_seconds`` without requiring an entry reload.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from homeassistant.components.device_tracker.config_entry import ScannerEntity
from homeassistant.components.device_tracker.const import SourceType

from .const import CONF_MAX_AGE_SECONDS, CONF_STABLE_ID, DEFAULT_MAX_AGE_SECONDS
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
    """Set up the D15N device tracker from a config entry."""
    coordinator: D15NPassiveCoordinator = entry.runtime_data
    stable_id: str = entry.data[CONF_STABLE_ID]
    async_add_entities([D15NDeviceTracker(coordinator, stable_id, entry)])


class D15NDeviceTracker(D15NEntity, ScannerEntity):
    """BLE presence tracker for the Minewtech D15N beacon.

    Reports ``home`` when the most recent advertisement arrived within
    ``max_age_seconds`` seconds; ``not_home`` otherwise. The threshold is
    read live from ``entry.options`` so changes via the Options Flow take
    effect immediately without an entry reload.
    """

    _attr_source_type = SourceType.BLUETOOTH_LE
    # ScannerEntity.entity_registry_enabled_default can return False when
    # the Bluetooth coordinator has not yet registered the device entry.
    # Force True so the tracker is visible immediately after setup.
    _attr_entity_registry_enabled_default = True

    def __init__(
        self,
        coordinator: D15NPassiveCoordinator,
        stable_id: str,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, stable_id)
        self._entry = entry
        self._attr_unique_id = f"{stable_id}_device_tracker"
        self._attr_mac_address = coordinator.address

    @property
    def is_connected(self) -> bool:
        """Return ``True`` when the beacon was seen within max_age_seconds."""
        adv = self._coordinator.last_advertisement
        if adv is None:
            return False
        max_age: float = self._entry.options.get(
            CONF_MAX_AGE_SECONDS, DEFAULT_MAX_AGE_SECONDS
        )
        return (time.monotonic() - adv.timestamp) < max_age


__all__ = ["D15NDeviceTracker", "async_setup_entry"]

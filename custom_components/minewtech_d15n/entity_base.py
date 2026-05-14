"""Shared base entity for the Minewtech D15N integration.

All platform entities (sensor, device_tracker) inherit from
:class:`D15NEntity`. The base handles:

- HA device-info registration via the stable-id.
- Coordinator listener registration / cleanup.
- ``available`` delegated to the coordinator's own ``available`` flag.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, MANUFACTURER, MODEL

if TYPE_CHECKING:
    from .coordinator import D15NPassiveCoordinator


class D15NEntity(Entity):
    """Base class for all D15N entities.

    Subclasses must set ``_attr_unique_id`` in their ``__init__`` and
    implement the state-specific properties.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _register_default_coordinator_listener = True

    def __init__(
        self,
        coordinator: D15NPassiveCoordinator,
        stable_id: str,
    ) -> None:
        self._coordinator = coordinator
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, stable_id)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name=f"D15N {coordinator.address}",
        )

    @property
    def available(self) -> bool:
        return self._coordinator.available

    async def async_added_to_hass(self) -> None:
        if self._register_default_coordinator_listener:
            self.async_on_remove(
                self._coordinator.async_add_listener(self._handle_coordinator_update)
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Called by the coordinator after each successfully parsed ADV."""
        self.async_write_ha_state()

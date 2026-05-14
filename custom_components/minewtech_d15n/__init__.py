"""Minewtech D15N Beacon integration for Home Assistant.

Sets up the passive Bluetooth coordinator and forwards platform setup to
``device_tracker`` and ``sensor``. The ``event`` platform is intentionally
skipped per the PLAN.md §10.1 fallback A2 decision (no button-events in v1).

The :mod:`coordinator` module is imported lazily inside
:func:`async_setup_entry` rather than at module top. This is deliberate:
the coordinator's import chain transitively loads
``homeassistant.components.usb`` (via ``homeassistant.components.bluetooth``),
which in turn drags in Linux-only wheels (``aioesphomeapi`` /
``serialx.platforms``). Keeping the top-level import surface to ``.const``
keeps the package importable on macOS dev machines and inside our test
suite without dragging the full HA runtime tree.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .const import CONF_ADDRESS, PLATFORMS

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .coordinator import D15NPassiveCoordinator

    type D15NConfigEntry = ConfigEntry[D15NPassiveCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: D15NConfigEntry) -> bool:
    """Set up a Minew D15N config entry.

    Creates the passive Bluetooth coordinator, parks it on
    ``entry.runtime_data``, registers it for callback teardown on unload,
    and forwards setup to the configured platforms.
    """
    from .coordinator import D15NPassiveCoordinator  # noqa: PLC0415

    address: str = entry.data[CONF_ADDRESS]
    coordinator = D15NPassiveCoordinator(hass, address)
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Start only after platforms are set up so their listeners are registered
    # before the first advertisements are processed.
    entry.async_on_unload(coordinator.async_start())
    return True


async def async_unload_entry(hass: HomeAssistant, entry: D15NConfigEntry) -> bool:
    """Tear down a Minew D15N config entry.

    The coordinator's bluetooth callbacks are released by the
    ``async_on_unload`` registration in :func:`async_setup_entry`; here we
    only need to unload the platforms.
    """
    unloaded: bool = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    return unloaded

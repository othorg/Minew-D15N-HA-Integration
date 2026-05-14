"""Passive Bluetooth coordinator for the Minew D15N integration.

Wraps Home Assistant's :class:`PassiveBluetoothProcessorCoordinator` with the
D15N parser as ``update_method``. The coordinator is address-pinned: it
matches advertisements from a single BLE address (the one captured during
config-flow discovery). MAC rotation is out of scope for v1 — if the
beacon's address ever changes, the user creates a new config entry; the
old one becomes inactive.

Trigger handling (PLAN.md §10.1 fallback A2): the coordinator does *not*
deduplicate or dispatch button events, because trigger advertisements are
not implemented in v1. The ``D15NAdvertisement.trigger_event`` field is
always ``None``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from habluetooth import BluetoothScanningMode
from homeassistant.components.bluetooth.passive_update_processor import (
    PassiveBluetoothProcessorCoordinator,
)
from homeassistant.core import callback

from .parser import D15NAdvertisement, parse, parse_for_known_address

if TYPE_CHECKING:
    from collections.abc import Callable

    from habluetooth.models import BluetoothServiceInfoBleak
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class D15NPassiveCoordinator(PassiveBluetoothProcessorCoordinator[D15NAdvertisement | None]):
    """Coordinator that dispatches parsed D15N advertisements to entities.

    The base class fans the parser output out to every registered
    :class:`PassiveBluetoothDataProcessor`; entities subscribe to a
    processor in their platform setup (see ``sensor.py`` /
    ``device_tracker.py`` in Phase 5).
    """

    def __init__(self, hass: HomeAssistant, address: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            address=address,
            mode=BluetoothScanningMode.PASSIVE,
            update_method=self._update_method,
            connectable=False,
        )
        self._last_advertisement: D15NAdvertisement | None = None
        self._last_battery_pct: int | None = None
        self._update_listeners: list[Callable[[], None]] = []

    @property
    def last_battery_pct(self) -> int | None:
        """Return the most recently received battery percentage.

        Unlike ``last_advertisement.battery_pct``, this value is sticky:
        it is only overwritten when a non-``None`` value arrives (i.e. a
        TLM frame). Eddystone-UID / URL / iBeacon frames carry no battery
        data, so reading ``battery_pct`` from the raw advertisement causes
        the sensor to flap between the real value and ``unknown`` as the
        beacon rotates through its advertisement slots.
        """
        return self._last_battery_pct

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register a callback invoked after every ADV update, including None.

        Listeners fire even when the parser returns ``None`` (e.g. a non-D15N
        frame slips through, or the device becomes unavailable). Consumers
        should read ``last_advertisement`` and handle ``None`` gracefully.

        Returns a de-registration callable suitable for use with
        ``Entity.async_on_remove``.
        """
        self._update_listeners.append(listener)

        @callback
        def remove() -> None:
            self._update_listeners.remove(listener)

        return remove

    @staticmethod
    def _update_method(
        service_info: BluetoothServiceInfoBleak,
    ) -> D15NAdvertisement | None:
        """Parse one ADV for the already-selected beacon address.

        The coordinator itself is address-filtered by HA bluetooth. We keep
        :func:`parse` in the loop for explicit D15N guard semantics, then
        fall back to :func:`parse_for_known_address` so iBeacon-only /
        sparse slot frames from the same address still refresh tracker state.
        """
        strict = parse(service_info)
        if strict is not None:
            return strict
        return parse_for_known_address(service_info)

    @property
    def last_advertisement(self) -> D15NAdvertisement | None:
        """Return the most recently parsed D15N advertisement, or ``None``.

        Updated as a side effect of the ``_update_method`` path; consumers
        that need the latest snapshot without registering a processor can
        read this property.
        """
        return self._last_advertisement

    def _process_update(
        self,
        update: D15NAdvertisement | None,
        was_available: bool | None = None,
    ) -> None:
        if update is not None:
            self._last_advertisement = update
            if update.battery_pct is not None:
                self._last_battery_pct = update.battery_pct
        super()._process_update(update, was_available)
        for listener in list(self._update_listeners):
            listener()

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

from .parser import D15NAdvertisement, parse

if TYPE_CHECKING:
    from habluetooth.models import BluetoothServiceInfoBleak
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class D15NPassiveCoordinator(
    PassiveBluetoothProcessorCoordinator[D15NAdvertisement | None]
):
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

    @staticmethod
    def _update_method(
        service_info: BluetoothServiceInfoBleak,
    ) -> D15NAdvertisement | None:
        """Parse one ADV; return ``None`` for non-D15N frames.

        Defined as a static method (not a free function reference) so
        tests can patch :func:`parse` via the module-level symbol and
        still see the coordinator pick up the patched implementation.
        """
        return parse(service_info)

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
        super()._process_update(update, was_available)

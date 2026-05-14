"""Tests for custom_components.minewtech_d15n.coordinator.

The coordinator is a thin wrapper around HA's
:class:`PassiveBluetoothProcessorCoordinator`. We verify:

- ``_update_method`` delegates to the parser and returns ``None`` for
  non-D15N frames.
- ``_process_update`` updates ``last_advertisement`` only for parsed
  (non-``None``) results and still calls the parent's dispatch logic.

We do *not* exercise the full HA bluetooth callback machinery here —
that is integration territory and is verified manually in Phase 7
(deploy + smoke test against the real WoMo HA instance).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from custom_components.minewtech_d15n import async_setup_entry, async_unload_entry
from custom_components.minewtech_d15n.coordinator import (
    D15NPassiveCoordinator,
    parse,
)
from custom_components.minewtech_d15n.parser import (
    AddressType,
    D15NAdvertisement,
)

from .conftest import make_service_info


@pytest.fixture
def fake_advertisement() -> D15NAdvertisement:
    """Return a representative parsed advertisement."""
    return D15NAdvertisement(
        stable_id="eddystone:00112233445566778899:abcde76b01f4",
        address="c3:00:00:4b:06:53",
        address_type=AddressType.RANDOM_STATIC,
        local_name=None,
        rssi=-45,
        battery_pct=85,
        trigger_event=None,
        trigger_counter=None,
        timestamp=0.0,
        raw=b"",
    )


class TestUpdateMethod:
    def test_delegates_to_parser_and_returns_advertisement(
        self, uid_fixture: dict[str, Any]
    ) -> None:
        info = make_service_info(service_data_hex=uid_fixture["service_data_hex"])
        # Sanity-check that the parser the coordinator wraps still works.
        assert parse(info) is not None
        result = D15NPassiveCoordinator._update_method(info)
        assert result is not None
        assert result.stable_id is not None

    def test_returns_none_for_non_d15n_advertisement(self) -> None:
        info = make_service_info(
            service_data_hex="00e800112233445566778899abcde76b01f4",
            extra_service_uuids=(),
        )
        assert D15NPassiveCoordinator._update_method(info) is None


class TestProcessUpdate:
    """Verify the override of ``_process_update`` without touching HA bluetooth."""

    def _make_bare_instance(self) -> D15NPassiveCoordinator:
        """Construct a coordinator without invoking the heavy base __init__.

        The parent ``PassiveBluetoothProcessorCoordinator.__init__`` would
        register restore callbacks against a real Home Assistant instance.
        For these unit tests we bypass it: create a bare object and
        manually populate the attributes our override touches.
        """
        coord: D15NPassiveCoordinator = D15NPassiveCoordinator.__new__(
            D15NPassiveCoordinator
        )
        coord._last_advertisement = None
        coord._processors = []
        coord._update_listeners = []
        coord.last_update_success = True
        coord.logger = MagicMock()
        return coord

    def test_caches_last_advertisement_when_update_is_truthy(
        self, fake_advertisement: D15NAdvertisement
    ) -> None:
        coord = self._make_bare_instance()
        coord._process_update(fake_advertisement, was_available=False)
        assert coord.last_advertisement is fake_advertisement

    def test_ignores_none_update_for_last_advertisement_cache(
        self, fake_advertisement: D15NAdvertisement
    ) -> None:
        coord = self._make_bare_instance()
        # Seed the cache, then push a None update through.
        coord._last_advertisement = fake_advertisement
        coord._process_update(None, was_available=True)
        # Cache must keep the previous parsed advertisement, not wipe it.
        assert coord.last_advertisement is fake_advertisement

    def test_dispatches_to_registered_processors(
        self, fake_advertisement: D15NAdvertisement
    ) -> None:
        coord = self._make_bare_instance()
        processor = MagicMock()
        coord._processors.append(processor)
        coord._process_update(fake_advertisement, was_available=True)
        processor.async_handle_update.assert_called_once_with(
            fake_advertisement, True
        )

    def test_initial_last_advertisement_is_none(self) -> None:
        coord = self._make_bare_instance()
        assert coord.last_advertisement is None


class TestEntrySetupAndUnload:
    """Verify __init__.py's async_setup_entry / async_unload_entry contract.

    Uses MagicMock for the HomeAssistant + ConfigEntry pair to avoid
    booting a full HA instance just to check the wiring.
    """

    @pytest.fixture
    def fake_entry(self) -> MagicMock:
        entry = MagicMock()
        entry.data = {"address": "c3:00:00:4b:06:53"}
        return entry

    @pytest.fixture
    def fake_hass(self) -> MagicMock:
        hass = MagicMock()
        hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)
        hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
        return hass

    @pytest.mark.asyncio
    async def test_async_setup_entry_creates_coordinator_and_starts_it(
        self,
        fake_hass: MagicMock,
        fake_entry: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Patch the coordinator class so we don't touch HA's bluetooth init.
        fake_coordinator = MagicMock()
        fake_coordinator.async_start.return_value = MagicMock()
        monkeypatch.setattr(
            "custom_components.minewtech_d15n.coordinator.D15NPassiveCoordinator",
            lambda hass, addr: fake_coordinator,
        )

        ok = await async_setup_entry(fake_hass, fake_entry)
        assert ok is True
        assert fake_entry.runtime_data is fake_coordinator
        fake_coordinator.async_start.assert_called_once_with()
        fake_entry.async_on_unload.assert_called_once_with(
            fake_coordinator.async_start.return_value
        )
        fake_hass.config_entries.async_forward_entry_setups.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_unload_entry_delegates_to_platform_unload(
        self, fake_hass: MagicMock, fake_entry: MagicMock
    ) -> None:
        ok = await async_unload_entry(fake_hass, fake_entry)
        assert ok is True
        fake_hass.config_entries.async_unload_platforms.assert_called_once()

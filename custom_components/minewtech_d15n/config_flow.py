"""Config flow for the Minewtech D15N integration.

UI-only setup with two entry points:

- :meth:`async_step_bluetooth` is invoked automatically when HA's
  bluetooth integration sees an advertisement that matches the
  ``service_uuid`` filter from ``manifest.json``. The user just sees a
  discovery card and confirms.
- :meth:`async_step_user` is the manual fallback. The form lists every
  D15N currently in range and lets the user pick one. If the chosen
  beacon carries no stable identifier (no iBeacon, no Eddystone-UID,
  and its address is not RANDOM_STATIC), the user is forwarded to
  :meth:`async_step_label` to supply a free-text label, which produces
  a ``manual:<sha256>`` stable-id per PLAN.md §10.2. If no beacon at
  all is discoverable the flow aborts with ``no_devices_found``.

Both entry points compute the same :func:`derive_stable_id` cascade as
the parser, set the result as ``unique_id``, and abort with the
``no_stable_id`` translation key when no usable identifier can be
extracted. Duplicate entries are guarded by
``_abort_if_unique_id_configured``.

The options flow exposes two presence thresholds:

- ``max_age_seconds`` (30..3600, default 300): inactivity window after
  which ``device_tracker`` switches to ``not_home``.
- ``min_rssi`` (-120..-40 dBm, default -90): minimum signal strength
  required for ``home``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.components.bluetooth import async_discovered_service_info
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)

from .const import (
    APPLE_MANUFACTURER_ID,
    CONF_ADDRESS,
    CONF_ADDRESS_TYPE,
    CONF_MAX_AGE_SECONDS,
    CONF_MIN_RSSI,
    CONF_STABLE_ID,
    DEFAULT_MAX_AGE_SECONDS,
    DEFAULT_MIN_RSSI,
    DOMAIN,
    EDDYSTONE_FRAME_TYPE_UID,
    MAX_MAX_AGE_SECONDS,
    MAX_MIN_RSSI,
    MIN_MAX_AGE_SECONDS,
    MIN_MIN_RSSI,
    SERVICE_UUID_EDDYSTONE,
)
from .parser import (
    classify_address,
    derive_manual_stable_id,
    derive_stable_id,
    is_d15n,
)

if TYPE_CHECKING:
    from habluetooth.models import BluetoothServiceInfoBleak


def _entry_title(stable_id: str, address: str) -> str:
    """Build a user-friendly title for the config entry.

    Stable-id is technical; the title is shown in the device list. We use
    the address as the primary label because it is short and recognisable
    on the BLE side; the stable-id is recorded in entry.data for
    diagnostics.
    """
    return f"Minewtech D15N ({address})"


def _normalise_address(address: str) -> str:
    """Return a canonical address representation for comparisons/storage."""
    return address.strip().lower()


def _stable_id_tier(info: BluetoothServiceInfoBleak) -> int:
    """Rank an advertisement by the stable-id tier it can produce.

    Used by :meth:`MinewtechD15NConfigFlow._async_discoverable_beacons`
    to pick the most useful snapshot when HA's discovery cache holds
    several frames for the same beacon (e.g. one TLM and one UID/iBeacon).
    Higher is better; ``0`` means the cascade falls through entirely.
    """
    if APPLE_MANUFACTURER_ID in info.manufacturer_data:
        return 3
    eddystone = info.service_data.get(SERVICE_UUID_EDDYSTONE)
    if eddystone and eddystone[:1] == bytes([EDDYSTONE_FRAME_TYPE_UID]):
        return 2
    if derive_stable_id(info) is not None:
        return 1
    return 0


class MinewtechD15NConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a UI-driven setup for the Minewtech D15N integration."""

    VERSION = 1

    def __init__(self) -> None:
        # Pending discovery — populated by async_step_bluetooth before the
        # user confirms in the discovery card, so we can use it inside
        # async_step_bluetooth_confirm to build the final entry.
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._stable_id: str | None = None
        # Carried over from async_step_user when the user picks a beacon
        # that has no payload-level identifier; async_step_label uses the
        # address so the resulting entry can still be set up.
        self._pending_label_info: BluetoothServiceInfoBleak | None = None

    @staticmethod
    def async_get_options_flow(_config_entry: ConfigEntry) -> OptionsFlow:
        return MinewtechD15NOptionsFlow()

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle an HA bluetooth-integration auto-discovery."""
        address = _normalise_address(discovery_info.address)
        if not is_d15n(discovery_info):
            return self.async_abort(reason="not_d15n")
        if self._has_configured_address(address):
            return self.async_abort(reason="already_configured")

        stable_id = derive_stable_id(discovery_info)
        if stable_id is None:
            return self.async_abort(reason="no_stable_id")

        await self.async_set_unique_id(stable_id)
        # No `updates=` here: we are address-pinned (the coordinator listens
        # on the MAC from async_setup_entry). Silently updating entry.data
        # without reloading the coordinator would cause the two to diverge.
        # If the beacon's MAC ever changes the user creates a new entry.
        self._abort_if_unique_id_configured()

        self._discovery_info = discovery_info
        self._stable_id = stable_id
        self.context["title_placeholders"] = {
            "address": address,
        }
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirmation card shown after a successful auto-discovery."""
        assert self._discovery_info is not None
        assert self._stable_id is not None

        if user_input is not None:
            return self._create_entry(
                stable_id=self._stable_id,
                address=_normalise_address(self._discovery_info.address),
            )

        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={
                "address": self._discovery_info.address,
                "stable_id": self._stable_id,
            },
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manual entry: pick a discovered beacon from a dropdown.

        If no D15N beacons are currently visible, the flow aborts with the
        ``no_devices_found`` translation key. If a beacon is in range but
        carries no payload-level identifier (Eddystone-UID / iBeacon both
        missing, address is RANDOM_PRIVATE etc.), the user is forwarded to
        :meth:`async_step_label` which collects a free-text label per
        PLAN.md §10.2 — the chosen beacon's address is carried along so
        the resulting entry can still anchor the address-pinned coordinator.
        """
        discovered = self._async_discoverable_beacons()

        if not discovered:
            return self.async_abort(reason="no_devices_found")

        if user_input is not None:
            chosen_address = user_input[CONF_ADDRESS]
            info = discovered.get(chosen_address)
            if info is None:
                return self.async_abort(reason="device_lost")
            if self._has_configured_address(info.address):
                return self.async_abort(reason="already_configured")
            stable_id = derive_stable_id(info)
            if stable_id is None:
                # Cascade fell through entirely — defer the unique-id to a
                # user-supplied label, but remember which beacon was picked
                # so we can still pin the coordinator to its address.
                self._pending_label_info = info
                return await self.async_step_label()
            await self.async_set_unique_id(stable_id)
            self._abort_if_unique_id_configured()
            return self._create_entry(stable_id=stable_id, address=info.address)

        return self.async_show_form(
            step_id="user",
            data_schema=self._user_schema(discovered),
        )

    async def async_step_label(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Free-text fallback used when no stable-id can be derived.

        Only reachable as a side branch from :meth:`async_step_user`, which
        seeds ``self._pending_label_info`` with the beacon the user picked.
        That beacon's address anchors the address-pinned coordinator; the
        label produces the ``manual:<sha256>`` unique-id per PLAN.md §10.2.

        The label is normalised (``strip().casefold()``) before hashing so
        ``"  Mama "`` and ``"mama"`` collide deterministically. Collision
        against an existing entry is rejected with a ``label_in_use``
        error pointing the user at a more specific name.
        """
        if self._pending_label_info is None:
            # Defensive: this step has no standalone entry point — if it
            # is ever reached without a pre-seeded beacon, abort cleanly
            # rather than creating an entry that the coordinator cannot
            # set up.
            return self.async_abort(reason="no_devices_found")

        info = self._pending_label_info
        schema = vol.Schema({vol.Required("label"): str})

        if user_input is not None:
            label = user_input["label"]
            if not label.strip():
                return self.async_show_form(
                    step_id="label",
                    data_schema=schema,
                    errors={"label": "label_empty"},
                    description_placeholders={"address": info.address},
                )
            stable_id = derive_manual_stable_id(label)
            if self._has_unique_id(stable_id):
                return self.async_show_form(
                    step_id="label",
                    data_schema=schema,
                    errors={"label": "label_in_use"},
                )
            await self.async_set_unique_id(stable_id)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=label.strip(),
                data={
                    CONF_STABLE_ID: stable_id,
                    CONF_ADDRESS: _normalise_address(info.address),
                    CONF_ADDRESS_TYPE: classify_address(info.address).value,
                },
                options={
                    CONF_MAX_AGE_SECONDS: DEFAULT_MAX_AGE_SECONDS,
                    CONF_MIN_RSSI: DEFAULT_MIN_RSSI,
                },
            )

        return self.async_show_form(
            step_id="label",
            data_schema=schema,
            description_placeholders={"address": info.address},
        )

    def _create_entry(self, *, stable_id: str, address: str) -> ConfigFlowResult:
        """Persist a new entry with the diagnostic snapshot in entry.data.

        ``entry.data`` is treated as a snapshot of what we knew at setup
        time — the authoritative runtime address lives on the
        coordinator. ``options`` holds the user-tunable
        ``max_age_seconds`` with the default seeded so the device_tracker
        works out of the box.
        """
        address = _normalise_address(address)
        return self.async_create_entry(
            title=_entry_title(stable_id, address),
            data={
                CONF_STABLE_ID: stable_id,
                CONF_ADDRESS: address,
                CONF_ADDRESS_TYPE: classify_address(address).value,
            },
            options={
                CONF_MAX_AGE_SECONDS: DEFAULT_MAX_AGE_SECONDS,
                CONF_MIN_RSSI: DEFAULT_MIN_RSSI,
            },
        )

    def _async_discoverable_beacons(
        self,
    ) -> dict[str, BluetoothServiceInfoBleak]:
        """Collect every currently-visible D15N beacon keyed by address.

        Filters HA's ``async_discovered_service_info`` view through our
        ``is_d15n`` defense-in-depth check, then collapses multiple
        snapshots of the same address to a *single* preferred frame:

        - If at least one snapshot yields a payload-level stable-id
          (Tier 1 iBeacon or Tier 2 Eddystone-UID), that snapshot wins.
        - Otherwise the first remaining snapshot is kept; the dropdown
          entry will still surface, but the user is forwarded to
          :meth:`async_step_label` on selection.

        Already-configured beacons (unique-id matches an existing entry)
        are dropped from the dropdown so the user cannot re-add them.
        """
        configured_ids = {
            entry.unique_id for entry in self._async_current_entries(include_ignore=False)
        }
        configured_addresses = {
            _normalise_address(address)
            for entry in self._async_current_entries(include_ignore=False)
            if (address := entry.data.get(CONF_ADDRESS))
        }
        candidates: dict[str, BluetoothServiceInfoBleak] = {}
        for info in async_discovered_service_info(self.hass):
            if not is_d15n(info):
                continue
            normalised_address = _normalise_address(info.address)
            current_best = candidates.get(normalised_address)
            if current_best is None:
                candidates[normalised_address] = info
                continue
            # Replace only when this snapshot reaches a higher stable-id
            # tier than what we already have — otherwise stay with the
            # earlier frame so the dropdown order is stable.
            if _stable_id_tier(info) > _stable_id_tier(current_best):
                candidates[normalised_address] = info

        result: dict[str, BluetoothServiceInfoBleak] = {}
        for address, info in candidates.items():
            if _normalise_address(address) in configured_addresses:
                continue
            stable_id = derive_stable_id(info)
            if stable_id is not None and stable_id in configured_ids:
                continue
            result[address] = info
        return result

    @staticmethod
    def _user_schema(
        discovered: dict[str, BluetoothServiceInfoBleak],
    ) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(CONF_ADDRESS): vol.In(
                    {addr: f"{addr} (RSSI {info.rssi})" for addr, info in discovered.items()}
                )
            }
        )

    def _has_unique_id(self, stable_id: str) -> bool:
        for entry in self._async_current_entries(include_ignore=True):
            if entry.unique_id == stable_id:
                return True
        return False

    def _has_configured_address(self, address: str) -> bool:
        normalised = _normalise_address(address)
        for entry in self._async_current_entries(include_ignore=False):
            existing = entry.data.get(CONF_ADDRESS)
            if isinstance(existing, str) and _normalise_address(existing) == normalised:
                return True
        return False


class MinewtechD15NOptionsFlow(OptionsFlow):
    """Lets the user tune the ``device_tracker`` presence thresholds."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_age = self.config_entry.options.get(CONF_MAX_AGE_SECONDS, DEFAULT_MAX_AGE_SECONDS)
        current_rssi = self.config_entry.options.get(CONF_MIN_RSSI, DEFAULT_MIN_RSSI)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MAX_AGE_SECONDS, default=current_age): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_MAX_AGE_SECONDS, max=MAX_MAX_AGE_SECONDS),
                    ),
                    vol.Required(CONF_MIN_RSSI, default=current_rssi): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_MIN_RSSI, max=MAX_MIN_RSSI),
                    ),
                }
            ),
        )


__all__ = ["MinewtechD15NConfigFlow", "MinewtechD15NOptionsFlow"]

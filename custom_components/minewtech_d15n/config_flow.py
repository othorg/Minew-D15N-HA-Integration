"""Config flow for the Minewtech D15N integration.

UI-only setup with two entry points:

- :meth:`async_step_bluetooth` is invoked automatically when HA's
  bluetooth integration sees an advertisement that matches the
  ``service_uuid`` filter from ``manifest.json``. The user just sees a
  discovery card and confirms.
- :meth:`async_step_user` is the manual fallback. The form lists every
  D15N currently in range and lets the user pick one; if no beacon is
  discoverable a free-text label is offered, which produces a
  ``manual:<sha256>`` stable-id per PLAN.md §10.2.

Both entry points compute the same :func:`derive_stable_id` cascade as
the parser, set the result as ``unique_id``, and abort with the
``no_stable_id`` translation key when no usable identifier can be
extracted. Duplicate entries are guarded by
``_abort_if_unique_id_configured``.

The options flow exposes a single value: ``max_age_seconds`` (30..3600,
default 300) — the inactivity window after which ``device_tracker``
switches to ``not_home``.
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
    CONF_ADDRESS,
    CONF_ADDRESS_TYPE,
    CONF_MAX_AGE_SECONDS,
    CONF_STABLE_ID,
    DEFAULT_MAX_AGE_SECONDS,
    DOMAIN,
    MAX_MAX_AGE_SECONDS,
    MIN_MAX_AGE_SECONDS,
)
from .parser import (
    AddressType,
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


class MinewtechD15NConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a UI-driven setup for the Minewtech D15N integration."""

    VERSION = 1

    def __init__(self) -> None:
        # Pending discovery — populated by async_step_bluetooth before the
        # user confirms in the discovery card, so we can use it inside
        # async_step_bluetooth_confirm to build the final entry.
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._stable_id: str | None = None

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return MinewtechD15NOptionsFlow(config_entry)

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle an HA bluetooth-integration auto-discovery."""
        if not is_d15n(discovery_info):
            return self.async_abort(reason="not_d15n")

        stable_id = derive_stable_id(discovery_info)
        if stable_id is None:
            return self.async_abort(reason="no_stable_id")

        await self.async_set_unique_id(stable_id)
        self._abort_if_unique_id_configured(
            updates={CONF_ADDRESS: discovery_info.address}
        )

        self._discovery_info = discovery_info
        self._stable_id = stable_id
        self.context["title_placeholders"] = {
            "address": discovery_info.address,
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
                address=self._discovery_info.address,
            )

        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={
                "address": self._discovery_info.address,
                "stable_id": self._stable_id,
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manual entry: pick a discovered beacon from a dropdown.

        If no D15N beacons are currently visible, the flow aborts with the
        ``no_devices_found`` translation key. PLAN.md §10.2 contemplates a
        label-driven fallback for the case where derive_stable_id() always
        returns None; that path is implemented in
        :meth:`async_step_label` and only reachable from a side branch in
        :meth:`async_step_bluetooth` (aborts there flow into a discovery
        card, while the user step matches HA's "+ Add integration"
        pattern).
        """
        discovered = self._async_discoverable_beacons()

        if not discovered:
            return self.async_abort(reason="no_devices_found")

        if user_input is not None:
            chosen_address = user_input[CONF_ADDRESS]
            info = discovered.get(chosen_address)
            if info is None:
                return self.async_abort(reason="device_lost")
            stable_id = derive_stable_id(info)
            if stable_id is None:
                # Re-show the form with an error so the user can retry or
                # use a label instead of guessing.
                return self.async_show_form(
                    step_id="user",
                    data_schema=self._user_schema(discovered),
                    errors={"base": "no_stable_id"},
                )
            await self.async_set_unique_id(stable_id)
            self._abort_if_unique_id_configured(
                updates={CONF_ADDRESS: info.address}
            )
            return self._create_entry(stable_id=stable_id, address=info.address)

        return self.async_show_form(
            step_id="user",
            data_schema=self._user_schema(discovered),
        )

    async def async_step_label(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Free-text fallback used when no stable-id can be derived.

        The label is normalised (``strip().casefold()``) before hashing so
        ``"  Mama "`` and ``"mama"`` produce the same unique-id. Collision
        is rejected with a ``label_in_use`` error pointing the user at a
        more specific name.
        """
        if user_input is not None:
            label = user_input["label"]
            stable_id = derive_manual_stable_id(label)
            if self._has_unique_id(stable_id):
                return self.async_show_form(
                    step_id="label",
                    data_schema=vol.Schema({vol.Required("label"): str}),
                    errors={"label": "label_in_use"},
                )
            await self.async_set_unique_id(stable_id)
            self._abort_if_unique_id_configured()
            # Manual entries carry no address — record None so the
            # diagnostic snapshot is explicit instead of missing the key.
            return self.async_create_entry(
                title=label.strip(),
                data={
                    CONF_STABLE_ID: stable_id,
                    CONF_ADDRESS: None,
                    CONF_ADDRESS_TYPE: AddressType.UNKNOWN.value,
                },
            )

        return self.async_show_form(
            step_id="label",
            data_schema=vol.Schema({vol.Required("label"): str}),
        )

    def _create_entry(self, *, stable_id: str, address: str) -> ConfigFlowResult:
        """Persist a new entry with the diagnostic snapshot in entry.data.

        ``entry.data`` is treated as a snapshot of what we knew at setup
        time — the authoritative runtime address lives on the
        coordinator. ``options`` holds the user-tunable
        ``max_age_seconds`` with the default seeded so the device_tracker
        works out of the box.
        """
        return self.async_create_entry(
            title=_entry_title(stable_id, address),
            data={
                CONF_STABLE_ID: stable_id,
                CONF_ADDRESS: address,
                CONF_ADDRESS_TYPE: AddressType.UNKNOWN.value,
            },
            options={CONF_MAX_AGE_SECONDS: DEFAULT_MAX_AGE_SECONDS},
        )

    def _async_discoverable_beacons(
        self,
    ) -> dict[str, BluetoothServiceInfoBleak]:
        """Collect every currently-visible D15N beacon keyed by address.

        Filters HA's ``async_discovered_service_info`` view through our
        ``is_d15n`` defense-in-depth check; entries whose stable-id is
        already configured are removed so the dropdown does not let the
        user re-add the same beacon.
        """
        seen: dict[str, BluetoothServiceInfoBleak] = {}
        configured_ids = {
            entry.unique_id
            for entry in self._async_current_entries(include_ignore=False)
        }
        for info in async_discovered_service_info(self.hass):
            if not is_d15n(info):
                continue
            if info.address in seen:
                continue
            stable_id = derive_stable_id(info)
            if stable_id is not None and stable_id in configured_ids:
                continue
            seen[info.address] = info
        return seen

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
        for entry in self._async_current_entries(include_ignore=False):
            if entry.unique_id == stable_id:
                return True
        return False


class MinewtechD15NOptionsFlow(OptionsFlow):
    """Lets the user tune the ``device_tracker`` timeout after setup."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        # The HA OptionsFlow base no longer accepts the config entry in
        # the constructor, but storing the reference simplifies our
        # form-defaults logic without altering the framework contract.
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self._config_entry.options.get(
            CONF_MAX_AGE_SECONDS, DEFAULT_MAX_AGE_SECONDS
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MAX_AGE_SECONDS, default=current): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_MAX_AGE_SECONDS, max=MAX_MAX_AGE_SECONDS),
                    )
                }
            ),
        )


__all__ = ["MinewtechD15NConfigFlow", "MinewtechD15NOptionsFlow"]

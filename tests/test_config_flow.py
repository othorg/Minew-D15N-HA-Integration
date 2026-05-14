"""End-to-end tests for custom_components.minewtech_d15n.config_flow.

Uses the ``hass`` fixture from pytest-homeassistant-custom-component and
``MockConfigEntry`` to drive the real ConfigFlow machinery rather than
mocking it out. Bluetooth discovery is exercised through a patched
``async_discovered_service_info`` so we can inject any number of
fixture-derived advertisements without touching the underlying scanner.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from custom_components.minewtech_d15n.config_flow import MinewtechD15NConfigFlow
from custom_components.minewtech_d15n.const import (
    CONF_ADDRESS,
    CONF_ADDRESS_TYPE,
    CONF_MAX_AGE_SECONDS,
    CONF_MIN_RSSI,
    CONF_STABLE_ID,
    DEFAULT_MAX_AGE_SECONDS,
    DEFAULT_MIN_RSSI,
    DOMAIN,
)
from custom_components.minewtech_d15n.parser import derive_manual_stable_id
from homeassistant.config_entries import SOURCE_BLUETOOTH, SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import make_service_info


def _make_service_info_with_address(
    address: str,
    hex_payload: str = "00e800112233445566778899abcde76b01f4",
) -> Any:
    """Build a discovery-shaped service info; address parameterised."""
    return make_service_info(service_data_hex=hex_payload, address=address)


class TestBluetoothDiscoveryFlow:
    @pytest.mark.asyncio
    async def test_happy_path(self, hass: Any, uid_fixture: dict[str, Any]) -> None:
        info = _make_service_info_with_address("c3:00:00:4b:06:53", uid_fixture["service_data_hex"])

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=info
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "bluetooth_confirm"

        result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input={})
        assert result["type"] == FlowResultType.CREATE_ENTRY
        ns = uid_fixture["expected"]["namespace_hex"]
        inst = uid_fixture["expected"]["instance_hex"]
        assert result["data"][CONF_STABLE_ID] == f"eddystone:{ns}:{inst}"
        assert result["data"][CONF_ADDRESS] == "c3:00:00:4b:06:53"
        assert result["data"][CONF_ADDRESS_TYPE] == "random_static"
        assert result["options"][CONF_MAX_AGE_SECONDS] == DEFAULT_MAX_AGE_SECONDS
        assert result["options"][CONF_MIN_RSSI] == DEFAULT_MIN_RSSI

    @pytest.mark.asyncio
    async def test_aborts_when_already_configured(
        self, hass: Any, uid_fixture: dict[str, Any]
    ) -> None:
        ns = uid_fixture["expected"]["namespace_hex"]
        inst = uid_fixture["expected"]["instance_hex"]
        stable_id = f"eddystone:{ns}:{inst}"
        MockConfigEntry(
            domain=DOMAIN,
            unique_id=stable_id,
            data={CONF_STABLE_ID: stable_id, CONF_ADDRESS: "c3:00:00:4b:06:53"},
        ).add_to_hass(hass)

        info = _make_service_info_with_address("c3:00:00:4b:06:53", uid_fixture["service_data_hex"])
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=info
        )
        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "already_configured"

    @pytest.mark.asyncio
    async def test_aborts_when_same_address_already_configured_with_different_id(
        self, hass: Any, uid_fixture: dict[str, Any]
    ) -> None:
        MockConfigEntry(
            domain=DOMAIN,
            unique_id="manual:deadbeefcafe",
            data={CONF_STABLE_ID: "manual:deadbeefcafe", CONF_ADDRESS: "c3:00:00:4b:06:53"},
        ).add_to_hass(hass)
        info = _make_service_info_with_address("C3:00:00:4B:06:53", uid_fixture["service_data_hex"])
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=info
        )
        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "already_configured"

    @pytest.mark.asyncio
    async def test_aborts_when_no_stable_id_derivable(self, hass: Any) -> None:
        # URL frame on an UNKNOWN address: derive_stable_id returns None.
        info = make_service_info(
            service_data_hex="10e8016d696e657700",
            address="12:34:56:78:9a:bc",  # top bits 00 -> UNKNOWN
        )
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=info
        )
        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "no_stable_id"

    @pytest.mark.asyncio
    async def test_aborts_when_not_a_d15n(self, hass: Any) -> None:
        info = make_service_info(
            service_data_hex="00e800112233445566778899abcde76b01f4",
            extra_service_uuids=(),  # strips the vendor UUID
        )
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=info
        )
        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "not_d15n"


class TestUserFlow:
    @pytest.mark.asyncio
    async def test_lists_discovered_beacons(self, hass: Any, uid_fixture: dict[str, Any]) -> None:
        info_a = _make_service_info_with_address(
            "c3:00:00:4b:06:53", uid_fixture["service_data_hex"]
        )
        info_b = _make_service_info_with_address(
            "c3:00:00:4b:06:54", uid_fixture["service_data_hex"]
        )

        with patch(
            "custom_components.minewtech_d15n.config_flow.async_discovered_service_info",
            return_value=[info_a, info_b],
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_USER}
            )
            assert result["type"] == FlowResultType.FORM
            assert result["step_id"] == "user"
            # The schema's dropdown should contain both addresses.
            schema_keys = result["data_schema"].schema[CONF_ADDRESS].container
            assert "c3:00:00:4b:06:53" in schema_keys
            assert "c3:00:00:4b:06:54" in schema_keys

    @pytest.mark.asyncio
    async def test_user_path_creates_entry(self, hass: Any, uid_fixture: dict[str, Any]) -> None:
        info = _make_service_info_with_address("c3:00:00:4b:06:53", uid_fixture["service_data_hex"])
        with patch(
            "custom_components.minewtech_d15n.config_flow.async_discovered_service_info",
            return_value=[info],
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_USER}
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], user_input={CONF_ADDRESS: "c3:00:00:4b:06:53"}
            )
        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_ADDRESS] == "c3:00:00:4b:06:53"

    @pytest.mark.asyncio
    async def test_user_path_aborts_when_no_beacons_visible(self, hass: Any) -> None:
        with patch(
            "custom_components.minewtech_d15n.config_flow.async_discovered_service_info",
            return_value=[],
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_USER}
            )
        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "no_devices_found"

    @pytest.mark.asyncio
    async def test_user_path_hides_already_configured_entries(
        self, hass: Any, uid_fixture: dict[str, Any]
    ) -> None:
        ns = uid_fixture["expected"]["namespace_hex"]
        inst = uid_fixture["expected"]["instance_hex"]
        stable_id = f"eddystone:{ns}:{inst}"
        MockConfigEntry(
            domain=DOMAIN,
            unique_id=stable_id,
            data={CONF_STABLE_ID: stable_id, CONF_ADDRESS: "c3:00:00:4b:06:53"},
        ).add_to_hass(hass)

        info = _make_service_info_with_address("c3:00:00:4b:06:53", uid_fixture["service_data_hex"])
        with patch(
            "custom_components.minewtech_d15n.config_flow.async_discovered_service_info",
            return_value=[info],
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_USER}
            )
        # Only the already-known beacon is in range → dropdown is empty →
        # the flow aborts the same way as if no beacon was visible.
        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "no_devices_found"


class TestLabelFallback:
    """User-flow → label-step branch (PLAN.md §10.2 fallback A1)."""

    @pytest.mark.asyncio
    async def test_user_picks_beacon_without_stable_id_falls_through_to_label(
        self, hass: Any
    ) -> None:
        # URL frame, UNKNOWN address → derive_stable_id returns None.
        info = make_service_info(
            service_data_hex="10e8016d696e657700",
            address="12:34:56:78:9a:bc",
        )
        with patch(
            "custom_components.minewtech_d15n.config_flow.async_discovered_service_info",
            return_value=[info],
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_USER}
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], user_input={CONF_ADDRESS: "12:34:56:78:9a:bc"}
            )
            assert result["type"] == FlowResultType.FORM
            assert result["step_id"] == "label"
            # The form was reached without the user explicitly asking for
            # a label — confirm the description still includes the
            # chosen beacon's address so the user knows what they are naming.
            assert result["description_placeholders"]["address"] == ("12:34:56:78:9a:bc")

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], user_input={"label": "Keychain Mama"}
            )
        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_STABLE_ID].startswith("manual:")
        assert result["data"][CONF_ADDRESS] == "12:34:56:78:9a:bc"
        assert result["data"][CONF_ADDRESS_TYPE] == "unknown"
        assert result["options"][CONF_MAX_AGE_SECONDS] == DEFAULT_MAX_AGE_SECONDS
        assert result["options"][CONF_MIN_RSSI] == DEFAULT_MIN_RSSI

    @pytest.mark.asyncio
    async def test_label_in_use_rejects_collision(self, hass: Any) -> None:
        # Pre-existing manual entry that the second flow will collide with.
        existing_id = derive_manual_stable_id("keychain mama")
        MockConfigEntry(
            domain=DOMAIN,
            unique_id=existing_id,
            data={CONF_STABLE_ID: existing_id, CONF_ADDRESS: "12:34:56:78:9a:bc"},
        ).add_to_hass(hass)

        info = make_service_info(
            service_data_hex="10e8016d696e657700",
            address="aa:11:22:33:44:55",  # different address, same label
        )
        with patch(
            "custom_components.minewtech_d15n.config_flow.async_discovered_service_info",
            return_value=[info],
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_USER}
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], user_input={CONF_ADDRESS: "aa:11:22:33:44:55"}
            )
            assert result["step_id"] == "label"

            # Submitting the same label (case/whitespace differs but
            # normalises to the same hash) re-shows the form with error.
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], user_input={"label": "  Keychain Mama "}
            )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "label"
        assert result["errors"] == {"label": "label_in_use"}

    @pytest.mark.asyncio
    async def test_label_rejects_whitespace_only_value(self, hass: Any) -> None:
        info = make_service_info(
            service_data_hex="10e8016d696e657700",
            address="12:34:56:78:9a:bc",
        )
        with patch(
            "custom_components.minewtech_d15n.config_flow.async_discovered_service_info",
            return_value=[info],
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_USER}
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], user_input={CONF_ADDRESS: "12:34:56:78:9a:bc"}
            )
            assert result["step_id"] == "label"
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], user_input={"label": "   "}
            )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "label"
        assert result["errors"] == {"label": "label_empty"}

    @pytest.mark.asyncio
    async def test_label_step_aborts_when_invoked_standalone(self, hass: Any) -> None:
        """Defensive: label-step has no standalone trigger and must abort
        if HA ever routes there without async_step_user seeding the info.
        """
        flow = MinewtechD15NConfigFlow()
        flow.hass = hass
        result = await flow.async_step_label()
        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "no_devices_found"


class TestDiscoverableBeaconsPriority:
    """Frame priorisation when multiple snapshots exist for the same address."""

    @pytest.mark.asyncio
    async def test_user_dropdown_prefers_uid_over_tlm_frame(
        self, hass: Any, uid_fixture: dict[str, Any], tlm_fixture: dict[str, Any]
    ) -> None:
        # Two snapshots of the same beacon: TLM frame seen first (no
        # payload id), then the UID frame (eddystone:… tier 2). The
        # picker must keep the UID one so the user does not get
        # forwarded to async_step_label unnecessarily.
        addr = "c3:00:00:4b:06:53"
        tlm_info = make_service_info(service_data_hex=tlm_fixture["service_data_hex"], address=addr)
        uid_info = make_service_info(service_data_hex=uid_fixture["service_data_hex"], address=addr)

        with patch(
            "custom_components.minewtech_d15n.config_flow.async_discovered_service_info",
            return_value=[tlm_info, uid_info],
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_USER}
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], user_input={CONF_ADDRESS: addr}
            )

        # If the picker had kept the TLM frame, the cascade would have
        # fallen through to tier 4 (ble:<addr>) which is still a valid
        # stable_id for RANDOM_STATIC c3:… — so we instead assert on the
        # *eddystone:* prefix to prove the UID frame was used.
        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_STABLE_ID].startswith("eddystone:")

    @pytest.mark.asyncio
    async def test_user_dropdown_lists_partially_configured_beacons(
        self, hass: Any, uid_fixture: dict[str, Any]
    ) -> None:
        """Two beacons in range, one of them already set up — only the
        unconfigured one should appear in the dropdown.
        """
        ns = uid_fixture["expected"]["namespace_hex"]
        inst = uid_fixture["expected"]["instance_hex"]
        configured_id = f"eddystone:{ns}:{inst}"
        MockConfigEntry(
            domain=DOMAIN,
            unique_id=configured_id,
            data={CONF_STABLE_ID: configured_id, CONF_ADDRESS: "c3:00:00:4b:06:53"},
        ).add_to_hass(hass)

        info_configured = make_service_info(
            service_data_hex=uid_fixture["service_data_hex"],
            address="c3:00:00:4b:06:53",
        )
        # Second beacon uses a different namespace so its stable_id differs.
        info_new = make_service_info(
            service_data_hex="00e8aabbccddeeff0011223344556677",
            address="c3:00:00:4b:06:54",
        )
        with patch(
            "custom_components.minewtech_d15n.config_flow.async_discovered_service_info",
            return_value=[info_configured, info_new],
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_USER}
            )
            schema_keys = result["data_schema"].schema[CONF_ADDRESS].container
            assert "c3:00:00:4b:06:53" not in schema_keys
            assert "c3:00:00:4b:06:54" in schema_keys

    @pytest.mark.asyncio
    async def test_user_dropdown_hides_beacon_when_address_already_configured(
        self, hass: Any, uid_fixture: dict[str, Any]
    ) -> None:
        MockConfigEntry(
            domain=DOMAIN,
            unique_id="manual:deadbeefcafe",
            data={CONF_STABLE_ID: "manual:deadbeefcafe", CONF_ADDRESS: "c3:00:00:4b:06:53"},
        ).add_to_hass(hass)
        info = make_service_info(
            service_data_hex=uid_fixture["service_data_hex"],
            address="C3:00:00:4B:06:53",
        )
        with patch(
            "custom_components.minewtech_d15n.config_flow.async_discovered_service_info",
            return_value=[info],
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_USER}
            )
        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "no_devices_found"


class TestOptionsFlow:
    @pytest.mark.asyncio
    async def test_writes_max_age_seconds(self, hass: Any) -> None:
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id="eddystone:00112233445566778899:abcde76b01f4",
            data={CONF_ADDRESS: "c3:00:00:4b:06:53"},
            options={
                CONF_MAX_AGE_SECONDS: DEFAULT_MAX_AGE_SECONDS,
                CONF_MIN_RSSI: DEFAULT_MIN_RSSI,
            },
        )
        entry.add_to_hass(hass)

        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "init"

        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input={CONF_MAX_AGE_SECONDS: 60, CONF_MIN_RSSI: -75}
        )
        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert entry.options[CONF_MAX_AGE_SECONDS] == 60
        assert entry.options[CONF_MIN_RSSI] == -75

    @pytest.mark.asyncio
    async def test_rejects_out_of_range_value(self, hass: Any) -> None:
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id="eddystone:00112233445566778899:abcde76b01f4",
            data={CONF_ADDRESS: "c3:00:00:4b:06:53"},
        )
        entry.add_to_hass(hass)

        result = await hass.config_entries.options.async_init(entry.entry_id)
        # Below the minimum (30) — voluptuous rejects the value; HA wraps
        # the MultipleInvalid in InvalidData before re-raising it from
        # async_configure.
        with pytest.raises(InvalidData):
            await hass.config_entries.options.async_configure(
                result["flow_id"], user_input={CONF_MAX_AGE_SECONDS: 5, CONF_MIN_RSSI: -80}
            )

    @pytest.mark.asyncio
    async def test_rejects_out_of_range_rssi(self, hass: Any) -> None:
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id="eddystone:00112233445566778899:abcde76b01f4",
            data={CONF_ADDRESS: "c3:00:00:4b:06:53"},
            options={
                CONF_MAX_AGE_SECONDS: DEFAULT_MAX_AGE_SECONDS,
                CONF_MIN_RSSI: DEFAULT_MIN_RSSI,
            },
        )
        entry.add_to_hass(hass)

        result = await hass.config_entries.options.async_init(entry.entry_id)
        with pytest.raises(InvalidData):
            await hass.config_entries.options.async_configure(
                result["flow_id"], user_input={CONF_MAX_AGE_SECONDS: 300, CONF_MIN_RSSI: -20}
            )

    @pytest.mark.asyncio
    async def test_accepts_lower_rssi_boundary(self, hass: Any) -> None:
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id="eddystone:00112233445566778899:abcde76b01f4",
            data={CONF_ADDRESS: "c3:00:00:4b:06:53"},
            options={
                CONF_MAX_AGE_SECONDS: DEFAULT_MAX_AGE_SECONDS,
                CONF_MIN_RSSI: DEFAULT_MIN_RSSI,
            },
        )
        entry.add_to_hass(hass)

        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input={CONF_MAX_AGE_SECONDS: 300, CONF_MIN_RSSI: -120}
        )
        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert entry.options[CONF_MIN_RSSI] == -120

    @pytest.mark.asyncio
    async def test_rejects_below_lower_rssi_boundary(self, hass: Any) -> None:
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id="eddystone:00112233445566778899:abcde76b01f4",
            data={CONF_ADDRESS: "c3:00:00:4b:06:53"},
            options={
                CONF_MAX_AGE_SECONDS: DEFAULT_MAX_AGE_SECONDS,
                CONF_MIN_RSSI: DEFAULT_MIN_RSSI,
            },
        )
        entry.add_to_hass(hass)

        result = await hass.config_entries.options.async_init(entry.entry_id)
        with pytest.raises(InvalidData):
            await hass.config_entries.options.async_configure(
                result["flow_id"], user_input={CONF_MAX_AGE_SECONDS: 300, CONF_MIN_RSSI: -121}
            )

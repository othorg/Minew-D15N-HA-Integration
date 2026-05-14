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
from custom_components.minewtech_d15n.const import (
    CONF_ADDRESS,
    CONF_MAX_AGE_SECONDS,
    CONF_STABLE_ID,
    DEFAULT_MAX_AGE_SECONDS,
    DOMAIN,
)
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
        info = _make_service_info_with_address(
            "c3:00:00:4b:06:53", uid_fixture["service_data_hex"]
        )

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=info
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "bluetooth_confirm"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={}
        )
        assert result["type"] == FlowResultType.CREATE_ENTRY
        ns = uid_fixture["expected"]["namespace_hex"]
        inst = uid_fixture["expected"]["instance_hex"]
        assert result["data"][CONF_STABLE_ID] == f"eddystone:{ns}:{inst}"
        assert result["data"][CONF_ADDRESS] == "c3:00:00:4b:06:53"
        assert result["options"][CONF_MAX_AGE_SECONDS] == DEFAULT_MAX_AGE_SECONDS

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

        info = _make_service_info_with_address(
            "c3:00:00:4b:06:53", uid_fixture["service_data_hex"]
        )
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
    async def test_lists_discovered_beacons(
        self, hass: Any, uid_fixture: dict[str, Any]
    ) -> None:
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
    async def test_user_path_creates_entry(
        self, hass: Any, uid_fixture: dict[str, Any]
    ) -> None:
        info = _make_service_info_with_address(
            "c3:00:00:4b:06:53", uid_fixture["service_data_hex"]
        )
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

        info = _make_service_info_with_address(
            "c3:00:00:4b:06:53", uid_fixture["service_data_hex"]
        )
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


class TestOptionsFlow:
    @pytest.mark.asyncio
    async def test_writes_max_age_seconds(self, hass: Any) -> None:
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id="eddystone:00112233445566778899:abcde76b01f4",
            data={CONF_ADDRESS: "c3:00:00:4b:06:53"},
            options={CONF_MAX_AGE_SECONDS: DEFAULT_MAX_AGE_SECONDS},
        )
        entry.add_to_hass(hass)

        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "init"

        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input={CONF_MAX_AGE_SECONDS: 60}
        )
        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert entry.options[CONF_MAX_AGE_SECONDS] == 60

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
                result["flow_id"], user_input={CONF_MAX_AGE_SECONDS: 5}
            )

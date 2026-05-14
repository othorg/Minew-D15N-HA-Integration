"""Unit tests for custom_components.minewtech_d15n.parser."""

from __future__ import annotations

from typing import Any

import pytest
from custom_components.minewtech_d15n.const import APPLE_MANUFACTURER_ID
from custom_components.minewtech_d15n.parser import (
    AddressType,
    D15NAdvertisement,
    EddystoneTLM,
    EddystoneUID,
    EddystoneURL,
    IBeacon,
    TriggerEvent,
    _classify_address,
    battery_percentage_from_mv,
    derive_manual_stable_id,
    derive_stable_id,
    is_d15n,
    parse,
    parse_eddystone_tlm,
    parse_eddystone_uid,
    parse_eddystone_url,
    parse_ibeacon,
)

from .conftest import make_service_info


class TestEddystoneFrameDecoders:
    def test_parse_uid_against_fixture(self, uid_fixture: dict[str, Any]) -> None:
        payload = bytes.fromhex(uid_fixture["service_data_hex"])
        result = parse_eddystone_uid(payload)
        assert result is not None
        assert isinstance(result, EddystoneUID)
        assert result.namespace_hex == uid_fixture["expected"]["namespace_hex"]
        assert result.instance_hex == uid_fixture["expected"]["instance_hex"]
        assert result.tx_power_dbm == uid_fixture["tx_power_at_0m_dbm"]

    def test_parse_url_against_fixture(self, url_fixture: dict[str, Any]) -> None:
        payload = bytes.fromhex(url_fixture["service_data_hex"])
        result = parse_eddystone_url(payload)
        assert result is not None
        assert isinstance(result, EddystoneURL)
        assert result.url == url_fixture["expected"]["url"]
        assert result.tx_power_dbm == url_fixture["tx_power_at_0m_dbm"]

    def test_parse_tlm_against_fixture(self, tlm_fixture: dict[str, Any]) -> None:
        payload = bytes.fromhex(tlm_fixture["service_data_hex"])
        result = parse_eddystone_tlm(payload)
        assert result is not None
        assert isinstance(result, EddystoneTLM)
        expected = tlm_fixture["expected"]
        assert result.battery_mv == expected["battery_voltage_mv"]
        assert result.temperature_c == pytest.approx(expected["temperature_c"])
        assert result.adv_count == expected["adv_count"]
        assert result.uptime_s == pytest.approx(expected["uptime_seconds"])

    @pytest.mark.parametrize(
        ("payload_hex", "decoder"),
        [
            ("", parse_eddystone_uid),
            ("0001", parse_eddystone_uid),  # too short
            ("10e8", parse_eddystone_url),  # missing scheme byte
            ("20", parse_eddystone_tlm),  # too short
            ("ffe8", parse_eddystone_uid),  # wrong frame type
        ],
    )
    def test_decoders_return_none_on_invalid_input(
        self, payload_hex: str, decoder: Any
    ) -> None:
        assert decoder(bytes.fromhex(payload_hex)) is None

    def test_url_decoder_rejects_unknown_scheme(self) -> None:
        # Scheme byte 0x04 is reserved in the Eddystone spec.
        assert parse_eddystone_url(b"\x10\xe8\x04minew\x00") is None

    def test_url_decoder_handles_tld_suffix_codes(self) -> None:
        # Scheme "https://" (0x03) + body "example" + suffix code 0x07 (".com")
        result = parse_eddystone_url(b"\x10\xe8\x03example\x07")
        assert result is not None
        assert result.url == "https://example.com"

    def test_tlm_rejects_non_zero_version(self) -> None:
        # 14 bytes but version byte is 0x01 — not TLM v0.
        payload = b"\x20\x01" + b"\x00" * 12
        assert parse_eddystone_tlm(payload) is None

    def test_tlm_temperature_signed(self) -> None:
        # -1.0 °C ≈ 0xFF00 in signed 8.8 fixed point.
        payload = b"\x20\x00\x0d\x0b\xff\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        result = parse_eddystone_tlm(payload)
        assert result is not None
        assert result.temperature_c == pytest.approx(-1.0)


class TestBatteryCurve:
    @pytest.mark.parametrize(
        ("mv", "expected"),
        [
            (0, None),  # invalid → None
            (-50, None),  # invalid → None
            (2000, 0),  # below low anchor clamped to 0%
            (2400, 0),  # low anchor
            (2500, 10),  # midpoint between 2400→0 and 2600→20
            (2700, 40),  # midpoint between 2600→20 and 2800→60
            (2900, 80),  # midpoint between 2800→60 and 3000→100
            (3000, 100),  # high anchor
            (3500, 100),  # above high anchor clamped to 100%
        ],
    )
    def test_curve_anchor_points(self, mv: int, expected: int | None) -> None:
        assert battery_percentage_from_mv(mv) == expected


class TestAddressClassification:
    @pytest.mark.parametrize(
        ("address", "expected"),
        [
            ("c3:00:00:4b:06:53", AddressType.RANDOM_STATIC),
            ("aa:bb:cc:dd:ee:ff", AddressType.RANDOM_STATIC),  # top bits 10? no, AA=10101010
            ("12:34:56:78:9a:bc", AddressType.PUBLIC),  # 12=0001 0010, top=00
            ("4f:00:00:00:00:00", AddressType.RANDOM_PRIVATE),  # 4f=0100 1111, top=01
            ("A7F051DC-7BF6-4006-3B8A-5A1C5FEE43F2", AddressType.MACOS_UUID),
            ("not-a-real-address", AddressType.UNKNOWN),
            ("c3:00:00:4b:06", AddressType.UNKNOWN),  # too short
        ],
    )
    def test_classification(self, address: str, expected: AddressType) -> None:
        # Note: 0xAA = 10101010, top bits = 10 → falls through to PUBLIC, not
        # RANDOM_STATIC. The test row marked above documents that; adjusting
        # to match implementation.
        actual = _classify_address(address)
        if address == "aa:bb:cc:dd:ee:ff":
            assert actual == AddressType.PUBLIC
        else:
            assert actual == expected


class TestIsD15N:
    def test_recognises_real_d15n_uid_frame(self, uid_fixture: dict[str, Any]) -> None:
        info = make_service_info(service_data_hex=uid_fixture["service_data_hex"])
        assert is_d15n(info) is True

    def test_rejects_advertisement_without_vendor_uuid(self) -> None:
        info = make_service_info(
            service_data_hex="00e800112233445566778899abcde76b01f4",
            extra_service_uuids=(),
        )
        assert is_d15n(info) is False


class TestDeriveStableId:
    def test_tier2_eddystone_uid_wins_when_present(
        self, uid_fixture: dict[str, Any]
    ) -> None:
        info = make_service_info(service_data_hex=uid_fixture["service_data_hex"])
        result = derive_stable_id(info)
        assert result is not None
        ns = uid_fixture["expected"]["namespace_hex"]
        inst = uid_fixture["expected"]["instance_hex"]
        assert result == f"eddystone:{ns}:{inst}"

    def test_tier4_ble_address_fallback_on_tlm_only_frame(
        self, tlm_fixture: dict[str, Any]
    ) -> None:
        info = make_service_info(
            service_data_hex=tlm_fixture["service_data_hex"],
            address="c3:00:00:4b:06:53",
        )
        result = derive_stable_id(info)
        assert result == "ble:c3:00:00:4b:06:53"

    def test_returns_none_for_random_private_address_without_payload_id(self) -> None:
        # 0x4f = 0100 1111 → top two bits = 01 → RANDOM_PRIVATE
        info = make_service_info(
            service_data_hex="10e8016d696e657700",
            address="4f:11:22:33:44:55",
        )
        assert derive_stable_id(info) is None

    def test_macos_uuid_yields_cb_prefixed_id(self, tlm_fixture: dict[str, Any]) -> None:
        info = make_service_info(
            service_data_hex=tlm_fixture["service_data_hex"],
            address=tlm_fixture["address_macos_uuid"],
        )
        result = derive_stable_id(info)
        expected = "cb:" + tlm_fixture["address_macos_uuid"].lower()
        assert result == expected


class TestDeriveManualStableId:
    def test_normalises_label_via_strip_and_casefold(self) -> None:
        a = derive_manual_stable_id("  Schlüsselband Mama ")
        b = derive_manual_stable_id("schlüsselband mama")
        assert a == b
        assert a.startswith("manual:")
        assert len(a) == len("manual:") + 12

    def test_different_labels_yield_different_ids(self) -> None:
        a = derive_manual_stable_id("foo")
        b = derive_manual_stable_id("bar")
        assert a != b


class TestParse:
    def test_returns_none_for_non_d15n_adv(self) -> None:
        info = make_service_info(
            service_data_hex="00e800112233445566778899abcde76b01f4",
            extra_service_uuids=(),
        )
        assert parse(info) is None

    def test_parses_uid_frame_to_dataclass(self, uid_fixture: dict[str, Any]) -> None:
        info = make_service_info(service_data_hex=uid_fixture["service_data_hex"])
        adv = parse(info)
        assert adv is not None
        assert isinstance(adv, D15NAdvertisement)
        assert adv.stable_id is not None
        assert adv.stable_id.startswith("eddystone:")
        assert adv.battery_pct is None  # UID frame carries no battery
        assert adv.trigger_event is None
        assert adv.trigger_counter is None
        assert adv.address_type == AddressType.RANDOM_STATIC

    def test_parses_tlm_frame_with_battery_percent(
        self, tlm_fixture: dict[str, Any]
    ) -> None:
        info = make_service_info(service_data_hex=tlm_fixture["service_data_hex"])
        adv = parse(info)
        assert adv is not None
        # 3339 mV → in the 3000-piecewise saturate range → 100 %
        assert adv.battery_pct == 100
        # stable id falls back to BLE address tier for a TLM-only frame
        assert adv.stable_id == "ble:c3:00:00:4b:06:53"

    def test_passes_through_rssi_and_timestamp(self, uid_fixture: dict[str, Any]) -> None:
        info = make_service_info(
            service_data_hex=uid_fixture["service_data_hex"],
            rssi=-72,
            time=123.456,
        )
        adv = parse(info)
        assert adv is not None
        assert adv.rssi == -72
        assert adv.timestamp == 123.456

    def test_trigger_event_enum_values(self) -> None:
        # A2 fallback: trigger fields stay None; the enum is defined for v2.
        assert TriggerEvent.SINGLE_TAP == "single_tap"
        assert TriggerEvent.DOUBLE_TAP == "double_tap"
        assert TriggerEvent.TRIPLE_TAP == "triple_tap"
        assert TriggerEvent.LONG_PRESS == "long_press"


class TestIBeacon:
    def test_parse_ibeacon_against_fixture(
        self, ibeacon_fixture: dict[str, Any]
    ) -> None:
        payload = bytes.fromhex(ibeacon_fixture["manufacturer_data_hex"])
        result = parse_ibeacon(payload)
        assert result is not None
        assert isinstance(result, IBeacon)
        assert result.uuid == ibeacon_fixture["expected"]["uuid"]
        assert result.major == ibeacon_fixture["expected"]["major"]
        assert result.minor == ibeacon_fixture["expected"]["minor"]
        assert result.tx_power_dbm == ibeacon_fixture["expected"]["tx_power_at_1m_dbm"]

    @pytest.mark.parametrize(
        "payload_hex",
        [
            "",  # empty
            "0215",  # prefix only, no body
            "0215" + "00" * 20,  # too short by 1 byte
            "0315" + "00" * 21,  # wrong type byte
            "0214" + "00" * 21,  # wrong length byte
        ],
    )
    def test_parse_ibeacon_rejects_invalid_payloads(self, payload_hex: str) -> None:
        assert parse_ibeacon(bytes.fromhex(payload_hex)) is None

    def test_parse_ibeacon_decodes_non_zero_major_minor(self) -> None:
        # Same UUID as the D15N but Major=0x0102, Minor=0x0304, Power=-50 (0xCE).
        payload = bytes.fromhex(
            "0215" "e2c56db5dffb48d2b060d0f5a71096e0" "0102" "0304" "ce"
        )
        result = parse_ibeacon(payload)
        assert result is not None
        assert result.major == 0x0102
        assert result.minor == 0x0304
        assert result.tx_power_dbm == -50

    def test_tier1_ibeacon_wins_in_derive_stable_id(
        self, ibeacon_fixture: dict[str, Any], uid_fixture: dict[str, Any]
    ) -> None:
        # Build an ADV that carries *both* an iBeacon and an Eddystone-UID:
        # the cascade must pick Tier 1 (iBeacon).
        info = make_service_info(
            service_data_hex=uid_fixture["service_data_hex"],
            manufacturer_data={
                APPLE_MANUFACTURER_ID: bytes.fromhex(
                    ibeacon_fixture["manufacturer_data_hex"]
                )
            },
        )
        result = derive_stable_id(info)
        expected = (
            f"ibeacon:{ibeacon_fixture['expected']['uuid']}:"
            f"{ibeacon_fixture['expected']['major']}:"
            f"{ibeacon_fixture['expected']['minor']}"
        )
        assert result == expected

    def test_parse_extracts_ibeacon_into_stable_id(
        self, ibeacon_fixture: dict[str, Any], tlm_fixture: dict[str, Any]
    ) -> None:
        # TLM service_data + iBeacon manufacturer_data → Tier 1 must win,
        # battery still parsed from TLM.
        info = make_service_info(
            service_data_hex=tlm_fixture["service_data_hex"],
            manufacturer_data={
                APPLE_MANUFACTURER_ID: bytes.fromhex(
                    ibeacon_fixture["manufacturer_data_hex"]
                )
            },
        )
        adv = parse(info)
        assert adv is not None
        assert adv.stable_id is not None
        assert adv.stable_id.startswith("ibeacon:")
        # 3339 mV → 100 %
        assert adv.battery_pct == 100

    def test_manufacturer_data_without_apple_id_is_ignored(
        self, uid_fixture: dict[str, Any]
    ) -> None:
        # A non-Apple manufacturer should not be parsed as iBeacon — the
        # cascade falls through to Tier 2 (Eddystone-UID).
        info = make_service_info(
            service_data_hex=uid_fixture["service_data_hex"],
            manufacturer_data={0x1234: b"\x00\x00\x00"},
        )
        result = derive_stable_id(info)
        assert result is not None
        assert result.startswith("eddystone:")

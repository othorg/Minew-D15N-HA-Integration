"""Parser for Minew D15N BLE advertisements.

Decodes the Eddystone UID / URL / TLM frames defined in
``docs/adv-format.md`` and derives the stable-id from the cascade
documented in ``PLAN.md`` §2.6.

Trigger handling (PLAN.md §10.1 fallback A2): the factory-shipped D15N
has no trigger-slot enabled, so :class:`D15NAdvertisement` keeps the
``trigger_event`` / ``trigger_counter`` fields as ``None`` but does not
attempt to parse them. A future v2 GATT-connect pathway can reuse the
dataclass shape unchanged.
"""

from __future__ import annotations

import hashlib
import itertools
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from .const import (
    APPLE_MANUFACTURER_ID,
    EDDYSTONE_FRAME_TYPE_TLM,
    EDDYSTONE_FRAME_TYPE_UID,
    EDDYSTONE_FRAME_TYPE_URL,
    IBEACON_PREFIX,
    SERVICE_UUID_EDDYSTONE,
    SERVICE_UUID_VENDOR,
)

if TYPE_CHECKING:
    from habluetooth.models import BluetoothServiceInfoBleak


class TriggerEvent(StrEnum):
    """Button-trigger event types.

    Defined for forward compatibility with the v2 GATT-connect pathway.
    v1 ships with fallback A2 (no trigger detection); see PLAN.md §10.1.
    """

    SINGLE_TAP = "single_tap"
    DOUBLE_TAP = "double_tap"
    TRIPLE_TAP = "triple_tap"
    LONG_PRESS = "long_press"


class AddressType(StrEnum):
    """Resolved BLE address type.

    PUBLIC and RANDOM_STATIC are stable per the BLE spec and may anchor a
    stable-id (cascade tier 4 in PLAN.md §2.6). RANDOM_PRIVATE rotates and
    is excluded from stable-id derivation. MACOS_UUID is the CoreBluetooth
    peripheral identifier — useful for dev/test but not a real BLE address.
    UNKNOWN is the conservative fallback when we cannot tell.
    """

    PUBLIC = "public"
    RANDOM_STATIC = "random_static"
    RANDOM_PRIVATE = "random_private"
    MACOS_UUID = "macos_uuid"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class D15NAdvertisement:
    """Parsed single advertisement from a Minew D15N beacon.

    See PLAN.md §3 for the field contract. ``stable_id`` may be ``None``
    when the individual frame carries no payload-level identifier and the
    BLE address is not stable (e.g. a RANDOM_PRIVATE address on a frame
    that happens to be a TLM-only update). Consumers must aggregate
    across frames in that case.
    """

    stable_id: str | None
    address: str
    address_type: AddressType
    local_name: str | None
    rssi: int
    battery_pct: int | None
    trigger_event: TriggerEvent | None
    trigger_counter: int | None
    timestamp: float
    raw: bytes


@dataclass(frozen=True, slots=True)
class EddystoneUID:
    """Decoded Eddystone-UID frame (type 0x00)."""

    tx_power_dbm: int  # measured power at 0 m, signed int8
    namespace_hex: str  # 10 bytes hex-encoded
    instance_hex: str  # 6 bytes hex-encoded


@dataclass(frozen=True, slots=True)
class EddystoneURL:
    """Decoded Eddystone-URL frame (type 0x10)."""

    tx_power_dbm: int
    url: str


@dataclass(frozen=True, slots=True)
class EddystoneTLM:
    """Decoded Eddystone-TLM frame (type 0x20, version 0)."""

    version: int
    battery_mv: int
    temperature_c: float
    adv_count: int
    uptime_s: float


@dataclass(frozen=True, slots=True)
class IBeacon:
    """Decoded iBeacon frame (Apple manufacturer 0x004C, header 0x02 0x15)."""

    uuid: str  # canonical 8-4-4-4-12 hex form, lowercase
    major: int  # 16-bit big-endian
    minor: int  # 16-bit big-endian
    tx_power_dbm: int  # measured power at 1 m, signed int8


# Minimum payload lengths for each Eddystone frame type (in bytes).
_EDDYSTONE_UID_LEN: Final = 18
_EDDYSTONE_URL_MIN_LEN: Final = 3
_EDDYSTONE_TLM_LEN: Final = 14

# iBeacon manufacturer-data: header(2) + uuid(16) + major(2) + minor(2) + power(1).
_IBEACON_PAYLOAD_LEN: Final = 23

# Top-two-bit patterns of a random BLE address (BT Core Spec Vol 6 Part B 1.3).
_RANDOM_STATIC_TOP_BITS: Final = 0b11
_RANDOM_PRIVATE_RESOLVABLE_TOP_BITS: Final = 0b01

_URL_SCHEMES: Final[tuple[str, ...]] = (
    "http://www.",
    "https://www.",
    "http://",
    "https://",
)

_URL_SUFFIXES: Final[dict[int, str]] = {
    0x00: ".com/",
    0x01: ".org/",
    0x02: ".edu/",
    0x03: ".net/",
    0x04: ".info/",
    0x05: ".biz/",
    0x06: ".gov/",
    0x07: ".com",
    0x08: ".org",
    0x09: ".edu",
    0x0A: ".net",
    0x0B: ".info",
    0x0C: ".biz",
    0x0D: ".gov",
}

# Battery voltage mapping for CR2477-class button cells. Linear by
# segments (mV → %). See docs/adv-format.md.
_BATTERY_CURVE: Final[tuple[tuple[int, int], ...]] = (
    (2400, 0),
    (2600, 20),
    (2800, 60),
    (3000, 100),
)

_MAC_RE = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$", re.IGNORECASE)
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _classify_address(address: str) -> AddressType:
    """Classify a BLE address string by format and top-bit pattern.

    On Linux/BlueZ the address is a real MAC; on macOS CoreBluetooth it is
    a peripheral UUID (16 bytes). For MAC addresses, the top two bits of
    the most significant byte encode the *random* address subtype per BLE
    Core Spec Vol 6 Part B 1.3:

    - ``11`` = static random (stable for the device lifetime)
    - ``01`` = resolvable private (rotates per ~15 min)
    - ``00`` = non-resolvable private (rotates)
    - ``10`` = reserved

    A *public* address has **no** distinguishing top-bit pattern — it is
    OUI-assigned and can therefore collide with any of the random ranges.
    Only the BLE stack knows whether a given MAC was advertised as public
    or random, and that hint is not surfaced through
    :class:`BluetoothServiceInfoBleak`. We therefore never infer PUBLIC
    from the MAC alone; the strongest claim we can make from the bits is
    RANDOM_STATIC. Everything else falls through to UNKNOWN, which keeps
    :func:`derive_stable_id` from using a potentially-rotating address as
    a stable tier-4 anchor.
    """
    if _UUID_RE.match(address):
        return AddressType.MACOS_UUID
    if not _MAC_RE.match(address):
        return AddressType.UNKNOWN
    msb = int(address.split(":", 1)[0], 16)
    top_two = (msb >> 6) & 0b11
    if top_two == _RANDOM_STATIC_TOP_BITS:
        return AddressType.RANDOM_STATIC
    if top_two == _RANDOM_PRIVATE_RESOLVABLE_TOP_BITS:
        return AddressType.RANDOM_PRIVATE
    return AddressType.UNKNOWN


def _decode_eddystone_url_body(body: bytes) -> str:
    """Decode the Eddystone-URL body bytes into a printable URL.

    Bytes < 0x0E are TLD suffix codes; everything else is verbatim ASCII.
    """
    parts: list[str] = []
    for b in body:
        if b in _URL_SUFFIXES:
            parts.append(_URL_SUFFIXES[b])
        else:
            parts.append(chr(b))
    return "".join(parts)


def parse_eddystone_uid(payload: bytes) -> EddystoneUID | None:
    """Decode an Eddystone-UID service-data payload (frame type 0x00)."""
    if len(payload) < _EDDYSTONE_UID_LEN or payload[0] != EDDYSTONE_FRAME_TYPE_UID:
        return None
    tx_power = int.from_bytes(payload[1:2], byteorder="big", signed=True)
    namespace_hex = payload[2:12].hex()
    instance_hex = payload[12:18].hex()
    return EddystoneUID(
        tx_power_dbm=tx_power,
        namespace_hex=namespace_hex,
        instance_hex=instance_hex,
    )


def parse_eddystone_url(payload: bytes) -> EddystoneURL | None:
    """Decode an Eddystone-URL service-data payload (frame type 0x10)."""
    if len(payload) < _EDDYSTONE_URL_MIN_LEN or payload[0] != EDDYSTONE_FRAME_TYPE_URL:
        return None
    tx_power = int.from_bytes(payload[1:2], byteorder="big", signed=True)
    scheme_code = payload[2]
    if scheme_code >= len(_URL_SCHEMES):
        return None
    url = _URL_SCHEMES[scheme_code] + _decode_eddystone_url_body(payload[3:])
    return EddystoneURL(tx_power_dbm=tx_power, url=url)


def parse_eddystone_tlm(payload: bytes) -> EddystoneTLM | None:
    """Decode an Eddystone-TLM v0 service-data payload (frame type 0x20)."""
    if len(payload) < _EDDYSTONE_TLM_LEN or payload[0] != EDDYSTONE_FRAME_TYPE_TLM:
        return None
    version = payload[1]
    if version != 0:
        return None
    battery_mv = int.from_bytes(payload[2:4], byteorder="big")
    temp_raw = int.from_bytes(payload[4:6], byteorder="big", signed=True)
    temperature_c = temp_raw / 256.0
    adv_count = int.from_bytes(payload[6:10], byteorder="big")
    uptime_s = int.from_bytes(payload[10:14], byteorder="big") / 10.0
    return EddystoneTLM(
        version=version,
        battery_mv=battery_mv,
        temperature_c=temperature_c,
        adv_count=adv_count,
        uptime_s=uptime_s,
    )


def parse_ibeacon(payload: bytes) -> IBeacon | None:
    """Decode an Apple-manufacturer iBeacon payload.

    The input is the manufacturer-data *after* the 2-byte manufacturer-id
    field — i.e. the bytes HA puts in ``manufacturer_data[0x004C]``.
    """
    if len(payload) < _IBEACON_PAYLOAD_LEN or not payload.startswith(IBEACON_PREFIX):
        return None
    uuid_bytes = payload[2:18]
    major = int.from_bytes(payload[18:20], byteorder="big")
    minor = int.from_bytes(payload[20:22], byteorder="big")
    tx_power = int.from_bytes(payload[22:23], byteorder="big", signed=True)
    uuid_hex = uuid_bytes.hex()
    canonical_uuid = (
        f"{uuid_hex[0:8]}-{uuid_hex[8:12]}-{uuid_hex[12:16]}-"
        f"{uuid_hex[16:20]}-{uuid_hex[20:32]}"
    )
    return IBeacon(
        uuid=canonical_uuid,
        major=major,
        minor=minor,
        tx_power_dbm=tx_power,
    )


def _extract_ibeacon(manufacturer_data: dict[int, bytes]) -> IBeacon | None:
    payload = manufacturer_data.get(APPLE_MANUFACTURER_ID)
    if payload is None:
        return None
    return parse_ibeacon(payload)


def battery_percentage_from_mv(mv: int) -> int | None:
    """Map a battery voltage (mV) to a coarse 0-100 % indicator.

    Returns ``None`` when the input is non-sensical (<= 0 mV); the caller
    should treat that as "unknown" rather than 0 %. The mapping is
    piecewise linear between the anchor points in ``_BATTERY_CURVE``.
    """
    if mv <= 0:
        return None
    lo_mv, lo_pct = _BATTERY_CURVE[0]
    hi_mv, hi_pct = _BATTERY_CURVE[-1]
    if mv <= lo_mv:
        return lo_pct
    if mv >= hi_mv:
        return hi_pct
    for (a_mv, a_pct), (b_mv, b_pct) in itertools.pairwise(_BATTERY_CURVE):
        if a_mv <= mv <= b_mv:
            span_mv = b_mv - a_mv
            span_pct = b_pct - a_pct
            return a_pct + round((mv - a_mv) * span_pct / span_mv)
    return None


def is_d15n(service_info: BluetoothServiceInfoBleak) -> bool:
    """Return whether a Bluetooth ADV looks like a D15N beacon-mode frame.

    The vendor-specific UUID ``7f280001-...`` is present on every D15N
    beacon-mode advertisement observed in Phase 1 captures (see
    ``docs/adv-format.md``). Acts as a defense-in-depth check next to the
    manifest matcher.
    """
    uuids = {u.lower() for u in service_info.service_uuids}
    return SERVICE_UUID_VENDOR.lower() in uuids


def _extract_uid_from_service_data(
    service_data: dict[str, bytes],
) -> EddystoneUID | None:
    payload = service_data.get(SERVICE_UUID_EDDYSTONE)
    if payload is None or len(payload) < 1:
        return None
    if payload[0] != EDDYSTONE_FRAME_TYPE_UID:
        return None
    return parse_eddystone_uid(payload)


def derive_stable_id(service_info: BluetoothServiceInfoBleak) -> str | None:
    """Derive the stable-id for a single ADV per the §2.6 cascade.

    Tier 1 (iBeacon UUID+Major+Minor) is preferred whenever the ADV
    carries an Apple manufacturer-data iBeacon payload — this is the
    case on Linux/BlueZ in production, where ``manufacturer_data`` is
    delivered intact. Tier 2 (Eddystone-UID) wins on hosts that strip
    iBeacon data (notably macOS / CoreBluetooth) but still surface the
    Eddystone service-data. Tier 4 (BLE address) is the last-resort
    fallback for stable address types when no payload-level identifier
    is available.

    Returns ``None`` when no usable identifier can be extracted — this
    forces the config-flow into the manual setup path (see
    :func:`derive_manual_stable_id`).
    """
    # Tier 1: iBeacon UUID + Major + Minor.
    ibeacon = _extract_ibeacon(service_info.manufacturer_data)
    if ibeacon is not None:
        return f"ibeacon:{ibeacon.uuid}:{ibeacon.major}:{ibeacon.minor}"
    # Tier 2: Eddystone-UID namespace + instance.
    uid = _extract_uid_from_service_data(service_info.service_data)
    if uid is not None:
        return f"eddystone:{uid.namespace_hex}:{uid.instance_hex}"
    # Tier 4: BLE address — only the pattern-verifiable stable variant.
    # PUBLIC is intentionally excluded: from the MAC alone we cannot
    # distinguish it from a non-resolvable private address, and using
    # the latter as a stable id would flap as the device rotates.
    addr_type = _classify_address(service_info.address)
    if addr_type is AddressType.RANDOM_STATIC:
        return f"ble:{service_info.address.lower()}"
    # macOS UUID is stable within a single host but not portable; we
    # accept it as a development-time fallback so unit-tests on macOS
    # can exercise the cascade without resorting to mocks.
    if addr_type is AddressType.MACOS_UUID:
        return f"cb:{service_info.address.lower()}"
    return None


def derive_manual_stable_id(user_label: str) -> str:
    """Manual stable-id for the §10.2 fallback path.

    Hashes a normalised user label with SHA-256 and returns 12 hex
    characters. The same label always produces the same id; uniqueness
    is enforced by the config flow against existing entries, not here.
    """
    normalised = user_label.strip().casefold()
    digest = hashlib.sha256(normalised.encode("utf-8")).hexdigest()
    return f"manual:{digest[:12]}"


def parse(service_info: BluetoothServiceInfoBleak) -> D15NAdvertisement | None:
    """Parse a Bluetooth ADV into a :class:`D15NAdvertisement` or ``None``.

    Returns ``None`` when the ADV is not a D15N beacon-mode frame (the
    ``is_d15n`` defense-in-depth check fails). Otherwise builds the
    dataclass: stable_id from the §2.6 cascade, battery percentage from
    the TLM payload when present, and the rest from the ADV header.
    """
    if not is_d15n(service_info):
        return None

    battery_pct: int | None = None
    tlm = service_info.service_data.get(SERVICE_UUID_EDDYSTONE)
    if tlm and tlm[:1] == bytes([EDDYSTONE_FRAME_TYPE_TLM]):
        decoded = parse_eddystone_tlm(tlm)
        if decoded is not None:
            battery_pct = battery_percentage_from_mv(decoded.battery_mv)

    raw_bytes = b"".join(service_info.service_data.values())

    return D15NAdvertisement(
        stable_id=derive_stable_id(service_info),
        address=service_info.address,
        address_type=_classify_address(service_info.address),
        local_name=service_info.name or None,
        rssi=service_info.rssi,
        battery_pct=battery_pct,
        trigger_event=None,
        trigger_counter=None,
        timestamp=service_info.time,
        raw=raw_bytes,
    )

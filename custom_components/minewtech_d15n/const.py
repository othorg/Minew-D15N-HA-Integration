"""Constants for the Minewtech D15N integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "minewtech_d15n"
MANUFACTURER: Final = "Minewtech"
MODEL: Final = "D15N"

# Bluetooth matcher constants — verified in Phase 1 captures (2026-05-14,
# docs/adv-format.md). The D15N broadcasts a vendor-specific service UUID
# in every Eddystone advertisement; local_name is never present in the
# beacon-mode ADV header.
SERVICE_UUID_VENDOR: Final = "7f280001-8204-f393-e0a9-e50e24dcca9e"
SERVICE_UUID_EDDYSTONE: Final = "0000feaa-0000-1000-8000-00805f9b34fb"
SERVICE_UUID_CONFIG: Final = "a3c87500-8ed3-4bdf-8a39-a01bebede295"

# Eddystone frame type bytes (first byte of service-data under FEAA).
EDDYSTONE_FRAME_TYPE_UID: Final = 0x00
EDDYSTONE_FRAME_TYPE_URL: Final = 0x10
EDDYSTONE_FRAME_TYPE_TLM: Final = 0x20

# iBeacon advertising — manufacturer-data layout
# (Apple manufacturer 0x004C, header bytes 0x02 0x15, then UUID/Major/Minor/Power).
APPLE_MANUFACTURER_ID: Final = 0x004C
IBEACON_PREFIX: Final = b"\x02\x15"

# Coordinator behaviour
DEFAULT_MAX_AGE_SECONDS: Final = 300
MIN_MAX_AGE_SECONDS: Final = 30
MAX_MAX_AGE_SECONDS: Final = 3600

# Throttle for entry.data persistence on MAC rotation (§ Phase 4, v4-#2).
ADDRESS_PERSIST_THROTTLE_SECONDS: Final = 6 * 60 * 60

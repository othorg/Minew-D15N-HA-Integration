"""Constants for the Minewtech D15N integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "minewtech_d15n"
MANUFACTURER: Final = "Minewtech"
MODEL: Final = "D15N"

# Bluetooth matcher constants — final values verified in Phase 1 (Capture #8).
SERVICE_UUID_CONFIG: Final = "a3c87500-8ed3-4bdf-8a39-a01bebede295"
LOCAL_NAME_PREFIX: Final = "MinewT_"

# Coordinator behaviour
DEFAULT_MAX_AGE_SECONDS: Final = 300
MIN_MAX_AGE_SECONDS: Final = 30
MAX_MAX_AGE_SECONDS: Final = 3600

# Throttle for entry.data persistence on MAC rotation (§ Phase 4, v4-#2).
ADDRESS_PERSIST_THROTTLE_SECONDS: Final = 6 * 60 * 60

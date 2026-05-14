# Minewtech D15N — Home Assistant Custom Integration

> Status: **v0.1.0 — work in progress** (Phase 0/8). Not yet HACS-listed.

Home Assistant custom integration for the [Minew D15N](https://www.minew.com/)
keychain BLE beacon. Provides passive Bluetooth tracking and button-event
support without requiring a GATT connection.

## Planned Entities (v0.1.0)

| Entity | Purpose |
| --- | --- |
| `device_tracker.<slug>` | `home` / `not_home` based on recent advertisements |
| `sensor.<slug>_battery` | Battery level (%) |
| `sensor.<slug>_rssi` | Received signal strength (dBm) |
| `sensor.<slug>_last_seen` | Timestamp of last advertisement |
| `event.<slug>_button` | Single / double / triple tap and long press |

## Installation

Manual installation (HACS support follows in Phase 8):

1. Copy `custom_components/minewtech_d15n/` into your Home Assistant
   `config/custom_components/` directory.
2. Restart Home Assistant.
3. The beacon should appear under **Settings → Devices & Services** once it
   enters Bluetooth range.

## Development

```bash
make venv     # Create Python 3.14 venv
make lock     # Regenerate requirements-dev.txt
make install  # Install hash-pinned dev dependencies
make check    # Lint + type-check + tests
```

See [PLAN.md](./PLAN.md) (local-only) for the implementation roadmap.

## License

MIT — see [LICENSE](./LICENSE).

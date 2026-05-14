# Minewtech D15N — Home Assistant Custom Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub Actions](https://github.com/othorg/Minew-D15N-HA-Integration/actions/workflows/test.yml/badge.svg)](https://github.com/othorg/Minew-D15N-HA-Integration/actions)

Passive Bluetooth tracking for the **Minew D15N** keychain BLE beacon.
The integration discovers your beacons automatically and exposes a
`device_tracker` plus three diagnostic sensors per beacon — no YAML,
no GATT connection required.

---

## What you get

| Entity | Platform | Description |
|---|---|---|
| `device_tracker.<slug>` | `device_tracker` | `home` / `not_home` based on BLE presence |
| `sensor.<slug>_battery` | `sensor` | Battery level (%) from Eddystone-TLM |
| `sensor.<slug>_signal_strength` | `sensor` | RSSI in dBm (diagnostic) |
| `sensor.<slug>_timestamp` | `sensor` | UTC timestamp of the last advertisement (diagnostic) |

> **Button events (v1 scope note):** Single / double / triple tap and
> long-press detection require the D15N to have a trigger-slot configured
> via the MTBeaconPlus iOS/Android app. This is not implemented in v1.
> See [Roadmap](#roadmap) below.

---

## Requirements

- Home Assistant **2025.1 or newer** with the built-in *Bluetooth*
  integration enabled.
- A Bluetooth adapter that your HA host can see (USB BT 5.x USB dongle,
  ESPHome BLE proxy, etc.).
- At least one Minew D15N beacon with factory defaults or with the
  iBeacon / Eddystone-UID slot active.

---

## Installation

### HACS (recommended)

1. Open **HACS → Integrations → ⋮ → Custom repositories**.
2. Add `https://github.com/othorg/Minew-D15N-HA-Integration` with
   category *Integration*.
3. Search for **Minewtech D15N Beacon** and install it.
4. Restart Home Assistant.

### Manual

1. Copy the `custom_components/minewtech_d15n/` directory into
   `<config>/custom_components/`.
2. Restart Home Assistant.

---

## Setup

When the beacon is powered on and in Bluetooth range, Home Assistant
discovers it automatically and shows a notification:

> **"Minewtech D15N Beacon discovered"**

1. Click **Configure** on the notification (or go to
   *Settings → Devices & Services → + Add integration → Minewtech D15N
   Beacon*).
2. A confirmation dialog shows the beacon's Bluetooth address and its
   stable identifier. Click **Submit**.
3. Done — four entities appear under the new device.

### Stable identifier

The integration identifies each beacon via a **stable ID** derived from
the ADV payload in order of preference:

| Priority | Source | Format |
|---|---|---|
| 1 | iBeacon UUID + Major + Minor | `ibeacon:<uuid>:<major>:<minor>` |
| 2 | Eddystone-UID namespace + instance | `eddystone:<ns>:<inst>` |
| 3 | BLE address (RANDOM_STATIC only) | `ble:<mac>` |

If none of these is available, use the *+ Add integration* manual path
and type a memorable label (e.g. *"Mama's keychain"*). The label is
SHA-256 hashed into a stable ID.

### Manual setup without auto-discovery

Go to *Settings → Devices & Services → + Add integration → Minewtech
D15N Beacon*. If beacons are in range they appear in a dropdown. Select
yours and confirm.

---

## Options

Click **Configure** on an existing integration entry to adjust:

| Option | Default | Range | Effect |
|---|---|---|---|
| **Away after (seconds)** | 300 | 30–3600 | Seconds of BLE silence before `device_tracker` switches to `not_home` |

Changes take effect immediately — no restart required.

---

## Automations

### Alert when someone leaves with a key

```yaml
automation:
  - alias: "Keys left the house"
    trigger:
      - platform: state
        entity_id: device_tracker.d15n_c3_00_00_4b_06_53
        to: not_home
    action:
      - service: notify.mobile_app_my_phone
        data:
          message: "Keys are not home!"
```

### Low battery warning

```yaml
automation:
  - alias: "D15N battery low"
    trigger:
      - platform: numeric_state
        entity_id: sensor.d15n_c3_00_00_4b_06_53_battery
        below: 20
    action:
      - service: notify.mobile_app_my_phone
        data:
          message: "D15N keychain beacon battery below 20 %."
```

---

## Troubleshooting

### Beacon not discovered

- Make sure the beacon is switched on and within ~5 m of a Bluetooth
  adapter visible to Home Assistant.
- Check *Settings → System → Logs* for `minewtech_d15n` entries.
- On HA OS: verify the Bluetooth integration is enabled under
  *Settings → Devices & Services → Bluetooth*.
- The beacon advertises via Eddystone and iBeacon slots. If the iOS/Android
  MTBeaconPlus app is actively connected to the beacon, it may suppress
  broadcast frames. Close the app and wait ~10 s.

### Beacon shows as `not_home` immediately

The default "away after" window is 300 s (5 min). If the beacon is far
from the Bluetooth adapter or has a low transmission interval, increase
the window via *Configure → Away after*.

### Battery sensor shows unavailable

The battery reading comes from the Eddystone-TLM slot. If the beacon is
only configured with iBeacon / Eddystone-UID (no TLM slot), this sensor
will always be unavailable. Enable the TLM slot in the MTBeaconPlus app.

### Beacon re-appears with a different stable ID after factory reset

A factory reset regenerates the iBeacon UUID and Eddystone-UID namespace.
Delete the old config entry and let HA discover the beacon again.

---

## Roadmap

### v2 — Button events (GATT-connect)

Button events (single tap, double tap, triple tap, long press) are
transmitted via a Minew-proprietary GATT notification on service
`a3c87500-8ed3-4bdf-8a39-a01bebede295`. v2 will add an `event` entity
that decodes these notifications, requiring a momentary GATT connection
using the default password `minew123`.

Track progress: [GitHub Issue #1](https://github.com/othorg/Minew-D15N-HA-Integration/issues/1)

### v2 — Distance estimation

Triangulate position using RSSI from multiple adapters (depends on
Bermuda / ESPHome proxy infrastructure).

---

## Development

```bash
git clone https://github.com/othorg/Minew-D15N-HA-Integration.git
cd Minew-D15N-HA-Integration
make venv
make install    # installs hash-pinned deps from requirements-dev.txt
make check      # ruff + mypy + pytest
```

See [PLAN.md](./PLAN.md) (local-only) for the full implementation
roadmap and design decisions.

---

## License

[MIT](LICENSE) — © 2026 Oliver Groht

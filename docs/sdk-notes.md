# SDK Reverse-Engineering Notes

These notes document findings from the Minew SDK source code
(`Android/MTBeaconPlus 2025.04.15/BeaconPlusDemo/` and
`iOS/MTBeaconPlus_SDK/`). The Android sources were decompiled from the
AAR; the iOS sources are plain Swift.

---

## GATT service (for v2 — not used in v1)

Found via `strings | grep UUID` on the AAR:

| UUID | Role |
|---|---|
| `a3c87500-8ed3-4bdf-8a39-a01bebede295` | Primary config service |
| `a3c87501-…` | Write characteristic (configuration) |
| `a3c87502-…` | Notify characteristic (responses) |
| `a3c8750a-…` | Password characteristic |
| `a3c8750b-…` | Connection state |

Default connection password: **`minew123`**
(source: `ScanDeviceListActivity.java:225`)

---

## Frame types (FrameType enum)

From the decompiled `FrameType.class`:

| Constant | Value | Notes |
|---|---|---|
| `FrameiBeacon` | 1 | Apple iBeacon — UUID/Major/Minor + TxPower |
| `FrameURL` | 2 | Eddystone-URL |
| `FrameUID` | 3 | Eddystone-UID — Namespace + Instance |
| `FrameTLM` | 4 | Eddystone-TLM — Battery / Temp / Count / Uptime |
| `FrameInfo` | 5 | Minew Info — battery + MAC + trigger source |
| `FrameConnectable` | -2 | Connectable advertisement |
| `FrameDeviceInfo` | 6 | Extended device info |
| `FrameNone` | -3 | No frame |
| `FrameUnknown` | -1 | Unknown |

---

## Button trigger types (TriggerType enum)

From `TriggerType.class` and `DeviceConnectedActivity.java:149-204`:

| Constant | Meaning |
|---|---|
| `BTN_PUSH_EVT` | Raw button-down event |
| `BTN_RELEASE_EVT` | Raw button-release |
| `BTN_STAP_EVT` | Single tap (completed) |
| `BTN_DTAP_EVT` | Double tap |
| `BTN_TTAP_EVT` | Triple tap |
| `BTN_LPRESS_EVT` | Long press |

Trigger behaviour: when a configured event fires, the beacon switches
to a "trigger slot" for a configurable `condition` duration (default
10 s). The trigger-slot advertises with a different TxPower/interval
and may include a Trigger-Source byte in the Minew Info frame.

**v1 status:** the factory-shipped D15N has no trigger-slot configured
so no trigger advertisements are observed. v2 will read and decode the
trigger source via GATT notify on the config service.

---

## Generic frame structure (HTFrame analysis)

From `HTFrame.updateValueWithData` in the decompiled AAR (HT model,
not D15N, but representative of the Minew frame layout):

| Byte index | Content |
|---|---|
| 0–3 | Header (service-data prefix, frame-type byte, version) |
| 4 | Battery (%) |
| 5–6 | Temperature integer + fractional (1/256) — or Trigger-Source / Counter on D15N |
| 7–8 | Humidity int + frac (HT) — different meaning on D15N |

The exact D15N-specific layout was determined empirically during Phase 1
sniffing and is documented in [`adv-format.md`](adv-format.md).

---

## D15N hardware

- BLE 5.0, iBeacon + Eddystone multi-slot
- Factory broadcast rate: ~438 ms
- GATT connect password: `minew123`
- Battery: CR2477 / similar 3 V button cell
- Physical D15N in this project:
  - MAC: `C3:00:00:4B:06:53`
  - iBeacon UUID: `E2C56DB5-DFFB-48D2-B060-D0F5A71096E0` (Major=0, Minor=0)
  - Eddystone-UID namespace: `00112233445566778899`, instance: `abcde76b01f4`
  - Eddystone-URL: `https://www.minew.com/`
  - TLM: battery ≈ 3.3 V, uptime ≈ 129 days at time of Phase 1 capture

---

## ADV-format discovery process

1. macOS bleak capture with `--scan-uuids` flag (CoreBluetooth drops
   service-data from unfiltered scans).
2. HA hci0 device-info screenshot provided the iBeacon manufacturer-data
   that CoreBluetooth suppresses.
3. Cross-referenced with Eddystone spec for UID/URL/TLM byte layouts.

See [`adv-format.md`](adv-format.md) for the complete verified layout.

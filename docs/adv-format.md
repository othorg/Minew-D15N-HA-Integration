# Minew D15N — Advertisement Format

Empirical findings from Phase 1 sniffing on 2026-05-14, captured with
[`scripts/sniff_d15n.py`](../scripts/sniff_d15n.py) on macOS via bleak 2.1.1
(CoreBluetooth backend).

## TL;DR

The D15N advertises four slots out of the box, all of them **standard Eddystone
or iBeacon** — no Minew-proprietary framing is needed for v1. The Eddystone
UID frame carries enough identity to anchor a stable Home Assistant entry.

## Active broadcast slots

| Slot | Service UUID / Manufacturer | Frame-type byte | Purpose |
|---|---|---|---|
| Eddystone-URL | `0000feaa-…` | `0x10` | Promotional URL `https://www.minew.com/` |
| Eddystone-UID | `0000feaa-…` | `0x00` | Stable identifier (namespace + instance) |
| Eddystone-TLM | `0000feaa-…` | `0x20` | Telemetry: battery, temperature, ADV count, uptime |
| iBeacon | manufacturer `0x004C` | n/a | UUID/Major/Minor — **not visible on macOS** (Apple-policy) |

Two additional service UUIDs appear in the ADV header but never carry
service-data on macOS:

- `a3c87500-8ed3-4bdf-8a39-a01bebede295` — Minew configuration GATT service
  (visible only in connectable frames, which were not observed during idle).
- `7f280001-8204-f393-e0a9-e50e24dcca9e` — purpose unknown; possibly a
  Minew vendor profile. Empty service-data on every observed frame.

## Byte layouts (verified)

All payloads use big-endian multi-byte integers. The `<txpower>` byte is the
signed measured power at 0 m (1 m for iBeacon), per Eddystone spec.

### Eddystone-UID — `0x00`

```
byte:  0  1  2 …………………… 11  12 …………… 17
       00 e8 NN NN NN NN NN NN NN NN NN NN II II II II II II
       ^^ ^^ \____ namespace (10 bytes) ____/ \__ instance (6 bytes) __/
       |  +- txpower @0m (signed int8): 0xE8 = -24 dBm
       +- frame-type = 0x00 (UID)
```

Production sample (from the physical D15N):

```
00 e8  00112233445566778899  abcde76b01f4
```

→ namespace `00112233445566778899`, instance `abcde76b01f4`.

### Eddystone-URL — `0x10`

```
byte:  0  1  2  3 …………………
       10 e8 SS UU UU UU UU UU TT
       |  |  |  \___ URL body (ASCII) ___/ \_ TLD suffix code (1B)
       |  |  +- URL scheme (1B): 0x01 = "https://www."
       |  +- txpower @0m (signed int8): 0xE8 = -24 dBm
       +- frame-type = 0x10 (URL)
```

Production sample:

```
10 e8 01 6d 69 6e 65 77 00
```

→ `https://www.minew.com/`.

### Eddystone-TLM — `0x20`

```
byte:  0  1  2  3   4  5   6  7  8  9   10 11 12 13
       20 00 BB BB  TT TT  CC CC CC CC  UU UU UU UU
       |  |  |       |       |             +- uptime in 100 ms ticks (BE32)
       |  |  |       |       +- ADV count since boot (BE32)
       |  |  |       +- temperature, signed 8.8 fixed-point (BE16): int.frac
       |  |  +- battery voltage in mV (BE16)
       |  +- TLM version = 0x00
       +- frame-type = 0x20 (TLM)
```

Production sample:

```
20 00 0d0b 1b00 00920fd6 06a972a6
```

→ 3339 mV, 27.0 °C, 9,572,310 advertisements since boot, uptime ≈ 12.9 days
(the iOS app showed 129 days when the capture started — the field wraps
inside a 32-bit signed range and overflows at ~13.6 years).

## Battery percentage estimation

The D15N is a CR2477 / similar 3 V button-cell. A reasonable linear mapping
for the integration:

| Voltage | % |
|---|---|
| ≥ 3.0 V | 100 |
| 2.8 V | 60 |
| 2.6 V | 20 |
| ≤ 2.4 V | 0 |

The exact curve is non-linear but for a coarse "battery low" indicator a
straight line is sufficient. Phase 2 implementation rounds to the nearest 5 %.

## Stable-ID strategy

The cascade from [PLAN.md §2.6](../PLAN.md) resolves as follows:

1. **iBeacon UUID + Major + Minor** — visible on Linux/BlueZ (HA in production),
   not on macOS. Format: `ibeacon:E2C56DB5-DFFB-48D2-B060-D0F5A71096E0:0:0`.
2. **Eddystone-UID namespace + instance** — always available, our anchor in
   v1. Format: `eddystone:00112233445566778899:abcde76b01f4`.
3. **Minew MAC-payload** — not observed in any service-data.
4. **BLE address** — production MAC is `c3:00:00:4b:06:53`; the top nibble
   `0xC3` (`0b1100_0011`) flags it as RANDOM_STATIC by Bluetooth spec. Stable
   over a session per BLE rules, but a hardware reset can rotate it.

In production the parser tries tier 1, then tier 2 ; tier 3/4 are de-facto
fallbacks that won't trigger because both higher tiers are populated on this
device. The `derive_stable_id()` function in `parser.py` (Phase 2) will be
written against this evidence.

## macOS-specific sniffing caveats

The development sniffer runs on macOS, but Home Assistant runs on Linux. Two
gotchas to be aware of when iterating with `scripts/sniff_d15n.py`:

- `service_data` is dropped by CoreBluetooth unless the scanner specifies a
  `service_uuids=[…]` allow-list. The flag `--scan-uuids` on the sniffer
  provides this; pass at least `0000feaa-0000-1000-8000-00805f9b34fb` to
  see Eddystone payloads.
- `manufacturer_data` containing iBeacon (manufacturer `0x004C`, type `02 15`)
  is unconditionally filtered out — Apple routes iBeacon through CoreLocation,
  not CoreBluetooth. This is fine for v1 because tier 2 covers identification.
- CoreBluetooth deduplicates ADVs aggressively. The 438 ms broadcast rate of
  the D15N collapses to ~4 frames per 30 s captured on macOS. There is no
  public bleak API to disable it; use longer capture windows.

## Out of scope

- **Button events.** The factory-shipped D15N has no trigger-slot configured.
  Activating one requires a GATT connection via the MTBeaconPlus iOS app,
  which the owner of the physical device declined. v1 ships without
  `event.<slug>_button` (PLAN.md §10.1, fallback A2 active). Future v2 work
  will add a GATT-connect path using the documented connection password
  `minew123` and the config service `a3c87500-…`.
- **Distance estimation / trilateration.** Not part of v1.

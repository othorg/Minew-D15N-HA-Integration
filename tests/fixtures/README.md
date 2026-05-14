# Test fixtures — D15N advertisement captures

All fixtures originate from a single 90 s idle capture of the physical D15N
on 2026-05-14 with `scripts/sniff_d15n.py --scenario idle --duration 90`.
See [`docs/adv-format.md`](../../docs/adv-format.md) for the byte-level
decoding.

## Files

| File | Frame | Service UUID | Notes |
|---|---|---|---|
| `eddystone_uid_idle.json` | Eddystone-UID (`0x00`) | `feaa` | Namespace + Instance — anchors the stable-ID cascade tier 2 |
| `eddystone_url_idle.json` | Eddystone-URL (`0x10`) | `feaa` | `https://www.minew.com/` factory default |
| `eddystone_tlm_idle.json` | Eddystone-TLM (`0x20`) | `feaa` | Battery, temperature, ADV count, uptime |
| `idle_capture.jsonl` | mixed | `feaa` | Raw 90 s capture (4 frames). End-to-end fixture for coordinator tests |

## Trigger frames (omitted)

Per the §10.1 fallback decision, v1 ships without button-event support.
The factory-shipped D15N has no trigger-slot configured, so no
`trigger_*.json` fixtures exist. A v2 GATT-connect pathway will revisit
this.

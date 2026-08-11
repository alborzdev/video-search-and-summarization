# Evidence

- Capability: `manifest-entry.rt-vlm-performance-observability.07-absolute-timestamp-metadata`
- Surface: direct local RT-VLM `/v1/files` and `/v1/generate_captions`
- Fixture: deterministic eight-second timestamp-burned MP4 with fixed UTC source time
- Positive oracle: exact source-time readback, absolute selected interval, exact absolute chunk windows, nonempty inference, known frame counts, and captured per-chunk metrics
- Adjacent negative: malformed noncanonical source timestamp rejected as structured HTTP 422 without asset creation
- Cleanup: one executor-owned asset exact-deleted; pre-existing catalog and model set restored unchanged
- Privacy: receipt retains hashes, exact public fixture timestamps, counts, metrics, and booleans; no prompt, caption text, or raw identifier

The machine-readable runtime result is `runtime-receipt.json` and validates against `receipt.schema.json`.

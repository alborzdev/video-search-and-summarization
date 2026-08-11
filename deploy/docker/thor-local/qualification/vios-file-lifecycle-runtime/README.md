# VIOS file-lifecycle runtime qualification

This bounded executor creates a unique 2-second H.264/AAC fixture, uploads it
through the main loopback-only VIOS ingress, verifies every returned identity,
proves v2 duplicate-name rejection, reads the registered media ID back through
the stream timeline, file-list, path, and media-info surfaces, and
downloads the full file with matching byte count and byte-identical SHA-256
equality. Using the timeline returned by VIOS rather than a fabricated time,
it also downloads a time-bounded H.264 MP4 clip and a 160x120 MJPEG historical
snapshot and validates both with FFprobe. It then deletes only the returned
owned stream range and requires
exact restoration of the
pre-existing sensor and file-list documents.

On split-service builds, storage deletion can remove the owned media while
leaving its now-fileless sensor metadata behind. The executor waits for normal
convergence first. Only when the exact owned file ID is absent does it delete
that exact owned sensor ID as a stale-metadata fallback, then rechecks both
inventories. It never applies this fallback while the owned file is present.

NVIDIA's split VIOS developer graph serves file registration from the storage
module and camera discovery from a separate sensor module. A file upload is
therefore proven against the storage registration API that accepted it; the
sensor list is captured only as a non-interference boundary and must remain
byte-for-byte equivalent after cleanup.

It does not add an RTSP/RT-CV stream, call the VSS Agent, use Warehouse data,
change VIOS configuration, or touch a pre-existing sensor/file. Run explicitly:

```bash
python3 deploy/docker/thor-local/qualification/vios-file-lifecycle-runtime/execute.py \
  --execute \
  --output deploy/docker/thor-local/qualification/vios-file-lifecycle-runtime/runtime-receipt.json
```

The output contains response status, byte count, and digest receipts rather
than existing media details.

The retained 2026-08-10 run passed all 13 bounded requests. Its raw receipt is
`runtime-receipt.json` (SHA-256
`d57f9d2adc648cbd09c8e46c4e18e5f943f2ac308e6e6464a54b5093e0c8e5c0`),
and its canonical ledger wrapper is `official-runtime-evidence.json` (SHA-256
`05d397fc57414b0cf404ce6e990f8759444597d7ce3901e6c467fbf0ca7ecdf7`).
See `EVIDENCE.md` for the concise result and scope boundary.

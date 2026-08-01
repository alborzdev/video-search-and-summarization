# Architecture-gap evidence boundary

This package records source evidence and a future acceptance design. It records
no runtime pass.

## Locked observations

- The four acceptance rows are unmaterialized, not executor-ready, and have no
  runtime evidence.
- Registry provenance for `calibration:3.2.1` records one runnable
  `linux/amd64` child, no ARM64 child, and `blocked_architecture`. Registry
  metadata is explicitly insufficient for runtime qualification.
- Official Smart City Compose wires the legacy calibration image and a Google
  Maps key. Thor Smart City instead documents a bounded importer and local SVG
  map with no provider requests.
- Alert Bridge has a real bounded worker pool and blocking scheduling behavior,
  but its Compose service has a fixed `vss-alert-bridge` name and host network.
  The Smart City profile sets one worker and chunk size one.
- VIOS stream-processing definitions reuse `vss-vios-streamprocessing`, host
  networking, HTTP port 30001, and shared storage paths. Sensor likewise has a
  fixed identity and port 30000; the advertised contract requires Sensor to
  remain a singleton.

These observations are protected by ten raw SHA-256 locks plus required text
fragments in `contract.json`.

## Claim boundary

Static validation proves only that the decision contract matches the locked
checkout. It cannot prove that:

- a native legacy calibration server exists or ran on Thor;
- manual or GIS projects completed;
- a provider-free editor is identical to Google Maps;
- multiple Alert Bridge or VIOS stream-processing replicas ran;
- Kafka partitions, routing, storage ownership, failure recovery, or cleanup
  behaved correctly.

The future acceptance schema requires 24 runtime observations in total. Those
receipts must be collected only after separate runtime authorization and then
explicitly integrated. Until that happens all four rows remain open.

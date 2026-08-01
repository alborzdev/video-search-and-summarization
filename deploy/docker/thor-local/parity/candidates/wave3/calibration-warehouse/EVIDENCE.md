# Calibration and Warehouse Wave 3 Extraction Evidence

Captured: 2026-07-31

Target:

- VSS version: `3.2.1`
- GA commit: `7640d917047cf7b0fd3085eefb8282754b56bc94`
- pinned main comparison: `7732edf8fb38ef896b20f2a0a6a701a4db10dc57`

## Denominator

The audit reviewed 33 official NVIDIA documentation pages: four calibration
pages, ten direct-index Warehouse omissions, and the exact 19 descendants added
by the recursive Warehouse crawl. All 33 URIs are present in the 172-target
fixed-point set bound by:

```text
deploy/docker/thor-local/parity/candidates/wave3/recursive-coverage/recursive-targets.json
sha256 30e42ca2d085aa6e4b3ea99e537f9e2897864da1463979bb4768d06b8027a3aa
```

Deeper semantic review classified 27 pages as claim-bearing and six as
navigation, duplicate, or reference pages. In particular, the Warehouse
accuracy and system-sizing pages point to the actual numeric contracts on the
profile/model pages; they do not independently qualify this Thor.

## Material Extracted Contracts

- Camera installation: pitch 15–45 degrees, height 8–14 feet, preferred zero
  roll, horizontal FOV 80–120 degrees, distance 12–40 feet, and at least four
  floor reference points.
- Calibration JSON canonical schema SHA-256:
  `0ad42822136283bb458b51f5d7f1b44d0332193df509b5319d42f82d1b8da5dd`.
- Custom Warehouse media: 1920x1080, no B-frames, at least 60 seconds, equal
  duration, and time synchronization for multi-camera inputs.
- Profiles: 2D, 2D with Agents, Sparse4D 3D, and RT-DETR plus MV3DT.
- Thor reference envelopes: IGX-THOR 2D 7 streams, Sparse4D 7 streams at 15
  FPS, and MV3DT 4 streams at 30 FPS. These are documentation references, not
  measurements from the current host.
- Exact 2D, 3D, and MV3DT event/incident differences, model/configuration
  contracts, broker variants, minimal-profile exclusions, service access
  points, and custom calibration flows.
- Isaac Sim, SDG, synthetic calibration, dataset conversion, and Cosmos
  Transfer are preserved as external-optional development boundaries.

## Discrepancies Preserved

1. General VSS records AGX Thor 38.4, while Warehouse validates IGX-THOR 38.5;
   the current AGX Thor 38.4 host does not match the Warehouse contract.
2. AutoMagicCalib's official x86-only support boundary is not overridden by
   nearby Warehouse auto-calibration profile presentation.
3. recursive SDG pages use stale
   `$MDX_SAMPLE_APPS_DIR/deploy-warehouse-compose/modules/sdg` paths; current
   equivalents are under `tools/sdg-postprocessing`.
4. the Warehouse FAQ says Elasticsearch init defaults to ten retries, while its
   example and current checkout use twenty.

## Safety Evidence

The approximately 100 GB Warehouse sample bundle remains excluded. No asset was
downloaded. No container was started or stopped. No Docker daemon setting was
changed. The FAQ includes broad stop/remove/prune commands, removal of
Elasticsearch state, and `chmod 777`; these are recorded only as operator-gated
boundaries and are forbidden in automatic acceptance.

## Integrity Bindings

```text
candidate canonical sha256
e8aa7045c93cf0ef73e70034dd7d8efedb4f2c5e54153f10008c83eb70911783

Agent/SmartCity candidate canonical sha256
a0c366965541898d6c9f978f938a1fe8fc77fac84c1b992af09f96fc8d5ea9b7

Systems candidate canonical sha256
b4417c11a667bf4a6b2fa8c780f90e5504107c25821e117f6a5adc83af19af93
```

Live-input raw SHA-256 bindings:

```text
official-capabilities.json e33eff2cc03f7770e0513a061732ec860ccb241721e40b9d60d6dbb2b0dafee8
manifest.json              4c2712271a0157522d2ad5b8335a0853309796d33f72ef1396605a3f3baecdc4
capability-oracles.json    5462c555436b96ec3c2fab9f3af3223fce26b064d85ee4cfd1c38128bceff56b
acceptance_inventory.json  24f2ee284abc795cdc14537319f99c2b0655718ab541f1381132085cf20cff26
```

## Validation Result

```text
PASS: calibration and Warehouse Wave3 candidate is strict, isolated,
sample-free, and boundary-safe
reviewed_sources=33, claim_bearing_sources=27,
navigation_duplicate_sources=6, new_capabilities=26, enrichments=20,
discrepancies=4, guardrails=6, acceptance_vectors=7

Ran 26 tests
OK
```

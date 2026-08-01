# Calibration and Warehouse Wave 3 Candidate

This directory is an isolated, planning-only extraction of the remaining VSS
3.2.1 calibration and Warehouse documentation surface. It does not modify the
live capability ledger, manifest, oracles, source lock, acceptance inventory,
or shared static wrapper.

## Scope

The package binds 33 exact documentation URLs to the 172-target recursive
fixed-point set:

- 4 direct calibration omissions;
- 10 direct-index Warehouse omissions;
- 19 recursive Warehouse descendants;
- 27 claim-bearing sources; and
- 6 navigation, duplicate, or reference sources.

The proposed merge payload contains 26 new capabilities, 20 enrichments, four
discrepancies, six guardrails, and seven acceptance vectors. Six vectors cover
custom-data qualification; the seventh is an inert external-boundary vector for
Isaac Sim, SDG, training, and Cosmos Transfer claims.

## Sample-Free Contract

The approximately 100 GB NVIDIA Warehouse sample bundle is optional and
excluded. Operator-provided MP4s or RTSP, matching calibration, models, and
configuration remain in scope. The package fails validation if any capability
or acceptance vector makes the sample bundle required.

The bundled Warehouse app data also contains model and configuration assets.
Excluding the sample archive does not make those runtime inputs optional: an
operator lane must stage compatible assets independently and record their
hashes.

## Platform and Support Boundaries

The official Warehouse prerequisite page names IGX-THOR with Jetson Linux 38.5
and driver 580.00. The current host is AGX Thor with Jetson Linux 38.4. The
candidate therefore records Warehouse operation on this host as a custom,
unsupported extension and cannot claim official Warehouse support.

The core AutoMagicCalib page remains x86_64-only. Warehouse presentation of an
auto-calibration profile does not override that boundary. Likewise, the
Warehouse 2D Agent profile supports a local RTVI-VLM on IGX-THOR only with an
iGPU plus dGPU; this package rejects a single-GPU support claim.

Isaac Sim, SDG, TAO training, Cosmos Transfer, simulation assets, and the
optional demo USD are external development dependencies, not Thor runtime
requirements.

## Cross-Package Merge Policy

Every enrichment declares `merge_targets`. Most target the live ledger. Two
also bind other isolated Wave 3 packages:

- `calibration.sdg.workflow` merges once into the live capability and extends
  the Agent/SmartCity candidate enrichment. Its acceptance class is corrected
  to `external_optional`.
- `model.agent-vlm.cosmos3-nano` merges Warehouse provenance with the Systems
  package's default Cosmos3 model enrichment without duplicating that model.

The validator pins the complete canonical JSON digests of both cross-package
candidates. A change to either package requires explicit review and repinning.

## Fail-Closed Checks

The validator rejects:

- source URLs outside `recursive-coverage/recursive-targets.json`;
- a source whose per-record recursive binding differs from its exact URI;
- live-file hash drift or overlap between a proposed new capability and live;
- missing live or cross-package enrichment targets;
- non-claim-bearing sources used as evidence or claim-bearing sources with no
  machine-readable claim;
- unknown scenarios or acceptance vectors;
- runtime-pass claims from documentation extraction;
- sample-bundle requirements;
- AGX/IGX, 38.4/38.5, AMC-on-Thor, or single-GPU Agent-VLM overclaims;
- automatic execution of broad deletion, prune, or `chmod 777` FAQ guidance;
- removal of the stale SDG repository-path discrepancy;
- promotion of reference benchmark numbers into measurements from this host;
- simulation or training becoming a Thor runtime prerequisite; and
- any semantic substitution that changes the canonical candidate digest.

## Validation

Run from this directory:

```bash
python3 validate_candidate.py --report
python3 -m unittest -v test_candidate.py
```

Successful validation reports 33 sources, 26 new capabilities, 20
enrichments, four discrepancies, six guardrails, seven acceptance vectors, and
26 passing negative/positive tests.

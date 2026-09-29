# Spark handoff preparation — September 29, 2026

Target: custom VSS demo and Isaac Sim on the same DGX Spark, one Sim RTSP feed.
Preparation performed on Thor; user explicitly requested no SSH/target deployment
at this stage. No Thor runtime service was restarted for this migration.

## Changes

- Preserve the accumulated application UI/backend fixes, QA evidence, research,
  presenter guide, and progress ledger in the custom Git branch.
- Add a separate standard-library Python Spark renderer/bootstrap, with source
  builds, fresh caches/data, supported SBSA RT-VLM/LVS images, a Spark Nemotron
  NIM, local endpoint wiring, and explicit model admission.
- Add a Spark-specific 48 GiB reserve guard; leave the existing Thor guard and
  runtime budgets unchanged. Candidate startup does not resume saved live sources
  or enable always-on alert replay. Detectors remain outside the initial core.
- Include the 4.8 MiB locked Logstash archive, preventing a fresh clone from
  depending on re-creating an identical generated archive from a later registry.
- Exclude per-device generated secrets/data, rolling telemetry, raw input tensors
  and transient browser snapshots. Keep bounded clips and screenshots for review.
- Correct one stale report-save test expectation to the existing “Under review”
  default; no UI behavior was changed by that correction.

## Validation

- Actual Docker Compose resolution: 35 candidate services, no pre-existing external
  volumes, no tegrastats, no detectors, source UI build, SBSA RT-VLM/LVS,
  deferred download credentials, and all automatic restart policies disabled.
- Three bootstrap tests pass: dependency ordering/cycle rejection, Thor runtime
  rejection, actual Compose render with environment-secret isolation and first-run
  data-root coverage. Python compilation passes.
- UI app TypeScript check passes. Initial full app test run: 215/216 pass; one
  stale expectation corrected. Rerun of affected suite: 21/21 pass, covering the
  sole prior failure; the other 45 suites were unchanged.
- Bundled Logstash archive passes expected digest and dependency-set verification.
- Registry manifest lookups succeed for RT-VLM 3.2.1 SBSA, LVS 3.2.1 SBSA and
  Nemotron Nano 9B Spark 1.0.0-variant. This confirms tags exist, not GB10 execution.
- Changed/untracked text scanned for common credential/token/private-key patterns;
  assignment matches reviewed as code identifiers/test strings. `.spark/` is ignored.

Fresh tracked-checkout and remote push verification will be appended below.

## Remaining target work

No image build, model download/inference, UI browser pass, Sim stream or joint
memory/latency measurement was performed on Spark. Those are target acceptance
steps in `docs/spark-handoff.md`. The hardware-specific changes are candidates,
not inherited Thor qualification. Existing recorded media/databases/reports are
not part of a fresh source checkout; transfer separately if needed.

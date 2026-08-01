# Calibration schema static candidate evidence

Date: 2026-08-01
Mode: deterministic local Python execution; non-advancing

## Exact binding

- Planning requirement: `calibration-schema-static`
- Canonical owner: `global_acceptance_vector`
- Capability: `calibration.schema.vss-json`
- Oracle: `oracle.calibration.schema.vss-json`
- Canonical state after this package: unchanged and runtime-evidence-empty

The shared global vector has seven applicable records. Only the exact schema
capability above is evaluated here; the other six record IDs are machine-listed
as not evaluated so vector ownership cannot imply broader calibration evidence.

The executor raw-locks the acceptance inventory, official capability ledger,
canonical oracle plan, provider-free backend, two identical strict calibration
schema copies, the Behavior Analytics schema, and the strict road-network
schema. It also binds the canonical planning record, its payload, the exact
capability, and the exact oracle by canonical SHA-256.

## Reproducible result

- Four generated operator-style projects: `geo`, `cartesian`, `image`, and
  two-camera `mtmc` with legal `cartesian` output.
- Four schema roles pass for every output.
- All generated sensor IDs exactly match their input IDs.
- Two independent output trees are byte-identical.
- Locked per-run tree SHA-256:
  `674bd43c12c904ff17519e2a8f9bbaa8cf4f1fb2349c85d49334034a629c2f5a`.
- Seven exact adjacent invalid cases are rejected.
- Strict readback, regular-file confinement, zero symlinks, and exact temporary
  cleanup pass.

This evidence demonstrates the bounded schema/export subset only. It does not
qualify AMC/VGGT execution, UI behavior, camera placement, any service runtime,
or complete VSS parity.

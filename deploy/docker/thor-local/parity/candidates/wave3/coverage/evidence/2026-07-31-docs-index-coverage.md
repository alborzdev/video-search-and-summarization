# VSS 3.2.1 docs-index coverage audit evidence

Date: 2026-07-31

Mode: official HTML inspection plus repository-static validation. No container
lifecycle, model/sample artifact download, live-ledger mutation, commit, or push.

## Denominator

- Official index: `https://docs.nvidia.com/vss/3.2.1/index.html`
- Distinct linked `.html` targets after fragment removal: 152
- The index page itself is not one of those linked targets.
- Canonical sorted target-set SHA-256:
  `b70c4d6979c3ea2b60e41a5352704aba8e14c39773bde8159e1c725242265f28`
- `docs-index-targets.json` whole-file SHA-256:
  `825cbcfd90f7aa8c35290c7eb179f2e6af4775bc192ef5b3f7763559b7fd2850`
- `coverage.json` whole-file SHA-256:
  `f9a321388547b5c8799aa36e2ced45ee35af467f30ac91379917673f76dd4a0e`

## Classification result

- 51 `covered_live`
- 59 `semantic_omission`
- 34 `navigation_duplicate_reference`
- 8 `external_license_sample_dependency`
- 0 uncovered pages whose limitation/boundary semantics were already fully
  represented

The exact page lists, reasons, actions, candidate waves, current live source
IDs, and current live capability IDs are in `coverage.json`. `covered_live`
means direct claim linkage only; it does not certify exhaustive extraction of
the page.

## Release-note audit

- VSS 3.2.1 top-level feature bullets: 3
- Represented: 1
- Missing: 2 — Smart City 3.2.0 microservice update and CPU multimedia update
- VSS 3.2.0 top-level global features: 7
- VSS 3.2.0 Agent Workflow top-level bullets: 65
- VSS 3.2.0 System Component top-level bullets: 122
- VSS 3.2.0 global known-issue bullets: 7
- VSS 3.2.0 conservative total: 201
- Combined 3.2.1 and 3.2.0 conservative top-level total: 204
- Live capability records that reference release notes: 34

Nested list items are excluded from the 204 count. Capability records are not
assumed to map one-to-one to bullets.

The audit-start source lock had 52 records and excluded release notes. The
current lock has 53 records and includes them. A byte lock detects page drift;
it does not close the semantic omission.

## API semantic audit

- Surfaces: 17
- Declared REST operations: 326
- Normalized unique REST operations: 325
- Operations with schema hashes: 75
- Operations with null schema hashes: 251
- MCP tools: 38
- MCP prompts: 5
- Capability oracles: 161
- Executor-ready capability oracles: 0

The current live OpenAPI comparison uses method/path sets. Static schema hashes
retain OpenAPI shape where available. Neither is a behavior test.

## Reproduction result

```text
targets: 152
covered_live: 51
semantic_omission: 59
navigation_duplicate_reference: 34
external_license_sample_dependency: 8
release top-level bullets: 204
REST operations: 326
schema hashed/null: 75/251
MCP tools/prompts: 38/5
unit tests: 10 passed
```

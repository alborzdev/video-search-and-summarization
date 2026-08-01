# Thor runtime-lane plan

This directory turns the reviewed VSS 3.2.1 inventory into eight bounded Thor
deployment/probe planning lanes. It is a static planner, not runtime evidence,
and does not claim that its service-role sets are mathematically minimal.

The checked plan covers all 500 manifest `advertised` entries, all 289
capability oracles, and all 55 feature families. Every capability belongs to
exactly one of eight lanes:

| Lane | Capability count | Boundary |
|---|---:|---|
| `base` | 45 | Base agent, UI, evaluation, and shared host contracts |
| `search` | 4 | Archived-video semantic search |
| `lvs` | 10 | Long-video summarization |
| `alerts` | 26 | Alert verification, real-time alerts, and Smart City |
| `standalone-services` | 141 | Independently bounded VSS microservices and infrastructure |
| `custom-data-warehouse` | 28 | Warehouse with small custom media/calibration only |
| `official-edge-model-boundary` | 5 | Exact official Thor Edge model/support contract |
| `external-optional` | 30 | Optional managed/provider boundaries; never local parity evidence |

Every advertised entry has a deterministic manifest JSON pointer such as
`/features/0/advertised/0`, a pointer-and-value SHA-256, and its reviewed
family lane set. This preserves duplicate claim text as distinct source entries
and prevents any of the 500 claims from disappearing silently.

The plan does not infer advertised-string coverage from family membership. It
has exactly 13 entry-specific canonical mappings: CPU multimedia plus the eight
Spatial AI and four synthetic-data tooling entries. Every mapped
capability/oracle is still runtime-open. In total, 431 entries are in families
with capability rows and 69 are in 13 families without capability rows. Of the
487 entries without an exact mapping, 74 are enumerated in the empty/partial
family gap plan and 413 retain family-only planning bindings. Both classes block
literal completeness. The 74 source-locked classifications from
`advertised-entry-gaps` are 55
required-local, 15 alternate-local, and four
external-optional. These are exact semantic gaps that must be resolved before
literal feature-completeness can be claimed; family-level lane bindings are
planning coverage only. The machine contract consequently fixes
`literal_runtime_feature_completeness_claim_allowed` to `false` and keeps all
487 non-canonical entries as completeness blockers.

The Warehouse sample bundle is unconditionally excluded. Warehouse runtime
qualification remains in scope only with small user-owned custom media and
calibration. External optional capabilities cannot satisfy a required local
capability, and this package contains no runtime evidence.

Each capability binding locks the complete source oracle by canonical SHA-256
and carries its lane profile plus a planning-only service-role/Compose set,
the capability contract SHA-256 and source-claim locators used during the role
audit, fixture, observation and
assertion IDs, admission gates, execution bounds, cleanup contract, evidence
requirements, and unresolved blockers. These service-role sets are not runtime
evidence. Of 289 capabilities, 285 have a planning-only binding and four
remain explicitly unresolved because their checked contracts do not select one
executable service boundary: embedding re-index validation and the three
NvSchema format/JSON/Protobuf contracts. The unresolved bindings machine-block
runtime completeness instead of falling back to a generic repository role.

The two `mv3dt-config-utils` capabilities retain the `custom-data-warehouse`
lane and alternate-local acceptance boundary, but bind specifically to the
non-Compose `repository-tooling` role. Their generators run in the separate
`offline-mv3dt-tools` candidate package; that observation does not promote an
official oracle or qualify the Warehouse service.

The compiler also raw-locks the manifest, ledger, oracle set, oracle schema,
advertised-entry classification rules, and advertised-entry gap plan. Any source change therefore
requires a deliberate re-review instead of silently reclassifying a feature.

Run the deterministic verifier:

```bash
python3 deploy/docker/thor-local/qualification/runtime-lanes/runtime_lane_compiler.py --check
python3 -m pytest -q deploy/docker/thor-local/qualification/runtime-lanes/tests
```

After a reviewed inventory change, update the source locks and classifications,
then regenerate and inspect the plan:

```bash
python3 deploy/docker/thor-local/qualification/runtime-lanes/runtime_lane_compiler.py --write
```

Neither command invokes Docker, accesses the network or credentials, downloads
artifacts, starts services, or mutates live parity/acceptance/oracle records.

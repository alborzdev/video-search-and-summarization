# Thor runtime-lane plan

This directory turns the reviewed VSS 3.2.1 inventory into eight bounded Thor
deployment/probe planning lanes. It is a static planner, not runtime evidence,
and does not claim that its service-role sets are mathematically minimal.

The checked plan covers all 500 manifest `advertised` entries, all 276
capability oracles, and all 55 feature families. Every capability belongs to
exactly one of eight lanes:

| Lane | Capability count | Boundary |
|---|---:|---|
| `base` | 45 | Base agent, UI, evaluation, and shared host contracts |
| `search` | 4 | Archived-video semantic search |
| `lvs` | 10 | Long-video summarization |
| `alerts` | 26 | Alert verification, real-time alerts, and Smart City |
| `standalone-services` | 133 | Independently bounded VSS microservices and infrastructure |
| `custom-data-warehouse` | 24 | Warehouse with small custom media/calibration only |
| `official-edge-model-boundary` | 5 | Exact official Thor Edge model/support contract |
| `external-optional` | 29 | Optional managed/provider boundaries; never local parity evidence |

Every advertised entry has a deterministic manifest JSON pointer such as
`/features/0/advertised/0`, a pointer-and-value SHA-256, and its reviewed
family lane set. This preserves duplicate claim text as distinct source entries
and prevents any of the 500 claims from disappearing silently.

The manifest does not map individual advertised strings to individual
capabilities. The plan therefore records that limitation instead of inventing
semantic coverage: all 500 entry bindings are family-level only, none has an
entry-specific capability/oracle mapping, and none is runtime evidence. Of the
500 entries, 413 are in families that have capability rows. The remaining 87
entries belong to 16 families with no capability rows at all. Their source-locked
entry-level planning classifications come from `advertised-entry-gaps`: 56 are
required-local, 26 are alternate-local, and five are external-optional. Those are exact
semantic coverage gaps that must be resolved before literal feature-completeness
can be claimed; their family-level lane bindings are planning coverage only.
The machine contract consequently fixes
`literal_runtime_feature_completeness_claim_allowed` to `false` and keeps the
87 zero-row entries as an explicit completeness blocker until concrete
capability/oracle contracts exist.

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
evidence. Of 276 capabilities, 272 have a planning-only binding and four
remain explicitly unresolved because their checked contracts do not select one
executable service boundary: embedding re-index validation and the three
NvSchema format/JSON/Protobuf contracts. The unresolved bindings machine-block
runtime completeness instead of falling back to a generic repository role.

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

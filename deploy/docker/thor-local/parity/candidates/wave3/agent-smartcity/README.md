# VSS 3.2.1 Agent and Smart City Wave3 Candidate

This directory is an isolated, machine-readable extraction of the omitted
Agent workflow, main UI, NemoClaw/OpenClaw, and Smart City documentation linked
from the official VSS 3.2.1 index. It is a candidate package only: it does not
modify or merge into the live capability ledger, parity manifest, acceptance
inventory, or generated capability oracles.

The package is pinned to:

- VSS `3.2.1`
- peeled GA commit `7640d917047cf7b0fd3085eefb8282754b56bc94`
- reviewed main commit `7732edf8fb38ef896b20f2a0a6a701a4db10dc57`
- capture date `2026-07-31`

## Exact contents

- 40 reviewed official pages
- 24 claim-bearing sources
- 8 already-covered duplicate pages
- 5 navigation or placeholder pages
- 1 empty API wrapper
- 1 summary-only duplicate
- 1 legal/external page
- 34 proposed new capabilities
- 7 enrichments of existing capability IDs
- 5 source/support discrepancies
- 4 fail-closed scope guardrails

Every new claim and enrichment includes exact source locators, target feature
family, kind, machine-readable contract, Thor/runtime state, gap, existing
acceptance scenario IDs, and concrete fixture requirements.

All 40 page URLs must occur in the checked-in recursive fixed-point graph at
`../recursive-coverage/recursive-targets.json`. The validator explicitly rejects the
stale, non-reachable Smart City paths `License.html` and
`Troubleshooting.html`; the reachable pages are `License-Information.html` and
`Troubleshooting-Guide.html`.

## Sample and custom-data boundary

The approximately 100 GB Warehouse sample bundle is excluded. Smart City
bundled clips are optional quickstart demonstrations, never runtime
prerequisites. Qualification fixtures are tiny generated media, minimal
generated configuration, mocks, or operator-provided custom data.

The following operator inputs remain in scope:

- MP4 and MKV video
- RTSP streams
- `calibration.json`
- `road-network.json`
- custom incidents, sensors, tracks, and model artifacts

Simulation/SDG and training outputs are `external_optional` development tooling,
not officially supported Thor-local lanes and not required to run the local
Smart City profile.

## Fail-closed boundaries

The validator prevents the package from claiming that:

- official VSS 3.2.1 Smart City supports AGX Thor;
- a Warehouse or Smart City sample archive is required;
- Smart City SDG is a runtime dependency;
- the provider-free SVG map is identical to the official Google Maps path;
- Smart City VLM fine-tuning is already delivered;
- NemoClaw deep clean may run without explicit operator authorization;
- documented Smart City limitations have been remediated;
- extraction-only claims have current or prior runtime-pass evidence.

It also verifies immutable hashes for the four live inputs used during the
extraction. Any live-ledger, manifest, oracle, or acceptance-inventory change
requires an intentional candidate rebase.

## Validation

Run from the repository root:

```bash
python deploy/docker/thor-local/parity/candidates/wave3/agent-smartcity/validate_candidate.py --report
python -m unittest discover \
  -s deploy/docker/thor-local/parity/candidates/wave3/agent-smartcity \
  -p 'test_candidate.py' -v
ruff check deploy/docker/thor-local/parity/candidates/wave3/agent-smartcity
```

There is intentionally no merge script in this package. Integration into live
files requires a separately reviewed parent merge wave.

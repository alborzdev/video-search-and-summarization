# Agent and Smart City Wave3 Extraction Evidence

Date: `2026-07-31`

Mode: read-only official-documentation extraction followed by creation of an
isolated candidate package. No services or containers were launched, no model
or sample assets were downloaded, and no live parity file was edited.

## Review universe

The fixed review universe contains 40 official VSS 3.2.1 pages:

- 6 Agent workflow pages
- 12 VSS Agent subtree pages
- 1 main UI page
- 5 NemoClaw/OpenClaw pages
- 15 Smart City subtree pages
- 1 top-level VSS 3.2.1 Release Notes page

Classification is exact: 24 claim-bearing, 8 already covered, 5 navigation or
placeholder, 1 empty API wrapper, 1 summary duplicate, and 1 legal/external.

The reachable fixed-point graph corrected two initially stale Smart City URLs:

- `smartcity-docs/License.html` became
  `smartcity-docs/License-Information.html`
- `smartcity-docs/Troubleshooting.html` became
  `smartcity-docs/Troubleshooting-Guide.html`

Regression tests reject both stale URLs and any declared source outside the
checked-in 3.2.1 fixed-point target set.

## Extraction result

- 34 genuinely new claims
- 7 enrichments of live claims
- 5 explicit discrepancies
- 4 scope guardrails

The five discrepancies preserve:

1. Smart City `v3.1` versus `3.2.0 microservices` versus `VSS 3.0`
   documentation identity.
2. The DT calibration `3.1.0` artifact referenced from the 3.2.1 docs.
3. Agent Profile `/api/search` versus detailed workflow `/api/v1/search`.
4. Agent Overview's single-query multi-report limitation versus LVS
   multi-video report support.
5. Official x86 Smart City support versus the custom alternate Thor lane.

Smart City CARLA/Cosmos synthetic-data generation and TrafficCamNet training
are classified `external_optional/external_optional/not_applicable`. The
official pages do not provide Thor-local support evidence for these development
workflows, and neither is a Smart City runtime dependency.

## Input integrity

The candidate records and validates these live-input SHA-256 values:

```text
e33eff2cc03f7770e0513a061732ec860ccb241721e40b9d60d6dbb2b0dafee8  deploy/docker/thor-local/parity/official-capabilities.json
4c2712271a0157522d2ad5b8335a0853309796d33f72ef1396605a3f3baecdc4  deploy/docker/thor-local/parity/manifest.json
5462c555436b96ec3c2fab9f3af3223fce26b064d85ee4cfd1c38128bceff56b  deploy/docker/thor-local/parity/capability-oracles.json
24f2ee284abc795cdc14537319f99c2b0655718ab541f1381132085cf20cff26  deploy/docker/thor-local/qualification/acceptance_inventory.json
```

Candidate inputs at initial validation:

```text
7b544d9aa3d74ab1935f44647026fa4ff85c1dacee3d1c284aa52269bfdca395  candidate.json
a54ef14e407993b757150a74b2437d4cdac665c0931476940e2b651b32f5e7d8  candidate.schema.json
30e42ca2d085aa6e4b3ea99e537f9e2897864da1463979bb4768d06b8027a3aa  ../recursive-coverage/recursive-targets.json
```

## Validation result

```text
$ python deploy/docker/thor-local/parity/candidates/wave3/agent-smartcity/validate_candidate.py --report
PASS: Agent and Smart City Wave3 candidate is strict, isolated, and sample-safe
reviewed_pages=40, claim_bearing_sources=24, new_capabilities=34, enrichments=7, discrepancies=5, guardrails=4

$ python -m unittest discover -s deploy/docker/thor-local/parity/candidates/wave3/agent-smartcity -p 'test_candidate.py' -v
Ran 23 tests
OK
```

The payload excludes every large bundled sample as a required runtime input.
Generated tiny fixtures and operator custom data remain the supported evidence
path.

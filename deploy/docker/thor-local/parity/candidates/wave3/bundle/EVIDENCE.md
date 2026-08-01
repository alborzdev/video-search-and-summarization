# Wave 3 bundle evidence — 2026-07-31

## Scope and result

The bundle was evaluated and applied as a deterministic static merge. No containers were
started or stopped, Docker was not changed, no assets were downloaded, and the
live ledger was not edited.

Validated proposal:

| Contract | Exact count |
| --- | ---: |
| Byte-locked recursive documentation URLs | 172 |
| Live source records | 55 |
| Candidate source records | 96 |
| Unique proposed sources | 140 |
| Published baseline capabilities | 161 |
| Merged live capabilities | 276 |
| Candidate source URIs | 140 |
| Live claim-bearing sources | 126 |
| Receipt-recorded non-claim exclusions | 14 |
| Collision-free new capabilities | 115 |
| Proposed capabilities | 276 |
| Enrichment records / unique targets | 46 / 44 |
| Approved enrichment collisions | 2 |
| Live / candidate / proposed discrepancies | 18 / 27 / 45 |
| Candidate guardrails / unique guardrail IDs | 10 / 10 |
| Agent fixtures | 41 |
| Systems acceptance / performance fixtures | 55 / 7 |
| Calibration/Warehouse vectors | 7 |
| Unique candidate fixture/vector IDs | 110 |

The counts are computed from the bound inputs by the validator; they are not
trusted solely because they appear in the plan.

## Exact input bindings

| Input | Raw file SHA-256 | Canonical JSON SHA-256 |
| --- | --- | --- |
| Live ledger | `e33eff2cc03f7770e0513a061732ec860ccb241721e40b9d60d6dbb2b0dafee8` | `b5eac9d5dc076b4fb91fc3527de18d23f38f631f4167df5487a3065eeb7c7c07` |
| 172-page source lock | `fbf21f64f13dc22328c4a01c79e427042c3112885073dc32bb0ebd6700f0fd07` | `8d8a43afa4fc101f3735ae57437849d5e2b88a5c9893ea00ec4a296740d7f5a3` |
| Recursive target set | `30e42ca2d085aa6e4b3ea99e537f9e2897864da1463979bb4768d06b8027a3aa` | `3fe768b25f9feaa826846aba0b8185ec21f8ec81beba246af8644f2c5bd52f4a` |
| Agent/Smart City | `7b544d9aa3d74ab1935f44647026fa4ff85c1dacee3d1c284aa52269bfdca395` | `a0c366965541898d6c9f978f938a1fe8fc77fac84c1b992af09f96fc8d5ea9b7` |
| Systems | `0abc81c383a9db122d2ad74c4dbb6c85cc00caf032abd94c4e7d632ce97ff539` | `b4417c11a667bf4a6b2fa8c780f90e5504107c25821e117f6a5adc83af19af93` |
| Calibration/Warehouse | `1bc083b7ef0419a0f6975007cf672c477e9de0d164a7c350976f069199576ade` | `e8aa7045c93cf0ef73e70034dd7d8efedb4f2c5e54153f10008c83eb70911783` |
| Systems broker evidence | `21d6fd0724ce292ab0e09098485d3d12c8f3e357e81253c2e72ffdc07960b5ef` | `9fbd0053aa91910a321c11af1aac846435b44c8ce005221066e3cb99b15064dd` |
| Systems NvStreamer evidence | `968f413829ce9b14efa06f6128258e7ad25cd156bf71a37a5986928abc653e05` | `84b82e19af16b67b74a878764c6ed829719feb373d5e1910b119980353f76a91` |
| Systems performance evidence | `f5095fa0fbd5d26791c6dfe6d153ba97b63b6d46c51a6a09856c0f14bb089cec` | `7b51ddde61aec520944ef9bd425bdab6ed8cf4a141f859a80014924f501749fd` |

The merge plan's canonical JSON SHA-256 is
`7c61cb7569f095c66a8590ef56b323364643899271a460b7c375abbc6adb0fea`.
Its raw file SHA-256 at validation time is
`bcb98e16ed991eb1e92504c1d2031c8d5a1f690cde73509a8b40848eca990a3d`.

## Explicit conflict resolutions

The source merge has ten same-URI resolution groups. Nine reuse an identical
live/Agent source ID. Release notes additionally remap all 13 Systems claim
references from `doc.release-notes` to the live `release-notes-3.2.1` ID.

An independent bundle audit also found one source ID reused for distinct URIs:

- live `video-analytics-mcp-doc-3.2.1` → `video-analytics-mcp.html`
- Agent `video-analytics-mcp-doc-3.2.1` →
  `vss-agent/Video-Analytics-MCP-Server.html`

The plan keeps the live ID and renames the Agent source to
`agent-video-analytics-mcp-doc-3.2.1`. The validator requires its one Agent
claim reference to be remapped and rejects an absent, added, or substituted
claim without an updated reviewed plan.

No new-capability or fixture/vector collision exists. The only approved
multi-enrichment targets are:

1. `api.core.video-analytics-56`: disjoint merge of Agent
   `smart_city_uploads` and Systems `query_families`.
2. `calibration.sdg.workflow`: merge Agent ports/simulator/artifact/output
   claims with Calibration/Warehouse anchor/output claims; resolve `outputs` as
   an ordered unique union and status as `external_optional`, `source_only`,
   `not_applicable`.

Smart City CARLA/Cosmos SDG and TrafficCamNet training records are also pinned
to `external_optional`, `external_optional`, `not_applicable`. The documents do
not provide official Thor-local support evidence for these development tools.

## Validation record

Commands run from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/parity/candidates/wave3/bundle/validate_bundle.py --json

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s deploy/docker/thor-local/parity/candidates/wave3/bundle \
  -p 'test_*.py' -v

python3 -m ruff check \
  deploy/docker/thor-local/parity/candidates/wave3/bundle
```

Observed results:

- validator: PASS, with all exact counts above;
- bundle and merge mutation suite: 37 tests PASS;
- Ruff: PASS.

The mutation suite covers duplicate/non-finite JSON, plan and input hash drift,
path substitution, target drift, recursive/source-lock mismatch, failed fetch
records, source URL substitution, same-URI remaps, same-ID/different-URI rename
and claim accounting, unknown claims, live/cross-package capability collisions,
unapproved enrichment and fixture collisions (including Systems acceptance
fixtures), discrepancy and guardrail collisions, Systems auxiliary evidence
drift, both Video Analytics contract branches, the SDG output union/status
correction, Smart City external-boundary normalization, and count mutation.

## Limits

This evidence does not assert that 276 records have runtime pass evidence. It
merges the records into the live static ledger but does not create executor-ready
oracles. Warehouse runtime qualification also remains bounded by the documented
IGX-THOR 38.5 contract versus this AGX Thor 38.4 host, the current Docker cgroup
driver mismatch, missing runtime assets, and the unsupported single-GPU local
Warehouse agent-VLM topology.

## Final receipt-bound outputs

- ledger: `0dcd9aabc508b79d863da60c6b7ab592dd3f57032037dac750b160f72ff2f9b0`
- manifest: `bd181bea21b053407da4df7767e73496c4defab100d109e4ee0a3e113e42f35a`
- acceptance inventory: `ba7d1b6d81b511e525eaadb79aac54416711d2ed543984847ddb9e9a8df7cce6`
- capability oracles: `afaa785d6f7fb830b92042f61284e363915548573615cdc051e1ca8211a2b54b`
- capability schema: `6bbd5354db37f871a2a912a79a1bb45c477617ef65e54e1fb1a13f0269efad39`
- merge receipt: `7bbefa6fdc0cd8223b0aafdace181526ef5ef5f5fcff17dc192d2d2dbb6eeb5c`

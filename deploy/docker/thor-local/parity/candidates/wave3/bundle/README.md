# Wave 3 bundle and merge plan

This package joins the reviewed Agent/Smart City, Systems, and
Calibration/Warehouse candidates into one fail-closed **planning artifact**. It
does not edit the live capability ledger, create runtime evidence, or qualify a
service on Thor.

`merge-plan.json` pins the exact live ledger, 172-page source lock, recursive
target set, three candidate documents, and the three Systems semantic evidence
documents by both raw-file and canonical JSON SHA-256. `validate_bundle.py`
recomputes the proposed merged counts and rejects input drift, undocumented
source remaps, capability, discrepancy, guardrail, or fixture collisions, and
mutations to the two approved multi-enrichment merges.

## Deterministic live merge

- The pinned 161-capability baseline plus 115 collision-free candidate
  capabilities produces exactly 276 live planning records.
- The 140-URI candidate registry produces 126 claim-bearing live sources; the
  receipt records exactly 14 non-claim exclusions.
- `merge_live.py` accepts only the exact published unmerged state or the exact
  receipt-verified merged state and rejects partial or co-tampered outputs.
- 151 source records collapse to 140 unique URIs. Ten same-URI groups are
  explicitly resolved, including `doc.release-notes` to the live
  `release-notes-3.2.1` ID.
- One same-ID/different-URI conflict is explicitly renamed:
  Agent `video-analytics-mcp-doc-3.2.1` becomes
  `agent-video-analytics-mcp-doc-3.2.1`, including its one claim reference.
- 46 enrichment records target 44 live capabilities. Only
  `api.core.video-analytics-56` and `calibration.sdg.workflow` may have multiple
  contributors.
- The Video Analytics merge preserves both `smart_city_uploads` and
  `query_families`. The SDG merge preserves both output lists as an ordered
  union and applies the Warehouse `external_optional` correction.
- 110 candidate fixture/vector identifiers are unique: 41 Agent, 55 Systems
  acceptance fixtures, seven Systems performance fixtures, and seven
  Calibration/Warehouse vectors. No collision is approved.
- The proposed discrepancy count is 45 (18 live plus 27 candidate records), all
  IDs unique. All ten guardrail IDs are also unique.

All 96 Wave 3 candidate source URLs must exist in both the exact recursive
172-page graph and byte-level source lock. Existing live-ledger evidence may
also reference GitHub, NGC, or repository artifacts outside that documentation
lock; those pre-existing records are retained, not reclassified by this plan.

The optional Warehouse sample bundle remains excluded. Operator-provided video,
RTSP, calibration, model, and configuration inputs remain in scope. CARLA,
Cosmos Transfer, Isaac Sim, SDG, and model-training development workflows remain
`external_optional` unless future official Thor-local evidence supports a
different classification.

## Validate

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/parity/candidates/wave3/bundle/validate_bundle.py --json

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s deploy/docker/thor-local/parity/candidates/wave3/bundle \
  -p 'test_*.py' -v
```

See [EVIDENCE.md](EVIDENCE.md) for the exact pins, counts, and validation
record.

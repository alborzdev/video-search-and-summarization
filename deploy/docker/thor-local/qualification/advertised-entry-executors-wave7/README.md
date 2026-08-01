# Advertised-entry executors: Wave 7

This isolated package accounts for the exact 15 advertised entries left after
Waves 1–6 and the separate detection-mAP candidate.

- 87 original gap-plan entries
- 71 candidate-only entries in Waves 1–6
- 1 separate candidate-only detection-mAP entry
- 11 Wave 7 source/provenance candidates
- 4 user-managed external-attestation blockers

The 11 candidates cover two search-scale provenance/configuration subsets, two
Sparse4D source/configuration subsets, four MV3DT source/configuration subsets,
and three audio source/configuration subsets. They do not execute the required
runtime scale, custom-data multicamera, model, audio, or service oracles. The
four external entries—Slack, AWS/GCS, RAG report generation, and FRAG
retrieval—remain blocker-only because their plan requires authorized external
delivery or retrieval evidence and explicitly rejects source presence or mocks.

The executor reads only digest-locked repository files. It does not write files,
use the Warehouse sample bundle, access credentials or the network, invoke a
subprocess or Docker, load a model, or change service lifecycle state. All 87
official advertised-entry gaps remain open and no `passed_current` promotion or
runtime evidence is produced.

Run from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/advertised-entry-executors-wave7/executor.py \
  --check

PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  deploy/docker/thor-local/qualification/advertised-entry-executors-wave7/tests
```

`inventory.json` locks the gap plan, parity manifest, live official-capability
and capability-oracle ledgers, all six predecessor inventories, the separate
detection-map contract, exact entry/oracle identities, the 15-entry partition,
and every source used by the 11 candidates. The executor confirms that all 87
proposed IDs remain absent from both live ledgers and that every plan oracle is
still open with empty runtime evidence. Both schemas are meta-schema checked and
raw-SHA-bound by `executor.py`.

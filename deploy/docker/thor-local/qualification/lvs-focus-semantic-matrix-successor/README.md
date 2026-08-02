# LVS focus semantic matrix successor

This additive, inert-by-default package supplies the missing deterministic semantic candidate for object, event, and scenario focus. One exact digest-pinned owned MP4 is uploaded once and reused as the source identity for six `/v1/summarize` calls: object-only, event-only, scenario-only, combined target relationship, distractor control, and absent-focus negative.

Each request carries a generated structured-output schema with exact case and caption-source constants. A passing response must bind the same file ID and model, expose a unique response UUID, echo those constants in the structured artifact, return the exact assertion set for that case, provide bounded timestamp evidence for positive assertions, include the required planted markers, and exclude distractor/absent markers where applicable. The distractor control proves the distractor markers are observable in the same owned source instead of merely assuming they are absent.

The complete workflow is reconciled to the frozen 14-request/14-action envelope: five setup observations, six focus calls, then exact delete, full unrelated-file restoration, and final readiness. Receipts contain hashes, counts, and booleans only. They omit origins, paths, resource IDs, model strings, semantic terms, response text, and request bodies.

No runtime receipt is checked in. The candidate remains non-promoting and `executor_ready=false`. The Warehouse sample is excluded.

Safe static and fake-only checks:

```bash
python3 executor.py plan
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_executor.py
```

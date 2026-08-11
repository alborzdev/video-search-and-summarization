# LVS focus semantic matrix successor

This additive, inert-by-default package supplies the missing deterministic semantic candidate for object, event, and scenario focus. One exact digest-pinned owned MP4 is uploaded once and reused as the source identity for six `/v1/summarize` calls: object-only, event-only, scenario-only, combined target relationship, distractor control, and absent-focus negative.

Each request uses the standard NVIDIA structured-VLM response contract. A passing response must bind the same file ID and model, expose a unique response UUID, return the standard summary/event shape, provide bounded timestamp evidence for every returned event, include the requested planted markers, and never assert the planted absent object/event. The distractor control proves the second visible object/event can itself be selected. NVIDIA describes `objects_of_interest` as objects to detect, extract, or watch; it does not promise exclusive suppression of every other visible object, so the oracle does not invent that stronger guarantee.

The complete workflow is reconciled to the frozen 14-request/14-action envelope: five setup observations, six focus calls, then exact delete, full unrelated-file restoration, and final readiness. Receipts contain hashes, counts, and booleans only. They omit origins, paths, resource IDs, model strings, semantic terms, response text, and request bodies.

`runtime-receipt.json` is the sanitized live Thor result produced under the frozen pre-execution contract. It remains explicitly non-promoting until a separate admission step binds it into the canonical capability matrix. The Warehouse sample is excluded.

Safe static and fake-only checks:

```bash
python3 executor.py plan
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_executor.py
```

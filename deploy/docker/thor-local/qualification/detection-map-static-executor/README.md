# Detection mAP static candidate executor

This isolated lane covers exactly the remaining advertised literal
`manifest-gap.spatial-ai-utils.03-detection-map` (`detection mAP`). It emits a
candidate receipt only. It does not edit the parity manifest, gap plan,
acceptance inventory, oracle registry, qualification wrapper, or official
runtime evidence.

The executor performs two complementary checks:

1. It digest-locks the checked-in detection evaluator, JSONL loader, data
   classes, optional dependency declaration, and two end-to-end tests. AST
   checks prove that the production path still calls `accumulate`, `calc_ap`,
   and `add_label_ap`, and that both real loader/evaluator/save tests still
   assert `Person` AP `1.0`.
2. It runs a tiny custom AP semantic oracle twice. The exact fixture contains a
   perfect match (mAP `1.0`) and a center-distance miss outside the `0.5`
   threshold (mAP `0.0`). Exact input, file-output, and output-tree digests are
   enforced, and only executor-owned temporary files are written and removed.

The claim boundary is intentional: this lane does **not** say that the
nuScenes-backed production evaluator or its optional local dependency stack ran
successfully on Thor. It does not prove a service runtime, create runtime
evidence, or promote `passed_current`. No network, Docker, subprocess,
credential, lifecycle, download, or Warehouse sample path exists.

Run it with:

```bash
python deploy/docker/thor-local/qualification/detection-map-static-executor/executor.py
python -m pytest -q deploy/docker/thor-local/qualification/detection-map-static-executor/tests
```

Use `--list` to print the only supported entry or `--case
manifest-gap.spatial-ai-utils.03-detection-map` to select it explicitly.

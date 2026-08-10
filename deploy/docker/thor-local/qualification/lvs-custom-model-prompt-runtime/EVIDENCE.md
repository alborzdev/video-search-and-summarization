# LVS custom-model and custom-prompt retained evidence

The acknowledgement-gated executor produced this evidence on the local Thor
against the pinned VSS 3.2.1 LVS and RT-VLM images. The model-root Compose
projection proved that an alternate `vllm-compatible` checkpoint below
`MODEL_ROOT_DIR` resolves into LVS and RT-VLM, with the RT-VLM bind read-only.
The live container then exposed the same read-only model-root bind while loading
the exact local Cosmos3 checkpoint through its selected model path. RT-VLM
advertised one internal model with `owned_by=custom`, and LVS advertised that
same exact model identity.

## Retained run

The 2026-08-10 run completed in 18.088492 seconds with all 19 HTTP requests and
both semantic actions inside their bounds. The adjacent fake model was rejected
with HTTP 400 / `BadParameters` before inference. The compatible custom prompt
request completed in 16.613295 seconds, processed one chunk, returned a nonempty
video summary, and returned one event containing the required `start_time`,
`end_time`, `description`, and `type` fields. The receipt stores only prompt and
response hashes, not their text.

The single 2.6 MB qualifier-owned MP4 was deleted immediately. The complete LVS
file list, RT-VLM asset statistics, LVS readiness/model/metadata, and both
container identities matched pre-state exactly. Both containers remained
healthy with zero restarts and no OOM.

- Contract SHA-256: `16a1c5ff167774c07e1a9dca057bf15650ff5ae0367db42d7576bfc55322de9b`
- Receipt SHA-256: `48fc2c5515f2ace79992277bd528ee133d6ac4c0712c5653639e1d9efb7ed1a7`
- Official evidence SHA-256: `79269793902ca6a4cb603d4caf99476707233c2dab05435bf0ca9d1eaae191ad`
- Oracle SHA-256: `b153cde4a023f8a18f80966af8feab7ba938b8fdaa5f4237e18b22e7273a9d62`

This evidence qualifies the advertised configuration and prompt/output-shape
contract. It does not claim task-quality validation for every third-party model
that could be placed beneath the model root.

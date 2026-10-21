# Optional binary archive demo

`archive-conveyor-binary.json` is an explicit Verification Config API create
payload for the known short Conveyor fixture. It is not seeded, loaded at
startup, selected by a domain pack, or applied to existing rules. The default
JSON verifier remains unchanged. This preset is for the selected Spark 3.3
Cosmos Nano runtime; its 20-frame budget is not a Thor/Qwen qualification.

It asks whether **any** frame shows a cardboard box on the blue conveyor belt
and requests only YES/NO. Model and endpoint are inherited from the selected
runtime. Frame/token/timeout/temperature settings match the bounded
20-frame archive probe. `do_resize: false` omits the processor resize block and
uses the selected model's native video pixel budget; min/max pixel fields are
inert in this mode and are not a provider cap. No model, memory reserve, retry
policy or concurrency setting changes. The existing runtime must already use verdict parsing, no
pluggable `vlm.response_parser`, and `vlm.use_vlm_media_defaults: false` so the
explicit frame sampling applies. The preset does not change those global settings.

After reviewing the payload, check whether
`GET /api/v1/verification/config/demo_archive_conveyor_binary` already exists.
Create it only when absent; preserve any existing operator configuration:

```sh
curl --fail --show-error --silent \
  --header 'Content-Type: application/json' \
  --data-binary @services/alert/presets/archive-conveyor-binary.json \
  http://127.0.0.1:9080/api/v1/verification/config
```

A conflict means stop and review the existing rule; do not replace it with PUT.
Select category `demo_archive_conveyor_binary` in an explicit archived-video
`POST /api/v1/verification/ondemand` request with the known retained clip's
`info.media_urls` and `info.media_type: "video"`. Do not install a realtime rule
or route live events to this demo category. Keep the current base64 transport,
admission guard and existing terminal polling/sink acknowledgement workflow.

The provider receives no `json_object` constraint. The existing Cosmos parser
returns the same typed incident envelope: YES maps to `confirmed`, NO to
`rejected`, and reasoning is empty. No explanation is fabricated. Empty or
unparseable responses remain `verification-failed`, not a negative verdict.
Global `json_parser` mappings are ignored by the Cosmos format, and neither
parser settings nor those mappings are sent to the provider. Malformed responses
and transport/delivery failures still require the normal failure handling.

The initial capped-resize version failed its positive archive control despite
successful transport, terminal receipts and durable sink delivery. The installed
video processor interprets `size.longest_edge` as a total video-pixel budget:
262144 across 20 frames reduced the source to 64 × 128, losing useful detail. That
failure remains recorded in the dated QA evidence. Changing only `do_resize` to
false corrected the positive control: confirmed with all 19 terminal/stored-sink
assertions passing in 2.34 seconds. The decoder's 20 frames at 608 × 320 fit below
the selected model's native total video budget. The paired empty control also
passed: rejected with all 19 terminal/stored-sink assertions in 2.627 seconds.
This qualifies these two short archived Conveyor controls on the selected
Spark 3.3 Nano runtime. It is an explicit per-category correction, not a global
default change or a general accuracy claim. Both normalized verdicts, terminal
results and durable stored documents were checked. See the
[dated Spark QA record](../../../docs/qa/2026-10-20-vss33-spark.md) for runtime
receipts and limits.
Single-image semantic accuracy, long clips and sustained RTSP remain separate.
When done, delete only this exact category if you created it and its payload is
still unchanged. Keep terminal and stored incident evidence.

Focused offline checks (normal Alert development dependencies, no services):

```sh
PYTHONPATH=services/alert/src python3 -m pytest -q \
  services/alert/test/unit/test_archive_binary_preset.py
```

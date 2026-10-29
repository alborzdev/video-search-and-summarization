# Defense briefing v2 assets

Created 2026-10-22 with the built-in image-generation tool. All four scenes are AI-generated illustrations; none is captured from Isaac Sim or a real defense installation. `prompts.json` preserves the production prompts.

Original files remain under `/home/sparkdev/.codex/generated_images/01a14131-5490-7330-82eb-ed3fb525304d/`:

- hero.png: exec-40313f8a-bac6-4642-9a45-5d5aedc546e4.png
- damage.png: exec-7277347c-37a8-4415-a312-f46deace9f8f.png
- site.png: exec-b669eabf-7c3b-4dac-8df2-cc82be4ec60f.png
- vehicle.png: exec-0870d738-64c3-4f81-ba9f-8eaa7ac62b62.png

The actual Anvil-T5 product asset is reused from `/vision/anvil-t5.png`. Generated concept device depictions are not used.

## Real local inference artifact

`damage-input.jpg` is the submitted 1024×576 RGB JPEG (quality 92). `damage-box-response.json` preserves the actual response from `/api/vision/local-model` for segment / pothole / grounded_by=detect / presence=off. Only the base64 mask bytes are removed from this JSON. `damage-mask.png` is the returned binary mask rendered with a translucent mint color, with no manual shape edits. The input's RGB SHA-256 is in the response. The UI displays the exact submitted JPEG beneath the mask.

Moondream 2 (Photon) → SAM 2.1 Tiny, resident Spark service. Engine 654.225 ms, service 662.262 ms. Single warm request; not a throughput or accuracy benchmark. Mask identifies the depression, not all surrounding damage. No physical measurement is established.

`damage-response.json` preserves the earlier point-guided result with prompt “damaged pavement”: 955.526 ms and a tiny 83-pixel mask. That inadequate mask is not displayed as a successful inspection. The two requests differ in grounding and wording, so their latency is not a controlled comparison.

Person boxes, site zone, event time and workflow states in the briefing are authored examples. Camera-loss/uplink-loss controls are UI simulations. See `docs/defense-ui-implementation.md` for research, limitations and integration work.

## Persistent diorama

`airfield-diorama.png` is the standalone generated architectural scale-model illustration for the connected nine-step story. Original: `exec-8c3233ef-a4f3-4153-95b8-1fbc25e946c1.png` in the same generated-images directory above. The layout concept is `exec-d643f0b9-2816-4b4a-80e1-919040cc4694.png`. Built-in image tool; prompts in `diorama-prompts.json`.

The camera insets remain separate illustrative images; they are not geometrically accurate views synthesized from the diorama. Location pins, sightlines, local-compute connections and cumulative findings are code-native explanatory overlays. The same world persists and pans between chapters. No new real-world detection, calibration or geolocation claim is made by this asset.

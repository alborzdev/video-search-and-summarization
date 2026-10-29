# Photon on GB10: alternate Moondream model tests

October 22, 2026. **Segmentation goal is unfinished.** All inference below ran locally on Spark. No cloud image inference, another segmentation model, VSS model switch, or HTTP Moondream service was used.

## Actual results

| Model / configuration | Image understanding | Segment result | Peak CUDA reserved |
| --- | --- | --- | --- |
| 3.1, GB10 MoE adapter | Prior query/detect test succeeded | Panel and person: box then EOS; no path | 17.35 GiB |
| 3 Preview, GB10 MoE adapter | Query/detect succeeded; blank detector returned no objects | Panel and person: box then EOS; no path. Blank: no object | 17.35 GiB |
| 2, stock Photon | Query/detect succeeded; blank detector false full-frame box | Standard config rejects request: no segment template | 4.45 GiB |
| 2, diagnostic prompt override | Same public weights, no custom MoE | Panel/person/blank: box then EOS; no path | 4.45 GiB |

The diagnostic override uses the official MD3 segment prompt with MD2's shared tokenizer. It does not pretend to add training or vendor support. Installed vendor files were not changed.

Positive images were a generated metal-panel illustration and an existing warehouse person frame. A white image was the negative control. These are functionality checks, not a representative defense inspection evaluation. No semantic accuracy percentage is claimed. All positive segment requests with generated output ended after four output tokens; the only text token was EOS `[0]`. There was no SVG text, parse error or token-limit exhaustion. The missing refiner is therefore not responsible for these empty coarse paths.

Moondream 2 load/warm-up took 25.05 seconds. Its positive detections took 0.99 and 0.48 seconds; descriptions took 2.05 and 1.90 seconds. Preview loaded in 60.53 seconds. Its positive detections took 1.81 and 1.54 seconds; descriptions took 7.18 and 4.15 seconds. Times are single requests under the existing host workload, not sustained throughput. The Preview panel description hit our 48-token description limit. Segmentation used a separate 512-token limit and ended naturally after four tokens.

Minimum host available memory was 36.28 GiB across these tests, above the saved 20 GiB reserve. Guard remained active. Cosmos was temporarily stopped under the user's existing authorization and restored afterward; see recovery.json for verified final status.

## Checkpoints and runtime

- SDK 2.6.1, Kestrel 0.9.1, kernels 0.7.4, native 0.1.8, Torch 2.13.0 CUDA 13, true GB10 SM121.
- MD3.1: revision `1da27e6c2d2f9118de14560df456881dc62d91f3`, SHA256 `26dde16af961d3a486c7b86b9a34fc8487be7917f7e62324b751400ef4d391b4`.
- Preview FP8: revision `5112966d1a723413b1c9a1e8bea272b72e647b35`, SHA256 `699bd3876f9e105440d60a5fe30c26bc33fbdf008f5bd611a3557663b24bd371`.
- MD2: revision `5d6c926f44e26b07957b0dd315bbedcb4c17a5fe`, SHA256 `70a7d94c0c8349eb58ed2d9e636ef2d0916960f321ecabeac6354b8ba3d7403f`.

All file hashes were verified. Model/tokenizer downloads are disabled during testing. Photon usage telemetry is separate, so this is not an air-gap qualification. MD3 execution uses our BF16-compute MoE adapter and is not the optimized native FP8 GPU path. MD2 needs no application MoE patch but still emits vendor fallback warnings for untuned SM121 kernels.

## Why another public model did not fix segmentation

The [engine documentation](https://github.com/m87-labs/kestrel#segment) says local segmentation requires separate weights. The [3.1 maintainer commit](https://huggingface.co/moondream/moondream3.1-9B-A2B/commit/1da27e6c2d2f9118de14560df456881dc62d91f3) removes segmentation from the downloadable model's advertised skills. The [Preview discussion](https://huggingface.co/moondream/moondream3-preview/discussions/31) asks about bringing the API skill to local models; it is not evidence of a released local segmentation checkpoint.

There is conflicting marketing: the [Moondream model lineup](https://moondream.ai/models) lists Segment for MD2. The user also reports prior successful segmentation. These statements must not be dismissed. They do not identify the exact locally downloadable weights used in that prior setup.

A historical source audit found that SDK 0.2.0's segment method was cloud HTTP and did not choose a model ID in its payload. Kestrel 0.0.2 accepted an explicit model path. Versions 0.1.1, 0.2.0, 0.3.0 and 0.4.2 used the same public Preview FP8 file and disabled MD2's segment template. No evidenced downgrade was found that supplies missing segmentation weights. Public moondream-next safetensors is byte-identical to 3.1; downloading it again would not test a new model.

The stored Hugging Face account receives HTTP 403 for `vikhyatk/moondream-next/seg-model.pt` and `moondream/SegHeadRefiner/model.pt`. See access-check.json; no credentials were recorded, access requested or license terms accepted. Access alone would not prove that the segmentation checkpoint matches the current FP8 loader.

## Concrete next requirement

Obtain an authorized segmentation-trained Moondream checkpoint that matches Photon, plus its exact model identifier, tokenizer/config and required Photon version. Prefer the user's previously working local setup if it can be identified. Then rerun the same positive/negative cases and inspect the actual masks before changing VSS. If requesting vendor support, include GB10/aarch64/SM121, these runtime versions, and the distinction between the working MD2 fallback path and MD3's missing optimized MoE kernels.

The unused SAM exploration was removed after the user clarified Moondream-only scope: its helper, weights, source checkout and added packages were removed; no SAM inference or UI integration ever ran. The retained mask renderer only renders Moondream SVG output. Five CPU renderer tests and pip dependency validation passed after cleanup.

Raw logs, memory samples, settings and exit receipts are preserved in each timestamped directory here. Some original exit receipts flag the blank image as an empty mask; the current harness explicitly distinguishes expected absence, and result interpretation above treats Preview's empty blank result as correct. No historic raw receipt was rewritten.

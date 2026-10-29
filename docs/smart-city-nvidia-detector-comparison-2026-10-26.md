# Smart City detector comparison, 2026-10-26

## Decision and scope

Keep RF-DETR Medium and the existing native MV3DT pipeline as the active configuration. The test does not qualify a different live model or establish cross-camera identity accuracy. It compares detector candidates in isolation; it does not run the candidates through native MV3DT. The test did not change active service configuration.

## Labeled-image screening

All candidates used the same 100-image class-stratified COCO road subset and the same ground truth (subset manifest SHA256 `900ab9789a74be6653d8c74519e64349bd5ba37c1104bdd685e40a5f72ea7830`; ground truth SHA256 `af585b52cdb0ccc13c6dbf2e46fbc0f9d61176fbafbb51962b8b03b4e522c188`). COCO AP50:95 is averaged over IoU thresholds 0.50–0.95; higher is better. These are sample-specific results, not full COCO scores or measurements on the simulated city.

| Model and execution | Person AP50:95 | Car AP50:95 |
| --- | ---: | ---: |
| RF-DETR Medium, FP16 TensorRT batch 1, one city class per query | 57.46% | 60.35% |
| NVIDIA TrafficCamNet Transformer Lite ResNet18, FP16-enabled TensorRT | 44.22% | 39.61% |
| RF-DETR Medium, FP32 ONNX Runtime CPU, multi-label baseline | 57.70% | 60.66% |
| NVIDIA PeopleNet ResNet34 deployable quantized ONNX v2.6.3, FP32 CPU execution | 32.61% | Not a supported class |
| NVIDIA classic TrafficCamNet ResNet18, FP32 CPU execution | 19.35% | 10.33% |

The two RF-DETR rows use different inference and query policies; compare the Transformer to the first and the classic grid models to the second. The candidates use their own preprocessing and postprocessing. The Transformer results use NVIDIA TAO DDETR decoding and aspect-preserving Pillow input preparation, approximating but not verified pixel-for-pixel against DeepStream. The DetectNet grid models use direct resizing and deterministic NMS, not NVIDIA's native DeepStream hybrid clustering. The score floor was 0.001 for AP scoring, which is not a live confidence threshold. Neither benchmark measures native MV3DT, track stability, speed, or cross-camera identity.

Transformer and RF-DETR TensorRT comparison: `.spark/city/challengers/nvidia-r18-isolated-20261026-corrected/corpus/comparison-receipt.json`. Classic CPU results and exact evaluator source: `.spark/city/challengers/cpu-evaluation/{people-full,traffic-full}/`. The TensorRT engine build and one-image positive-control receipts are in `.spark/city/challengers/nvidia-r18-isolated-20261026-corrected/`.

The TrafficCamNet two-wheeler class combines bicycle and motorcycle; do not present it as bicycle-only. It does not distinguish bus and truck. PeopleNet is a person detector for this comparison and does not replace vehicle coverage. A model replacement must preserve or explicitly change the app's existing six-class contract.

## Recorded city frames

The two encoded recordings provide 60 JPEGs per camera at approximately 0.5-second intervals (120 total) with a hash-pinned manifest at `.spark/city/challengers/video-frames-20261026/manifest.json`. The original files and extractor source are identified there and alongside it. The file PTS values are per-camera playback times, not a qualified shared capture clock; no independent detection boxes or physical object IDs are annotated. The sampled IoU association diagnostics therefore cannot establish recall, tracking accuracy, fragmentation of real objects, or shared IDs. Equal numeric confidence thresholds are not necessarily equally calibrated across models. Comparing detection counts or diagnostic track lengths alone cannot prove that one detector is better.

The PeopleNet and classic TrafficCamNet frame outputs use ONNX Runtime CPU and the approximate grid/NMS decoder described above. Transformer frame outputs use the isolated TensorRT engine and approximate aspect-preserving preprocessing. RF-DETR frame outputs use FP32 ONNX Runtime and the production city query policy; they can differ from the live FP16-enabled TensorRT pipeline. None uses MV3DT for this replay.

To answer whether a detector improves actual shared IDs, the next experiment needs paired replay with a verified common capture clock, the same native MV3DT configuration and sufficient per-camera and cross-camera identity annotations. Compare class-aware detection metrics and identity metrics on that paired scene, and check performance and class coverage before changing the live detector.

## Runtime and tooling

The Spark user memory guard remained active at the configured 20 GiB reserve; the isolated runs additionally stopped below 24 GiB. The Transformer engine built and ran successfully; the guard receipt records the observed minimum available memory. `tools/smart-city/build_engine.py` now passes TensorRT's workspace size in MiB without a suffix, fixing a command that TensorRT had interpreted as only 2 KiB. Focused unit tests cover the engine command, the evaluators, decode geometry, prediction coverage, and comparison tools. These tests do not prove native DeepStream postprocessing parity.

A visual spot check of the first frame is saved at `.spark/city/challengers/city-detector-first-frame.jpg`: green boxes are person predictions, red boxes are car predictions, and the score threshold is 0.35. It is one unannotated frame, not a measured accuracy result; RF-DETR's other city classes and NVIDIA's two-wheeler class are omitted from this particular overlay. The Transformer produced overlapping person predictions in that frame, and the single-frame inspection should not be used to infer tracking performance.

At threshold 0.35 across both sampled views, the Transformer produced 926 person and 873 car boxes; RF-DETR produced 561 and 665. The frame agreement report found 518 person pairs and 545 car pairs with same-frame IoU at least 0.5. These totals do not distinguish true detections, false positives, duplicate boxes, or missed objects. The simple per-camera IoU diagnostic has median one observation per track for both models and classes; the half-second sampling and missing ground truth make this unsuitable for judging actual tracking. See `nvidia-r18-isolated-20261026-corrected/video/{frame-agreement.json,comparison-0.35.json}` and `cpu-evaluation/rfdetr-vs-{peoplenet,traffic}-continuity.json` under `.spark/city/challengers/` for the reproducible diagnostics. Transformer diagnostic receipts at 0.30 and 0.50 are also retained.

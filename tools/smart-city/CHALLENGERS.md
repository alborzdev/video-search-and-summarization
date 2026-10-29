# Detector comparison and staged challengers

Research/staging date: 2026-10-22. The initial baseline used RF-DETR Small from `rfdetr==1.11.2` at 512 × 512. The current explicit Spark selection is RF-DETR Medium at 576 × 576, with Small retained as the tested lower-cost alternative. Both use the custom DeepStream parser and float RGB/ImageNet preprocessing. Both preserve the pretrained sparse COCO class slots. The implementation is a measured starting point; these checks do not establish a universal state-of-the-art winner.

**Native integration update:** Small and Medium have now each passed a five-minute mixed-rate, two-source RTSP check. The current explicit Spark selection is Medium; its [native receipt](../../docs/qa/smart-city-2026-10-22/medium-native-300s.json) measured source clocks close to wall time and a highest reported RTCP source age of 0.404 seconds. Medium subsequently passed [three actual Ask/export requests during a ten-minute concurrent monitor](../../docs/qa/smart-city-2026-10-22/medium-three-ask-600s.json). Final exact-preview, production UI and endurance qualification have separate gates; see the [as-built status](../../docs/smart-city-as-built.md). Earlier staging descriptions below record the order of work; engine corpus results alone did not authorize this selection.

## RF-DETR Large trial — October 27

The installed `rfdetr==1.11.2` package's current `RFDETRLarge` is the 704×704 model using `rf-detr-large-2026.pth`; it is distinct from `RFDETRLargeDeprecated`. The staging/export/engine/quality/profile helpers now support `large` while retaining the existing batch-one/two corpus gates and target-device build checks. The [comparison receipt](../../docs/smart-city-rfdetr-large-2026-10-27.md) records the measured live and recorded FPS, model identities and qualification limits. The current explicit selection is recorded locally; generic devices still default to Small.

Use `python3 tools/smart-city/model_profile.py --device spark select medium` to restore Medium, then reconnect detections. `select large` selects the staged Large trial after validating its local artifacts and both corpus receipts. The native MV3DT tracker and calibrated camera geometry are unchanged. Export and reference checking use the maintained `tools/smart-city/export_model.py` and `verify_export.py` helpers in the isolated CPU environment. A long-running controller needs its normal service restart after deploying new model definitions so its Python module cache sees the added size.

## Decisions and actual staging state

| Candidate | Why evaluate it | License/source | Actual state and deployment cost |
| --- | --- | --- | --- |
| RF-DETR Small / Medium | Six required road classes; same trained family permits a useful quality/compute comparison | Apache-designated COCO checkpoints in the [pinned official package](https://github.com/roboflow/rf-detr/tree/1.11.2) | Both exported, actual Spark FP16 engines built and checked on a positive traffic frame. Both evaluated on the fixed COCO subset below in FP32 ONNX. The native adapter supports both sizes through generated matching preprocessing/inference profiles; Medium is explicitly selected on Spark. |
| NVIDIA TrafficCamNet Transformer Lite, ResNet-18 `deployable_resnet18_v2.0` | Compact traffic-specific NVIDIA baseline with a supplied DeepStream config | [Official NGC card](https://catalog.ngc.nvidia.com/orgs/nvidia/tao/models/trafficcamnet_transformer_lite/-), [NVIDIA Open Model License](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/) | FP32/FP16 ONNX, labels and config downloaded and SHA256 checked. Native classes are bicycle, car, person and road sign, plus background. It has no separate bus/truck labels and cannot replace six-class analytics unchanged. Graph contains `nvidia:MultiscaleDeformableAttnPlugin_TRT`; CPU ONNX Runtime cannot execute it. A separate TensorRT plugin build/positive control and matched evaluation remain required. No accuracy or Spark speed result is claimed. |
| RT-DETRv4-M, HGNetv2 | Independent current transformer challenger covering the six road classes | [Official repository](https://github.com/RT-DETRs/RT-DETRv4), Apache-2.0 project license | Source pinned at `55fefaaed7efe2a5f72d0a18fd4e05965e35c292`. The official checkpoint is linked through Google Drive. Trusted direct download failed the host certificate-chain check; the Drive connector could read metadata but its 256 MiB download limit is smaller than the 317,911,052-byte file. Weights are unavailable here, so export/inference were not completed. No unverified mirror or TLS bypass was used. |
| YOLO26s / YOLO26m | Strong compact detector family; useful independent challenger if its terms fit the product | [Official models](https://docs.ultralytics.com/models/yolo26/), [export](https://docs.ultralytics.com/modes/export/), [vendor license options](https://www.ultralytics.com/license) | Reviewed, not installed or downloaded. The vendor offers AGPL-3.0 and Enterprise terms and directs proprietary product use to Enterprise. No company license/compliance decision is recorded. This is a conditional evaluation path, not a silently approved dependency. Letterbox preprocessing, contiguous COCO IDs and its chosen end-to-end/raw export mode need a different adapter. |

Only the NVIDIA baseline and RT-DETRv4-M source package were staged as additional challengers. RF Small/Medium are the already integrated family. YOLO was screened but not staged. This is a bounded, practical shortlist, not a claim that every detector has been evaluated.

Publisher timing numbers on a T4 are useful for screening but are not Spark results. RT-DETRv4's [official table](https://github.com/RT-DETRs/RT-DETRv4#-main-results) reports 53.7 COCO AP and 5.91 ms T4 FP16 for M; YOLO26's [official table](https://docs.ultralytics.com/models/yolo26/#performance-metrics) reports its own T4 timings. Those numbers use different pipelines and must not be ranked against this worker's end-to-end playback rate.

## Exact additional-model contracts

**NVIDIA ResNet-18:** input `inputs`, dynamic batch × 3 × 544 × 960; RGB with 1/255 scaling and zero offsets. The supplied config sets `maintain-aspect-ratio=1`, no clustering (`cluster-mode=4`), output names `pred_logits;pred_boxes`, and `NvDsInferParseCustomDDETRTAO`. The [official TAO parser](https://github.com/NVIDIA/DeepStream/blob/main/src/apps/tao_apps/post_processor/nvdsinfer_custombboxparser_tao.cpp) takes the best class for each query, applies sigmoid, ranks up to 200 and discards class zero. It is not the RF-DETR global query/class parser. Ground-truth comparisons must either use its supported class set or explicitly report a separate coarse taxonomy; they must never invent a bus/truck subclass from `car`.

Staged files are in `.spark/city/challengers/nvidia-r18/`. `stage-receipt.json` pins every official artifact and graph signature. Main graph SHA256: `869a317494552773e424ae2228135b3c111052804e22100cb43c0cb2639293c4`; FP16 graph: `c533a2fb51994a7770dbdfb89c93582c91150043a239776ad4f17624d2cf2247`. The custom operator barrier is a deployment task, not evidence of bad detection quality.

**RT-DETRv4-M:** the pinned [official exporter](https://github.com/RT-DETRs/RT-DETRv4/blob/55fefaaed7efe2a5f72d0a18fd4e05965e35c292/tools/deployment/export_onnx.py) uses CPU model construction and the deployed postprocessor. It takes `images` (RGB 0–1, direct square 640 resize) plus `orig_target_sizes` and returns `labels, boxes, scores`. The [deploy postprocessor](https://github.com/RT-DETRs/RT-DETRv4/blob/55fefaaed7efe2a5f72d0a18fd4e05965e35c292/engine/rtv4/postprocessor.py) returns contiguous COCO labels before dataset-ID remapping; boxes are scaled XYXY, not RF-DETR normalized CXCYWH. Original size ordering must follow the official dataset/inference code. Its default exporter creates a batch of 32; a bounded batch-one/two export is preferable for this demo. Current PyTorch/ONNX exporter compatibility still needs a real run after the checkpoint becomes available. Training-time teacher distillation does not imply deploying the teacher model for detection.

## Fixed real-image quality proxy

`coco_road_subset.py` downloads official COCO 2017 validation annotations and only the selected 100 JPEGs, rather than the full image archive. It records the archive, official JSON, selected ground truth and every image SHA256 in `.spark/city/eval/coco-road100/subset-manifest.json`.

Selection is deterministic: revision `ct-city-coco-road-roundrobin-v1`, seed `20261022`. Eligible images contain a positive-area, non-crowd instance of one of person, bicycle, car, motorcycle, bus or truck. Each class's eligible images are ranked by SHA256 of revision/seed/category/image ID. Round-robin class selection chooses unique images until 100 are selected. Anchor quotas are 17/17/17/17/16/16. Other classes in selected images are retained in the official ground truth; evaluation selects only the six road categories. Crowd annotations never qualify an anchor and remain in the ground truth for standard COCO ignore matching.

| Class | Images containing non-crowd examples | Non-crowd objects |
| --- | ---: | ---: |
| Person | 74 | 453 |
| Bicycle | 26 | 52 |
| Car | 47 | 158 |
| Motorcycle | 24 | 62 |
| Bus | 26 | 44 |
| Truck | 31 | 57 |

`evaluate_detectors.py` uses CPU-only ONNX Runtime 1.24.4, four threads, FP32 model I/O, the reviewed resize/normalization, sigmoid global top-300 and a 0.001 score floor for COCO evaluation. This floor differs from the live display threshold. `pycocotools==2.0.11` computes the standard box AP over IoU 0.50:0.95 with max detections 1/10/100. Per-image boxes, scores, aggregate metrics and per-class metrics are retained. The optional coarse taxonomy is a separate score: person, two-wheeler and vehicle. Competing labels for one RF query within one coarse category collapse to the maximum score; that transformation is recorded rather than concealed.

This subset is class-stratified and is not an unbiased sample of all COCO images. It is a paired engineering comparison, not full COCO AP, final elevated-camera performance, night/rain robustness, event precision/recall, tracking quality or map error. It must not be used to tune and then claim held-out generalization. COCO annotations use CC BY 4.0; source-image licenses vary and are preserved in the manifest. Evaluation download does not clear these images for redistribution or booth playback. [Official downloads](https://cocodataset.org/#download), [terms](https://cocodataset.org/#termsofuse), [COCO evaluator](https://github.com/cocodataset/cocoapi/blob/master/PythonAPI/pycocotools/cocoeval.py).

Actual quality results live in `.spark/city/eval/results/rfdetr-small/receipt.json` and `rfdetr-medium/receipt.json`; the table below is updated only from completed receipts.

| FP32 ONNX model | Six-class AP50:95 | AP50 | AP for small objects | Person AP | Bicycle AP | Car AP | Motorcycle AP | Bus AP | Truck AP |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| RF-DETR Small 512 | 55.76 | 79.41 | 32.70 | 54.94 | 34.74 | 56.09 | 55.21 | 79.05 | 54.54 |
| RF-DETR Medium 576 | 57.75 | 79.86 | 34.78 | 57.70 | 36.88 | 60.66 | 56.47 | 81.61 | 53.18 |

Values are percentage points on this subset. Medium improved aggregate AP by 1.99 points, including a 2.07-point increase for small objects, but truck AP decreased by 1.36 points. This supports keeping Medium as a promising candidate, not switching the demo automatically. FP32 ONNX inference and TensorRT engine-only latency are different measurements. The completed CPU runs used the exact same image/GT manifest (`900ab9789a74be6653d8c74519e64349bd5ba37c1104bdd685e40a5f72ea7830`). Original evaluator source is copied into each result directory to preserve its recorded hash.

## Actual Spark TensorRT corpus result

The actual serialized FP16-enabled Small and Medium engines were each run on all 100 preprocessed images at batch one **and** batch two. The runner uses persistent TensorRT 10.16.1.11 execution contexts and CUDA 13.2 Runtime allocations; FP32 input/output tensors, the native engine hashes, decoded output arrays and per-file hashes are recorded. The runs were serial on GB10 with an explicit lease and a 20 GiB reserve floor. Process wall times include loading and file writes and are not inference latency measurements.

| Actual engine | Batch | Six-class AP50:95 | AP50 | AP for small objects | AP change from same-model FP32 |
| --- | ---: | ---: | ---: | ---: | ---: |
| RF-DETR Small FP16 enabled | 1 | 55.719 | 79.621 | 32.705 | −0.042 |
| RF-DETR Small FP16 enabled | 2 | 55.884 | 79.724 | 32.852 | +0.123 |
| RF-DETR Medium FP16 enabled | 1 | 57.856 | 80.490 | 35.673 | +0.106 |
| RF-DETR Medium FP16 enabled | 2 | 57.803 | 80.092 | 35.957 | +0.053 |

All four passed the stated engineering gate of at most one percentage point aggregate AP loss versus the matching FP32 ONNX run. Tiny positive changes are numerical/ranking effects on a small subset, not a claim that FP16 improves the model. These results supported Medium's roughly 1.92-point aggregate advantage at batch two. Subsequent native pacing and combined Ask checks justified its current explicit Spark selection, while Small remains the lower-cost baseline. Engine corpus quality alone does not test tracking, map projection, camera decoding, preview alignment or VLM coexistence; final preview/endurance and scene-specific gates remain separate.

Small engine SHA256: `e3f1143477f5320b45e1dfdb840ed39c1655179ef6444c77581aeaa73b07dc0c`; Medium: `9228a9c88bbde75a867b0ed92bd400da520e9b867baf855ea7343ce3c60866b0`. Quality receipts, per-class differences, source/input manifests and run receipts are copied to `docs/qa/smart-city-2026-10-22/`. Raw arrays remain under `.spark/city/runtime/corpus-outputs/`; predictions and scores are under `.spark/city/eval/results/*-fp16-b*/`.

`evaluate_tensorrt_corpus.py` has three separate commands: `prepare` runs CPU preprocessing, `run --allow-gpu` explicitly allocates GPU resources after lease coordination, and `score` computes CPU COCO metrics and the precision-retention gate. The exact TensorRT Python binding package was downloaded and extracted to `/state/tensorrt-python/root`, rather than replacing packages in the base stack. Its hash is `209d60f3c4a43658efdcf359bf03212c50a987eb57f4931a618e5811b95cc5a2`. The runner binds the documented [TensorRT execution APIs](https://docs.nvidia.com/deeplearning/tensorrt/latest/inference-library/python-api-docs.html) and [CUDA Runtime memory APIs](https://docs.nvidia.com/cuda/cuda-runtime-api/group__CUDART__MEMORY.html). CPU scoring controls verify perfect and wrong-box cases, changed output rejection and duplicate-image receipt rejection. These controls do not substitute for the recorded actual-engine runs.

## Reproduce CPU checks

Use an isolated CPU environment with ONNX Runtime, Pillow, NumPy, PyTorch/torchvision and pycocotools. Do not change the main VSS packages. The created `vss-city-challengers` container is limited to four CPU cores and 12 GiB, with CUDA visibility disabled.

```sh
python tools/smart-city/coco_road_subset.py --help
python tools/smart-city/stage_challengers.py --directory .spark/city/challengers/nvidia-r18 --inspect-graph
python tools/smart-city/evaluate_detectors.py \
  --onnx .spark/city/models/rfdetr-small/rfdetr-small.onnx --model rfdetr-small \
  --subset .spark/city/eval/coco-road100 --output .spark/city/eval/results/rfdetr-small --threads 4
```

CPU tests cover deterministic/non-crowd subset selection, class mapping and pixel boxes, non-finite output failure, coarse-query deduplication, and a real pycocotools perfect/wrong-box control with crowd ignore. They do not qualify the additional models' GPU plugins or a live city deployment.

## Qualified native model profiles

`model_profile.py` selects and prepares the Small/Medium native profiles without importing GPU libraries or starting a worker. With no saved selection, the selected size remains Small. `select medium` is explicit and succeeds only when the local engine and ONNX match the artifact lock, the Medium engine matches its device-local build receipt, and both batch-one and batch-two actual FP16 corpus receipts pass their retention gates. Quality receipts must link to matching actual target-device run receipts, the same six road classes and the same dataset. Missing, changed, wrong-device or failed evidence stops selection. The original Spark Small engine has no historical build receipt, so that existing baseline uses its pinned observed engine hash and actual corpus evidence; Medium and every Thor profile require a build receipt. Spark engines and quality receipts cannot qualify Thor.

```sh
# Read the explicit current selection (Medium on the prepared Spark); unselected devices default to Small.
python tools/smart-city/model_profile.py --device spark show
# Prepare a bounded Medium test while retaining the current selection.
python tools/smart-city/model_profile.py --device spark config --size medium
# Persist a selection after its separate native integration check.
python tools/smart-city/model_profile.py --device spark select medium
# Generate the selected profile for launch.
python tools/smart-city/model_profile.py --device spark config
```

The Python APIs are `selection_name(root, device)` (name only, no readiness claim), `selected_model(root, device)` (validated metadata), `select_model(root, device, size)` (atomic selection), `config_for_launch(root, device)` (selected native configs), and `config_for_model(root, device, size)` (candidate configs without selection). Metadata includes `size`, `resolution`, `enginePath`, `onnxPath`, hashes and `modelRevision`. Generated profiles add `hostConfigDir`, container `configDir`, `configManifest` and `nativeArgs`.

Configs are generated under `.{device}/city/state/model-config/{size}-{engineHashPrefix}/` and mounted as `/state/model-config/...`. The generator updates inference engine/ONNX/label paths, preprocessing network shape and width/height to 512 or 576, preserves the six labels and CUDA NvDCF configuration, and records source/generated file hashes. It uses the worker's exact existing flags `--config-dir` and `--model-revision`; the revision contains size and full engine SHA256. Source image configs are not edited. A selected model change takes effect when the controller launches the next worker; this helper does not hot-swap a running pipeline or assert native throughput qualification.

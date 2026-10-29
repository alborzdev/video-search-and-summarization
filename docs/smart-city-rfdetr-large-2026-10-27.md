# RF-DETR Large versus Medium on Spark — October 27, 2026

**RF-DETR Large is running in the simulation for visual review.** It uses the current `RFDETRLarge` from the installed `rfdetr==1.11.2`, with 704×704 input and the official `rf-detr-large-2026.pth` checkpoint. Medium uses 576×576. This is distinct from the older `RFDETRLargeDeprecated` variant. [Official model table](https://rfdetr.roboflow.com/latest/learn/run/detection/).

The comparison retains every-frame inference, the single native MV3DT tracker, calibrated 640×384 tracker input, 960×540 cameras/mux, CPU decode, 10 ms mux wait, exact native SEI frame clocks, full-resolution previews, the 30 FPS preview ceiling and existing rules. The saved 20 GiB guard remains active. No simulator/render setting was changed.

## Measured FPS

Four alternating live windows ran Medium → Large → Medium → Large. Each captured 30 samples over approximately 29.15 seconds after a ten-second startup wait. Both cameras remained live with stable source sessions and zero preview POST failures in every sampled window.

| Metric, average per camera | Medium | Large | Observed change |
| --- | ---: | ---: | ---: |
| Live analyzed FPS | 13.04 | 12.88 | −0.16 FPS, approximately 1.2% |
| Exact preview publishes/s | 12.55 | 12.18 | −0.37 FPS, approximately 2.9% |
| Unpaced recorded pipeline capacity | 142.26 | 105.07 | approximately 26% lower |

The live difference is small compared with variation between windows. Medium analyzed 12.86–13.20 FPS per camera; Large analyzed 12.63–13.14. These short changing-scene windows do not establish a precise causal 1.2% penalty or a speed gain in one particular window. Preview publish rate measures server delivery, not browser presentation rate. Source-frame-age p95 remained below 0.24 seconds in these windows.

The recorded test used the same retained two-camera footage, pinned engine/configs, one native MV3DT tracker, isolated MQTT topics, no HTTP posting or preview branch, and disabled file pacing. Each run processed 600 frames. Per-camera FPS excludes startup and the first 50 observations, measuring the following 200 observations using an external 10 ms file-arrival sampler. Medium ran at approximately 135/149 FPS per camera, Large at 107/103. The approximately 1.3–1.9 second measured spans are short throughput probes, so interpret this as roughly a quarter less spare processing capacity, not a production camera-rate promise. The independent file clocks do not qualify cross-camera physical identity accuracy.

Large therefore has substantially lower maximum processing capacity while remaining well ahead of the current live feed rate. No inference interval, source/frame drop or reduced tracker update rate was used to obtain the result.

## Export and precision checks

The checkpoint was downloaded from the official Google storage URL and verified against the installed upstream MD5 `5cb72153541cbcb9aa6efa26222acc75`. Checkpoint SHA256 is `0f4e20e19a99c0f8a62b5685f57f6c8b5c371c59081feda6752a0561a79ccf38`; ONNX SHA256 is `158503ef9885c77084b796296da2aeefb5e24f6a61a025e67e9afdb1b4b94030`.

The ONNX export passed reference-model numerical checks on a positive traffic frame at batches one and two. Its native contract remains FP32 RGB/ImageNet input, sparse COCO logits and normalized boxes. A new FP16-enabled TensorRT engine was built on this GB10 using the existing DeepStream/TensorRT environment, with dynamic batch 1–2 and optimization batch 2. Engine SHA256 is `4434b077b3602ae2c3d9e950e5c36fc718de07b7c8444a9a4fbc7e4451b90ff6`.

Both actual Large FP16 corpus runs passed the existing ≤1 percentage-point AP loss gate versus its own FP32 ONNX reference on the pinned 100-image road-user proxy:

| Actual batch-two engine | Six-class AP50:95 | Small-object AP |
| --- | ---: | ---: |
| Medium FP16 | 57.80 | 35.96 |
| Large FP16 | 59.48 | 40.59 |

Large's FP32 reference scored 59.61 AP. These are engineering proxy results, not full COCO or labeled simulation/tracking accuracy. They support trying the larger detector but do not prove fewer shared-ID errors or SUV class flips.

One stricter standalone single-image FP16 check did **not** pass its 0.03 confidence-difference threshold: a person confidence changed by 0.0591, with IoU 0.9646 and the same ten selected detections. That artifact is retained; its failed run produced no Large standalone latency result. The reported FPS comes from the separate native pipeline and live comparisons. The existing corpus precision gate and standalone confidence threshold were not relaxed.

## Implementation and active state

The existing staging, export, reference verification, engine building, corpus evaluation and native model-profile helpers now recognize `large`. Large requires a device-local build receipt and valid actual-engine quality receipts at **both** batch sizes, with the existing artifact/hash checks. Focused profile/build controls passed 14 tests, including 704×704 config generation and refusal when build/quality evidence is absent. The controller was restarted through its normal service to load the added model definition.

The selected size is now `large`; Medium remains staged. To restore Medium, select it and reconnect detections:

```sh
python3 tools/smart-city/model_profile.py --device spark select medium
curl -fsS -X POST http://127.0.0.1:9190/api/v1/detections \
  -H 'Content-Type: application/json' -d '{"action":"restart"}'
```

Raw commands, source snapshots, original selection/config, build logs, successful corpus receipts, the failed standalone check, recorded observations, arrival samples and live windows are retained in `.spark/city/runtime/rfdetr-large-20261027/`. Public summary and final live verification are under `docs/qa/smart-city-rfdetr-large-2026-10-27/`. Both camera overlays and the map are verified after the final Large selection. This remains a bounded prototype trial.

[Measured comparison](qa/smart-city-rfdetr-large-2026-10-27/summary.json) · [Active model verification](qa/smart-city-rfdetr-large-2026-10-27/active-verification.json) · [Large running in the live view](qa/smart-city-rfdetr-large-2026-10-27/large-live.jpg). The browser reported no console warnings or errors.

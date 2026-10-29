# First measured Spark segmentation comparison

2026-10-22. **Use SAM 2.1 Tiny as the provisional quality default; keep EdgeTAM as the speed option.** EdgeTAM was faster in every paired median, but its aircraft mask was materially less accurate. This recommendation is based on a small functional comparison, not a general model ranking.

Source: [aggregated results and provenance](benchmark-summary.json), built directly from the completed [SAM2.1 Tiny log](/home/sparkdev/vss/.spark/local-segmentation/runs/20261022T175146Z-sam2.1-tiny/inference.jsonl) and [EdgeTAM log](/home/sparkdev/vss/.spark/local-segmentation/runs/20261022T175205Z-edgetam/inference.jsonl). Both processes exited successfully.

## What was tested

Each model ran **nine prompt cases**: three annotated targets with both an oracle box and an oracle point (**six scored cases**), plus three manually prompted visual examples without ground truth. Each case had two warm-ups and ten timed repetitions, followed by ten separate cached-image prompt calls. The same images and prompts were verified across models.

These were mask-model tests. **Moondream did not provide the prompts.** The annotated targets came from `moondream/refcoco-m` validation, revision `45686f0eb7980ed4b70d3d5480a198775a26b4c1`. The blank negative control had no spatial prompt and was skipped by both models. These runs therefore establish neither end-to-end grounding accuracy nor absence detection.

## Measured latency and memory

| Measurement | SAM 2.1 Tiny | EdgeTAM |
|---|---:|---:|
| Range of full-image case medians | 39.30–80.69 ms | 24.05–31.03 ms |
| Aircraft, box prompt: median | 46.71 ms | 27.65 ms |
| Large panel image: median | 46.06 ms | 31.03 ms |
| Worst observed full-image call | 91.15 ms | 168.38 ms |
| CUDA allocator peak reserved | 0.637 GiB | 0.420 GiB |
| Model-load call, including checks/imports | 2.03 s | 1.89 s |

Full-image timing includes image encoding and one prompted mask. It excludes Moondream, camera ingestion, HTTP delivery and UI drawing. CUDA allocator memory is not total process or unified-memory use. Sampled system available memory stayed above 56 GiB during both runs.

**Tail latency needs more measurement.** EdgeTAM's aircraft-box case reached 94.90 ms, and two panel repetitions reached approximately 168 ms. The recorded `p95_observed` is simply the maximum of ten samples under this benchmark's indexing rule. It is not a reliable production p95 estimate. No frame-rate or continuous-video capacity claim follows from these runs.

## Mask quality on the three annotated targets

IoU measures overlap with the supplied annotation. Prompts here were derived from ground truth.

| Target | SAM Tiny box | EdgeTAM box | SAM Tiny point | EdgeTAM point |
|---|---:|---:|---:|---:|
| Left person | 97.37% | 97.21% | 96.78% | 96.96% |
| Real cat | 98.53% | 97.93% | 97.93% | 95.75% |
| Front aircraft | **97.75%** | **86.09%** | **96.47%** | **87.29%** |

The aircraft result drives the quality recommendation. With the box prompt, EdgeTAM included 10,527 false-positive pixels while missing 1,381 target pixels. Its high recall did not prevent excess background in the mask. This is evidence about this image; three targets cannot establish aircraft-wide or inspection accuracy.

Every repeated case produced one unique mask hash per model. The three manual examples have no IoU score, and a visually plausible mask must not be presented as measured accuracy.

## Reproducibility and remaining work

Both used Torch 2.13.0, TorchVision 0.28.0, FP32 weights with BF16 autocast, no image-encoder compilation, and no stability fallback or hole/sprinkle cleanup. Checkpoints loaded strictly against recorded hashes. The summary preserves full source receipts and SHA256 hashes of the raw logs, settings and fixture lists.

Both runs emitted a non-writable NumPy input warning. They are successful runs with that warning, not warning-free qualification receipts. Application adapter/benchmark file hashes were not recorded in these original runs; later source changes must not be attributed to them.

Next, use actual Moondream boxes and negative controls to measure the complete pipeline. Repeat under representative live load before selecting latency targets. Thor remains untested by these two receipts.

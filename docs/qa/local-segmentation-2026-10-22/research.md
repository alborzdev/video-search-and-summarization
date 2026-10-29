# Local promptable segmentation: Spark and Thor

Research date: 2026-10-22. Scope: turn a Moondream point or box into an image mask. No GPU benchmarks, service changes, installations, or checkpoint downloads were performed for this research. Artifact sizes and SHA256 values in `research.json` come from publisher metadata, not local weight verification.

**Test SAM 2.1 Tiny first and EdgeTAM second.** This is a ranking of practical implementation choices, not a claim that either is the fastest on GB10. Keep **EfficientViT-SAM-L0** as the TensorRT speed challenger. We should select the winner from matched image/prompt tests on Spark, then test separately on Thor.

## The two immediate candidates

| Candidate | Why it belongs in the first comparison | Published evidence and its limit |
|---|---|---|
| **SAM 2.1 Hiera Tiny** | Official, ungated checkpoint; mature point/box image predictor; useful quality baseline; supports video later. | 38.9M parameters; 91.2 FPS on A100 for compiled video inference. This is not Spark image-request latency. |
| **EdgeTAM** | Same style of image API with a much smaller checkpoint; designed for constrained devices; ungated code and weights. | 150.9 FPS compiled A100 video; 40.4 FPS image segmentation on iPhone 15 Pro Max. Its one-click SA-23 score is lower than the larger SAM 2.1 comparator. Neither timing predicts Spark performance. |

Sources: [Meta SAM2 model table](https://github.com/facebookresearch/sam2#model-description), [EdgeTAM model tables and license](https://github.com/facebookresearch/EdgeTAM#evaluation), [EdgeTAM paper](https://openaccess.thecvf.com/content/CVPR2025/papers/Zhou_EdgeTAM_On-Device_Track_Anything_Model_CVPR_2025_paper.pdf).

Both projects explicitly license code and checkpoints under Apache 2.0. Both return masks from spatial prompts; they do not replace Moondream's language understanding. The recommended pipeline is **Moondream detect/point → pixel coordinates → promptable segmenter → mask, outline, and measured area**. Run the image encoder once per frame and reuse its features for additional objects.

### Exact first download

- Code: [facebookresearch/sam2 at `2b90b9f`](https://github.com/facebookresearch/sam2/tree/2b90b9f5ceec907a1c18123530e92e794ad901a4).
- Weight: [official `sam2.1_hiera_tiny.pt`](https://huggingface.co/facebook/sam2.1-hiera-tiny/resolve/de431c4043854a71d8101e17995dfe596bf101a5/sam2.1_hiera_tiny.pt), 156,008,466 bytes; publisher SHA256 `7402e0d864fa82708a20fbd15bc84245c2f26dff0eb43a4b5b93452deb34be69`.
- Config: `configs/sam2.1/sam2.1_hiera_t.yaml`.
- API: `build_sam2` → `SAM2ImagePredictor.set_image` → `predict(point_coords=..., point_labels=..., box=...)`.
- Required stack: Python ≥3.10, Torch ≥2.5.1, matched TorchVision ≥0.20.1, NumPy, Pillow, tqdm, Hydra, iopath. [Official setup](https://github.com/facebookresearch/sam2/blob/2b90b9f5ceec907a1c18123530e92e794ad901a4/setup.py).

### Exact second download

- Code: [facebookresearch/EdgeTAM at `7711e01`](https://github.com/facebookresearch/EdgeTAM/tree/7711e012a30a2402c4eaab637bdb00a521302c91).
- Weight: [official `edgetam.pt`](https://huggingface.co/facebook/EdgeTAM/resolve/14d7ecc48c656b94e5184519f698cd5386c5a2bf/edgetam.pt), 56,116,523 bytes; publisher SHA256 `ed2d4850b8792c239689b043c47046ec239b6e808a3d9b6ae676c803fd8780df`.
- Config: `configs/edgetam.yaml`; uses its own fork of `SAM2ImagePredictor`.
- Its setup requires Torch ≥2.3.1 and TorchVision ≥0.18.1 plus SAM-style helpers. **It also imports `timm`, which setup omits.** Its backbone constructor requests `repvit_m1.dist_in1k` with `pretrained=True`, so a redundant backbone download can occur before loading EdgeTAM weights. Stage that dependency, or explicitly avoid redundant initialization only after checking complete checkpoint coverage. [Setup](https://github.com/facebookresearch/EdgeTAM/blob/7711e012a30a2402c4eaab637bdb00a521302c91/setup.py), [backbone source](https://github.com/facebookresearch/EdgeTAM/blob/7711e012a30a2402c4eaab637bdb00a521302c91/sam2/modeling/backbones/timm.py).

**Keep their environments separate:** both install the `sam2` namespace. Start with their optional connected-components CUDA extension disabled (`SAM2_BUILD_CUDA=0`); ordinary image mask inference can run without it. This avoids making an old custom extension the first Blackwell integration obstacle.

## The other candidates

| Model | Assessment |
|---|---|
| **EfficientViT-SAM-L0** | Strongest published Jetson lead: 8.2 ms at 512×512/batch 1 in its model table, 45.7 COCO mask AP using detector boxes, and official encoder/decoder ONNX/TensorRT exports. The repository ended maintenance in September 2025. Its broad requirements include unrelated training/demo/generation packages; isolate a minimal inference path. The table does not establish whole-application latency or Spark/Thor speed. [Official model/deployment guide](https://github.com/mit-han-lab/efficientvit/blob/master/applications/efficientvit_sam/README.md), [maintenance notice](https://github.com/mit-han-lab/efficientvit). |
| **EfficientTAM-Ti** | Public Apache weights; approximately 18M parameters; 1024 and separately trained 512 variants. Worth a later comparison. Setup pins old Gradio/HF packages unnecessarily for our use. The paper's faster `Mobile` claim has no clearly named matching checkpoint in the inspected official manifest. Do not assign its speed to another variant. [Repository](https://github.com/yformer/EfficientTAM), [official weights](https://huggingface.co/yunyangx/efficient-track-anything/tree/main), [paper](https://openaccess.thecvf.com/content/ICCV2025/papers/Xiong_Efficient_Track_Anything_ICCV_2025_paper.pdf). |
| **MobileSAM** | Small, accessible older baseline, but not the strongest quality/speed candidate. The README's 12 ms GPU result lacks enough hardware detail for our comparison. [Official source](https://github.com/ChaoningZhang/MobileSAM). |
| **NanoSAM** | Useful NVIDIA TensorRT alternative: published full-pipeline 8.1 ms on AGX Orin and 27 ms on Orin Nano, at 0.706 COCO box-prompt mIoU. Its mixed-precision recipe uses FP16 encoder and FP32 decoder. Older TensorRT/torch2trt integration needs checking on Spark/Thor. [NVIDIA source](https://github.com/NVIDIA-AI-IOT/nanosam). |
| **Efficient-SAM2, 2026** | Sparse routing/memory retrieval uses temporal information. Adds bypass configuration and is primarily a continuous-video optimization; not the simplest first replacement for one image mask. [Official implementation](https://github.com/jingjing0419/Efficient-SAM2). |
| **TinySAM 2, 2026** | Interesting memory compression paper; no verified official code/checkpoint download route found in this audit. [Paper](https://arxiv.org/abs/2605.18013). |
| **SAM 3 / 3.1** | Newer, but not a permissive lightweight substitute: gated weights, custom license, larger concept-segmentation stack. SAM3.1's ~7× claim is for 128 objects on H100. The license has ITAR/prohibited military end-use terms relevant to this project's deployment review. No legal eligibility conclusion is made here. [Release](https://github.com/facebookresearch/sam3/blob/main/RELEASE_SAM3p1.md), [license](https://github.com/facebookresearch/sam3/blob/main/LICENSE). |

## Spark/Thor feasibility and acceptance test

The installed Photon environment reports ARM64, Torch 2.13.0 and Triton 3.7.1, but lacks TorchVision, timm, Hydra and iopath. These checks read package metadata only. **Do not let a generic install replace the working CUDA Torch build.** A matched ARM64 TorchVision build is the main packaging dependency. The recommended models use normal Torch operations; that makes them plausible on GB10 without Photon's unavailable native MoE kernels, but compatibility is not yet proven by this research.

Spark GB10 is SM12.1; Thor T5000/T4000 is SM11.0. Rebuild/validate optimizations on each target instead of transferring a compiled engine. [NVIDIA architecture table](https://developer.nvidia.com/cuda/gpus).

First compare identical images with hand-selected prompts. Then compare the actual Moondream-generated boxes/points. This separates grounding mistakes from segmentation mistakes. Record cold load, warm image-encoding time, prompt-decoder time, end-to-end request p50/p95, and resident/peak memory. Include one and ten objects, thin features, small distant objects and partial occlusion. Compare precision modes before compiling. Claim “faster” only from the complete **Moondream + mask** path, not decoder-only timing.

The installed Moondream package versions are SDK 2.6.1 and Kestrel 0.9.1; the separately downloaded Kestrel 0.9.2 wheel was inspected for the release audit. No new reliable local segmentation checkpoint route was found beyond the [existing audit](../moondream-spark-2026-10-22/advertised-segmentation/upstream-evidence.md). Denied gates were not retried. Moondream remains useful for detection, points and descriptions; a separately measured segmenter can supply masks without depending on the uncertain SVG generation path.

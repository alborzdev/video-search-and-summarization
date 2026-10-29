# Segmentation protocol red-team — October 22, 2026

The partial worker and box masks are **complete, unrefined model outputs**, not paths cut short by our parser or token budget. Our strongest remaining error of interpretation would be comparing these forced coarse paths with Moondream's advertised final segmentation result. This audit does not establish that the correct local segmentation release is unavailable, or that refinement would repair these examples.

## Tests that can already be ruled out

The [paper, Appendix A.1–A.2](https://arxiv.org/html/2604.02593v1#A1) describes image-prefix tokens, segment mode, optional spatial references, object text, answer, box coordinates/size, then an optional SVG delimiter and path. Coordinates use bin/1024; sizes use the exponential mapping with denominator 1023. Path integers use a 960-unit box-relative coordinate frame. It describes a coarse path stage followed by learned mask refinement. Our independent decoder implements that sequence; our saved runs omit the refiner.

| Assumption checked | Evidence and result |
| --- | --- |
| Point hints request a small part of an object | No. The [official API](https://docs.moondream.ai/skills/segment/#spatial-references) defines points as object-location hints and boxes as regions containing the object. Combining the text `person` with a point is an explicit example. Our point is inside the warehouse worker. |
| The object name accidentally became a query instruction | No. The reference decoder uses `case['object']`; the cases' unused `prompt` strings are only for query controls. Installed SegmentSkill uses the same object field and spatial token order. |
| SVG coordinates should be full-image coordinates | No. [Official rendering instructions](https://docs.moondream.ai/skills/segment/#using-the-svg-path), installed `seg_refiner.svg_from_path`, and our renderer all translate and scale a box-relative path with `preserveAspectRatio="none"`. |
| The parser dropped part of the worker | Saved token replay disproves this for the completed worker output. Installed Kestrel and independent decoders produce identical text-token lists; their rasterized binary masks are identical. |
| Numeric formatting explains the box error | Installed parser rounds to three decimals; the independent parser retains more precision. Their box masks differ in only five binary pixels, with IoU 0.999463. Both cover the same stack region. |
| The worker hit a token or context limit | No. The reference worker finishes after 84 tokens, box after 61. Both explicitly end with `z`, observed delimiter 11, and EOS. Neither has a clipped bounding box. The panel is a separate budget-limited failure. |
| A factor-of-two, swapped-axis or missing affine transform caused the partial worker | No such mismatch was found. The saved worker bbox is already narrow before rasterization, and the emitted curve stays in that box's vicinity. |

The CPU replay and source hashes are in [protocol-audit.json](protocol-audit.json). Reproduce without a model or GPU:

```bash
CUDA_VISIBLE_DEVICES='' .spark/moondream-photon/venv/bin/python docs/qa/moondream-spark-2026-10-22/advertised-segmentation/protocol-audit.py
```

## What the worker actually demonstrates

The original warehouse image is 640×360; it was not downscaled by the 1024-pixel thumbnail limit. Ordinary detection gives horizontal bounds 0.3691–0.4473. Segmentation's predicted box gives 0.3750–0.4297, only about 70% of that width. Its completed mask has raster bounds `[238,112,273,222]`. The right side is missing in the prediction before the rendering step. This supports a grounding/coarse-mask problem, rather than a display problem. The detector box is a comparison, not ground truth.

The `cardboard box` point is in a tightly packed stack. Its completed mask has bounds `[401,185,517,271]` and includes parts of multiple boxes/gaps. This is not an adequate single-instance accuracy fixture. A generic noun plus a point is valid input, but does not make the prediction correct.

## Concrete alternative hypotheses and falsifiable checks

1. **The advertised result includes a missing refinement stage.** Current [API streaming documentation](https://docs.moondream.ai/skills/segment/#streaming) distinguishes coarse path chunks from the final refined path. Installed `SegmentSkillState.finalize` invokes the refiner only after a nonempty valid coarse path; the refiner uses the image and coarse mask and can return a new bbox. If the exact compatible Moondream refiner and its legitimate access become available, replay the *saved* worker/box coarse paths through it and score against annotated masks. This needs no new language-model generation. Improvement would support this explanation for boundary quality. It cannot explain or fix the default box-then-EOS result, because that never reaches refinement. Do not assume the refiner can repair a badly grounded region.
2. **The test set is too ambiguous/small to establish segmentation quality.** The worker is only about 50 pixels wide, and the boxes touch. Use one fixed, officially annotated referring-expression image to separate protocol failure from this scene's difficulty. A testable candidate is RefCOCO-M validation image 458827, sample 424581, expression `person on left`, at dataset revision `45686f0eb7980ed4b70d3d5480a198775a26b4c1`. Its 500×294 image has a supplied COCO RLE mask. Run the exact supported checkpoint first with text only, then with one point inside that same ground-truth mask. Record raw/default termination, coarse IoU, final/refined IoU and checkpoint identity separately. This is a conformance fixture, not a promised passing example. No model inference or image download was performed for it here.
3. **The tested public artifact is not the artifact behind the advertised result.** The [segmentation product FAQ](https://moondream.ai/skills/segment) currently describes the downloadable capability as pending and calls the preview cloud-only. Other official local instructions conflict with that statement; see the accompanying upstream audit. The decisive evidence would be an exact compatible checkpoint/refiner identifier plus an input/prompt and expected local output. A generic capability list or alias is insufficient. Do not infer a private language-model checkpoint merely from the phrase “separate model weights.”

Agreement between Photon and independent PyTorch excludes a Photon-only explanation for the observed failure, but both tests share the cached FP8 checkpoint. The [prior checkpoint comparison](../segmentation-diagnosis/checkpoint-comparison.md) substantially weakens the theory that the public BF16 export is different: six complete nonquantized tensors and five expert rows match. It is still a sample comparison, not an exhaustive weight proof. Downloading the whole export without new distinguishing evidence is not the next justified test.

## Official fixture search and limits

Inspected public repository trees on this date: Kestrel `8e6fb899bb8a076f3235b6a5ab832a78c031c77b`, moondream-python `3a5a59353ef909c8e9f7b68f8c87275123b80bf0`, moondream-examples `69a9276ab98504206dccf4a0e184d772f128696b`, and moondream `6eccfceaf1aaff804a67cd157193a6f744fa2bdc`. No reproducible segmentation fixture tying an image, exact prompt, expected SVG, and downloadable checkpoint was found in these inspected locations. The SDK's `test_local.py`/`test_cloud.py` do not supply such a golden segmentation output; the examples repository's saved results are car detections.

[RefCOCO-M](https://huggingface.co/datasets/moondream/refcoco-m/tree/45686f0eb7980ed4b70d3d5480a198775a26b4c1) supplies actual image-level annotations and evaluation expressions. Its bbox format is COCO pixel `[x,y,width,height]`, unlike the API's normalized corner format; convert it before using it as an input hint. Its mask is COCO RLE with size `[height,width]`, not an SVG. The identified example's bbox is `[13.21,1.12,183.67,260.97]`; a bbox-center point should not be assumed to be inside its foreground mask.

No GPU inference, service changes, model downloads, cloud-image uploads or vendor messages were performed in this audit.

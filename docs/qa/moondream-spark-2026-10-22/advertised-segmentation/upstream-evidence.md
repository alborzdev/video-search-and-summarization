# Advertised Moondream segmentation: upstream evidence

Checked 2026-10-22. Primary sources only. Companion [JSON](upstream-evidence.json) records package hashes, checkpoint metadata, dates and source URLs. No GPU execution, installation, large weight download, access request or external message was performed for this audit.

## Finding

The public instructions conflict. We did not find a current, authoritative artifact manifest that identifies the exact segmentation checkpoint and compatible Photon version needed to reproduce the advertised local example. The default checkpoint mappings are known; a reliable alternative segmentation release is not.

The strongest new evidence is an upstream occurrence of the same symptom on supported hardware. Moondream maintainer `vikhyat` authored and merged the SDK2.0 release PR on August3. Its installed-wheel H100 verification used Kestrel0.5.0, kernels0.4.9 and native0.1.6, with AOT-only execution. The PR states:

> The selected MD3 segmentation smoke prompt returned a bbox and no SVG tokens in the raw Kestrel skill result.

Ordinary and streamed calls agreed. The PR does not identify the image, prompt or exact MD3 checkpoint path. This establishes one upstream occurrence before our Spark work; it does **not** establish that all H100 segmentation requests fail. [Release PR15](https://github.com/m87-labs/moondream-python/pull/15)

## What the current sources say

| Primary source | Statement or behavior | What it establishes |
|---|---|---|
| [Local quickstart](https://docs.moondream.ai/running-locally/) | Initializes `md.photon("moondream3.1-9B-A2B")`, then calls `.segment(image, "person")`. | The user's expectation of ordinary local segmentation is supported by the documentation. |
| [Photon updates](https://moondream.ai/photon/updates) | August3 Photon2.0 advertises MD3 masks on H100. | A local capability claim, without a distinct checkpoint identifier. |
| [Production support](https://moondream.ai/photon/support) | Lists Segment for MD2 and MD3 on named hardware. | Conflicts with the public MD2 disabled segment template. |
| [Segment FAQ](https://moondream.ai/skills/segment) | Says downloadable segmentation is not yet available. | Contradicts the local quickstart and support table. |
| [Kestrel README](https://github.com/m87-labs/kestrel#segment) | Calls for MD3 plus separate segmentation weights obtained through Moondream. | Does not specify a current filename, revision or runtime tuple. |
| [Public3.1 model-card change](https://huggingface.co/moondream/moondream3.1-9B-A2B/commit/1da27e6c2d2f9118de14560df456881dc62d91f3) | July8 maintainer commit removes Segment from the skills list. | Explicit evidence that the public model card does not promise this skill. |

The March10 segmentation announcement promised a local release later that week, but provided no downloadable artifact. A promise and the later Photon claim do not resolve the missing artifact identity. [March announcement](https://moondream.ai/blog/segmenting-update-2026-03-10)

## Published packages and actual defaults

Latest SDK is **moondream2.6.1**, published September30, with an exact **Kestrel0.9.1** dependency. Standalone **Kestrel0.9.2** is newer, but its Moondream registry and downloader are byte-identical to0.9.1. The segment implementation is byte-identical across0.5.0,0.9.1 and0.9.2. Publisher-wheel hashes are in the JSON. The newer changelog adds RF-DETR/DINOv2 and runtime dependencies, not a Moondream segmentation checkpoint or stopping fix. [SDK metadata](https://pypi.org/pypi/moondream/2.6.1/json), [engine metadata](https://pypi.org/pypi/kestrel/0.9.2/json), [changelog](https://github.com/m87-labs/kestrel/blob/main/CHANGELOG.md)

| Model ID | Automatically selected artifact |
|---|---|
| `moondream2` | `vikhyatk/moondream2/model.safetensors` |
| `moondream3-preview` | `moondream/moondream3-preview/model_fp8.pt` |
| `moondream3.1-9B-A2B` | `moondream/moondream3.1-9B-A2B/model.safetensors` |

None of the inspected Python files in these packages selects `seg-model.pt`. Upgrading to standalone0.9.2 therefore does not supply a different segment model. [Registry](https://github.com/m87-labs/kestrel/blob/v0.9.2/kestrel/models/moondream/registration.py)

## Other official artifacts

- **`vikhyatk/moondream-next/seg-model.pt`** exists in manually gated repository revision `1fdf7871dc596a89f73491db95543870727b5dce`; size18,537,525,163bytes. The existing credential received403 during this session. Its name is suggestive, but no current compatibility manifest establishes it as the advertised Photon release. [File metadata](https://huggingface.co/api/models/vikhyatk/moondream-next?blobs=true)
- **`moondream/SegHeadRefiner/model.pt`** is separately gated, revision `d3664cf8d8501b37d9ed8cd222e6d4e876c88621`, size37,035,667bytes. Existing authorization also received403. This refines an existing coarse mask; it does not explain a VLM that emits no path. [Repository](https://huggingface.co/moondream/SegHeadRefiner), [refiner implementation](https://github.com/m87-labs/kestrel/blob/main/kestrel/seg_refiner.py)
- **Public `moondream/moondream-next/model.safetensors`** has the same published SHA256 as public3.1. It is not a different downloadable segmentation checkpoint. [Metadata](https://huggingface.co/api/models/moondream/moondream-next?blobs=true)
- The official model inventory also contains **`md3p-int4`**, documented as an MLX quantization of Preview, and **`tracking`**, an undocumented388MB SSM/ViT checkpoint. Neither supplies a documented Photon segment deployment recipe. [Int4 card](https://huggingface.co/moondream/md3p-int4), [tracking repository](https://huggingface.co/moondream/tracking)

The original segmentation-era Kestrel instructions used manually approved `vikhyatk/moondream-next/model.pt` at revision `d7af1649689208e30e657a8ad52017346e137c39`. This is a historical access route, not proof of current compatibility. [Historical instructions](https://github.com/m87-labs/kestrel/blob/88e1785a0210916ca2d28356900750a7ad200650/README.md#downloading-checkpoint)

## Remaining information needed

A reproducible vendor recipe must specify the checkpoint repository/file/revision/hash, compatible Photon/Kestrel version, any required adapter or decoder setting, optional refiner revision, and a known-good image/prompt with expected SVG. No reviewed source supplies that complete tuple. Cloud-facing model IDs alone do not identify local checkpoint bytes. [Cloud segment API](https://docs.moondream.ai/skills/segment/)

Our conditioned local SVG result also means we should not claim that public weights contain no segmentation behavior. The unresolved issue is the supported, reliable invocation and deployment recipe.

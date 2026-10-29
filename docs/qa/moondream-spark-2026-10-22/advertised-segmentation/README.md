# Why advertised Moondream segmentation does not match the local result

**Subsequent outcome:** the operator authorized alternative mask models. A local
Moondream 2 point → SAM 2.1 Tiny pipeline now produces usable masks; see the
[new implementation and measured evidence](../../local-segmentation-2026-10-22/README.md).
That does not fix or substitute evidence for the native segment-skill failure
analyzed here.

Checked October 22, 2026. **The advertising does explicitly include local
segmentation. The published default setup does not establish that capability,
and Moondream's own supported-H100 release test recorded the same box-without-path
symptom.** This is stronger evidence than the earlier Spark-only experiments.
Local segmentation remains unfinished; this report does not claim a working fix.

## The decisive new evidence

The maintainer's merged [Moondream 2.0 release PR, August 3](https://github.com/m87-labs/moondream-python/pull/15)
describes installed-wheel testing on H100 with exact Kestrel dependencies and
states that the selected segmentation request produced a box without SVG tokens.
Ordinary and streaming calls agreed. Thus, that symptom existed upstream on
supported hardware before our GB10 compatibility work. It is one reported smoke
prompt, not proof that every segmentation call on H100 fails, and the PR does not
provide a complete successful segmentation fixture.

The release audit compared publisher wheels, not only webpages:

- The segmentation skill source is identical in Kestrel 0.5.0, 0.9.1 and 0.9.2.
- The model registration and downloader are identical between 0.9.1 and 0.9.2.
- Those defaults choose the public Preview FP8 or 3.1 safetensors checkpoint.
  No separate segmentation checkpoint or segmentation adapter is selected.
- Consequently, upgrading that dependency supplies no demonstrated checkpoint
  correction or segmentation stopping fix. Other code changes can affect numeric
  outputs, so this is not a prediction of bit-identical generation.

Version identities, wheel/member hashes, URLs, and checked model revisions are
preserved in [upstream-evidence.json](upstream-evidence.json).

## Where the claims conflict

| Primary source | What it says or implements | What it establishes |
| --- | --- | --- |
| [Local quickstart](https://docs.moondream.ai/running-locally/) | Creates public 3.1 with `md.photon(...)`, then calls `segment` | The user's expectation is supported by official instructions |
| [Photon August 3 release page](https://moondream.ai/photon/updates) | Advertises local MD3 segmentation on H100 | An advertised capability, without the exact segmentation weight artifact |
| [Engine README](https://github.com/m87-labs/kestrel#segment) | Says MD3 segmentation requires separate model weights and directs users to Moondream for access | A missing prerequisite in the quickstart; the sentence alone does not identify which weights |
| [3.1 maintainer commit, July 8](https://huggingface.co/moondream/moondream3.1-9B-A2B/commit/1da27e6c2d2f9118de14560df456881dc62d91f3) | Deliberately removes segment from the downloadable model's skill list | Public checkpoint support is narrower than other pages imply |
| [Segmentation product FAQ](https://moondream.ai/skills/segment) | Still describes downloadable support as pending and the launch as cloud-only | Another official contradiction; an undated FAQ cannot alone override newer release notes |
| Installed registry | Shares SegmentSkill across MD2/MD3; MD2's segment template is null | `supports('segment')` can overstate executable capability |

We cannot resolve these contradictions by treating the API method's existence
as proof that the selected checkpoint performs the task. We also should not
claim that Moondream segmentation as a whole is broken: the public local
configuration and the separately advertised segmentation service are not a
verified equivalent deployment.

## What is ruled out, and what remains open

The [local reference comparison](../non-photon/README.md) reproduced worker and
panel box-then-EOS output without Photon. Together with the upstream H100 receipt,
this rules against a solely GB10-specific explanation for the observed symptom.
It does not certify our experimental GB10 adapter as numerically equivalent to
Moondream's supported kernels.

The model emits no path tokens before the normal early stop. SVG rendering,
the mask overlay, and token-budget truncation therefore cannot explain those
particular empty outputs. The later forced-continuation panel *does* hit its
token budget; this is a different failure and is recorded separately.

An independent CPU replay also compared both parsers on the generated worker
and box contours. Their binary raster masks agree essentially exactly, so the
partial worker is not caused by losing coordinates during SVG decoding. Its
predicted box is already too narrow before the path is rendered.

The [segmentation paper](https://arxiv.org/html/2604.02593v1) describes a trained
path generator followed by Moondream's own learned refiner. Our forced coarse
paths are not the complete advertised refined output. The installed refiner is
conditional and is invoked only after a nonempty coarse path, so it cannot by
itself explain or repair the default box-then-EOS stop. It may substantially
affect the quality of a properly generated coarse path. It is part of Moondream's
system, not a proposed replacement segmentation model.

Existing authorized-access checks return HTTP 403 for the historical
`vikhyatk/moondream-next/seg-model.pt` reference and
`moondream/SegHeadRefiner/model.pt`. This does not prove that the historical
seg-model path is today's intended release. No alternate mirror, gate bypass,
access request, cloud inference call or outbound support message was used.

**Working diagnosis:** the public default checkpoint/configuration has not been
shown to match the advertised segmentation deployment. The evidence points to
a release/configuration gap rather than a Spark-only failure. Which exact weights
and settings close that gap remains unconfirmed; we have no basis to promise that
merely obtaining either gated artifact will fix it.

## Concrete next requirement

Obtain a vendor-confirmed tuple: segmentation checkpoint repository/file/revision,
matching tokenizer and prompt/config, required Photon version, refiner requirement,
and one image + prompt + expected mask. Test that exact tuple locally on the
existing bounded harness, with a negative control, before wiring segmentation
into VSS. A [concise support request](vendor-request.md) is prepared locally and
has not been sent.

This turn performed source, release and CPU checks. It did not stop Cosmos,
launch another GPU model, change installed packages, or change the VSS UI.

Detailed independent audits:

- [Release and publisher-wheel evidence](upstream-evidence.md)
- [Entrypoints, checkpoint selection and refiner prerequisites](entrypoint-audit.md)
- [Protocol and parser replay, with mask comparisons](protocol-audit.md)

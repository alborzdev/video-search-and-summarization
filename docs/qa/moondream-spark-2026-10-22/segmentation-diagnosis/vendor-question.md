# Draft: identify the local Photon segmentation checkpoint

Prepared locally; not sent.

We are testing Moondream segmentation through Photon on DGX Spark GB10
(ARM64, SM121). Image answers and detection execute; normal segment calls return
a box and then EOS without an SVG path. However, suppressing EOS only at the
first post-box step let public Preview emit a coarse SVG for one person/point
case, ending naturally after 91 tokens. Its visual quality is incomplete. We
need reliable Moondream segmentation locally.

Further tests reproduced that Preview path without tracing. Conditioning the
same step on ID10 produced a second coarse box-region mask, while five other
positive cases hit a 256-token limit. 3.1 also produced paths under conditioning,
but falsely masked a blank image. MD2 did not emit a valid SVG under the same
diagnostic. We need to distinguish the intended segmentation checkpoint and
invocation from this limited path-generating behavior.

The engine README says segmentation needs separate Moondream 3 weights. The
Photon support page lists Segment for MD2 and MD3, and the local guide/cloud API
show Preview or 3.1. Please identify:

1. The exact repository, filename, revision/hash and access process for the
   segmentation-trained checkpoint used by Photon. Does public
   `moondream3-preview/model_fp8.pt` contain that training, or does it need a
   separate checkpoint/adapter? Which MD2 checkpoint supports the advertised skill?
2. The matching tokenizer, prompt template and engine/SDK version, plus a small
   reproducible image/object example with an expected coarse SVG path. Should
   a local segment call explicitly condition the first post-box token? In our
   successful continuation, the model chose ID10, emitted SVG, then ID11 and EOS.
3. Whether the segmentation checkpoint is supported by the present FP8 loader,
   and whether SegHeadRefiner is optional for a valid coarse mask. Please also
   identify the supported GB10/SM121 build, if one exists.

Our pinned software is moondream 2.6.1, kestrel 0.9.1, kestrel-kernels 0.7.4,
kestrel-native 0.1.8, PyTorch 2.13.0/CUDA 13.0. MD3 uses an application-owned
PyTorch MoE compatibility adapter because the stock optimized path fails on
SM121; this is not a claim of vendor-supported GB10 operation. Batch size is 1,
CUDA graphs and prefix cache are disabled, and decode is native.

Tested public revisions:

- Preview: `5112966d1a723413b1c9a1e8bea272b72e647b35`.
- 3.1: `1da27e6c2d2f9118de14560df456881dc62d91f3`.
- MD2: `5d6c926f44e26b07957b0dd315bbedcb4c17a5fe`.

The normal Preview trace records committed IDs `[5, 5, 6, 0]` on two positive
images with no hint, a point hint and a box hint. Every stop is model EOS, not
token/context truncation or a skill-specific stop. The actual SVG parser passes
CPU fixtures, and Starmie's cached hash matches the official tokenizer. The
one-step continuation result establishes path generation in these public weights;
we are not claiming they contain no segmentation ability.

We have not established that the adapter reproduces native W8A8 results. A
vendor example and matching segmentation-trained checkpoint would let us test
that separately from the public-checkpoint capability mismatch.

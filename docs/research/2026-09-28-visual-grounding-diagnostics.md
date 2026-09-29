# Visual grounding diagnostics — September 28

## Deployment identity

Runtime inspection identifies the active checkpoint as
`ngc:nim/nvidia/cosmos3-nano-reasoner:bf16-final`, served through RTVI as
`cosmos-reason3`. The agent model name is
`nim_nvidia_cosmos3-nano-reasoner_bf16-final`. Earlier assumptions based only on
Cosmos-Reason2 documentation are insufficient for this deployment.

## Primary-source guidance

The [Cosmos3 prompt guide](https://github.com/NVIDIA/cosmos/blob/main/cookbooks/cosmos3/reasoner/reasoner_prompt_guide.md)
distinguishes reasoning and non-reasoning prompts, gives separate sampling
settings, and places visual media before task text. Its examples use 4 FPS and
are described as tested on Super-Reasoner, not this Nano checkpoint. These are
reference settings, not proof that changing this deployment will fix accuracy.
The deployed RTVI video branch already constructs media before text for
cosmos-reason3. No model or frame-budget migration was made from this research.

[vLLM SamplingParams](https://docs.vllm.ai/en/latest/api/vllm/sampling_params/)
defines zero temperature as greedy sampling; construction also normalizes
sampling controls for that case. Therefore, dropping zero or setting it only
after construction is not equivalent to passing the requested value into the
constructor.

## Confirmed parameter defect

The deployed wrapper omitted temperature when its value was zero. Its generation
paths constructed SamplingParams without that field and mutated it afterward
only if it was present. Thus an explicit zero could leave the library default
in effect. Agent configuration requests temperature zero.

Fix: include temperature, including zero, in the SamplingParams constructor for
video, text-only and streaming text paths. Focused tests verify zero and nonzero
values reach construction. This is a request-fidelity fix; it does not guarantee
correct visual descriptions or bitwise repeatability across all conditions.

## Evaluation boundaries

The current five-second test clip supports a worker carrying a box toward rolling
steps; inspected final footage does not support a completed placement or ascent.
Several generated descriptions exceeded that evidence. A specific final-frame
question had one supported response and one response with speculative additions.
Keep this failure visible in the evaluation set; do not substitute a more flattering
clip or silently rewrite the saved model answer.

Next evaluation should compare identical questions after the parameter fix with
raw responses, exact media and timings recorded. Only then consider separately
bounded reasoning/sampling experiments under the existing memory procedure.

## Post-fix bounded result

Two identical final-frame questions returned identical supported core answers in
12.005 and 10.557 seconds. One general description avoided prior completion
claims but still needs fine-detail review. See the [evaluation receipt](../qa/demo-transformation-2026-09-28/temperature-fix-evaluation.md)
for exact responses, test scope and the memory-guard interruption/recovery. This
does not close the broader accuracy finding.

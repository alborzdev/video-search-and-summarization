# Two-clip comparison — failed qualification, September 28

Selected independently searched warehouse moments E1 0:00–0:05 and E2
0:05–0:10. Exact question: “Compare the person’s position in E1 and E2. Describe
only visible movement and where the person stands at the end of each clip.”

## Baseline failure

First observation visible by 20.391 s. Final answer observed by 35.335 s;
reported local analysis 33.0 s. Summary correctly distinguished base versus top
platform, but both underlying inspections invented comparisons of clips they
had not been given. E1 claimed both clips stopped at the ladder's foot; E2
claimed both reached the platform. This is contradictory, unusable evidence.

Root cause in request construction: each single-clip video-understanding call
received the whole two-clip comparison question. Added explicit single-clip
scope for multi-clip inspections and withheld the cross-clip question from those
calls. The synthesis stage still receives the original comparison question and
all observations. Single-clip question behavior remains unchanged.

## Repeat after scope correction

E1 observation visible by 19.991 s. Final degraded result observed by 45.430 s;
reported local analysis 29.5 s (observation intervals are not exact completion
timing). Cross-clip inventions stopped, but visual grounding still failed:
E1 claimed boxes were placed on the ladder, contrary to inspected footage.
E2 predicted preparation to place the box. Synthesis also returned no parseable
JSON object, so the UI correctly exposed a degraded response and its warning.
The synthesis prompt requests JSON; no response-format enforcement is visible
at the invocation. Raw model output was not captured, so the precise formatting
failure is not established. Do not hide it with an unconditional text fallback.

[Failed result](comparison-grounding-failure.png). No report saved for either run.

## Verification and runtime

Python syntax compilation passed. An isolated AST harness executed the actual
_inspect_evidence function with a mocked visual tool and verified two separately
labeled prompts without the comparison question, plus preservation of the
single-clip question. Updated the existing backend unit expectation; the full
backend test module was not run because its heavyweight imports have caused
memory pressure in this runtime. Live repeat verifies loaded behavior.

Restarted only vss-agent to load source; it reached healthy. Core before/after
reported 31 roles, no failures, 50.06/48.99 GiB available. The 48 GiB guard remains
active; do not run another heavy comparison at this headroom without checking
admission and memory. No model budgets, live sources or detectors changed.

This is **not a successful comparison demo**. Remaining work: reliable per-clip
final-state grounding, synthesis output contract, and latency below routine
30-second waits. Neither a correct-looking summary nor progressive text is
sufficient when the underlying observations are wrong.

## Follow-up: enforce local synthesis output shape

The local vLLM call relied on the prompt alone for valid JSON. A direct text-only
probe confirmed this deployed server accepts response_format json_schema. Added
schema binding specifically to vllm_llm: one required string summary, no extra
properties. Other model providers keep their existing invocation. Empty/malformed
output still degrades; no unconditional acceptance of raw model text was added.

Verification:
- Direct server schema probe: valid JSON, 2.742 s.
- Isolated real _synthesize_inspections function with real ChatOpenAI client and
  fixture observations: status complete, valid summary object, 1.450 s. This
  exercises schema binding and parsing while stubbing result containers and
  avoiding the heavyweight full agent import graph. It does not run video AI.
- The latter summary changed “beside green steps” to “on green steps,” so this
  is explicitly a **format-only pass**, not a semantic accuracy pass.
- Syntax compilation passed. Updated backend unit mocks/assertions for schema
  binding; full backend unit module still not executed at tight runtime headroom.
- Repro probe retained as synthesis-format-probe.py; invoke with
  `docker exec -i vss-agent /vss-agent/.venv/bin/python < docs/qa/demo-transformation-2026-09-28/synthesis-format-probe.py`.
  The observations are a test fixture, not fresh video results.

Only the agent was restarted to load the change. No model memory/token budgets
changed. Fresh full comparison remains unqualified because visual grounding,
text synthesis accuracy and total latency are separate unresolved requirements.

## Follow-up: synthesis preserves tested relations

Revised synthesis instructions to preserve location phrases/prepositions and
compare per-clip actions without refusing solely because identity is unknown.
The separate rule against asserting unproven cross-clip identity remains.

A text-only probe uses the actual synthesis function, prompt, JSON binding and
real local ChatOpenAI client. Inputs are explicit fixtures, not video results.
Observed outputs were manually checked in addition to lightweight assertions:

| Fixture | Result | Model-call elapsed |
| --- | --- | --- |
| Beside steps / on platform | Preserved beside and on, assigned to E1/E2 correctly | 1.149 s |
| Outside / inside marked area | Preserved both states per clip | 1.023 s |
| Stops walking while holding / continues walking while holding | Neither shows release | 4.132 s |
| Approaches without entry / walks through and ends inside | Preserved incomplete versus completed entry | 1.084 s |

All four returned valid structured summaries. The earlier beside→on error did
not recur in these scoped checks. Repro: `docker exec -i vss-agent
/vss-agent/.venv/bin/python < docs/qa/demo-transformation-2026-09-28/synthesis-grounding-probe.py`
(run as one shell command). Probe stubs result containers, timeline construction
and identity routing, so it does not replace API integration or video testing.
Syntax compilation passed; full backend unit module remains unrun under current
memory constraints. Restarted only the agent to load the prompt revision.

The visual model's unsupported placement claim is **still unresolved**. Passing
these synthesis fixtures does not qualify full comparison accuracy or latency.

## Follow-up: final decoded frame is not guaranteed in model input

At 48.64 GiB available (only 0.64 above the diagnostic floor), deferred further
inference. Read-only tracing found a separate input limitation. Agent logs show
five-second clips requesting ten frames. The running RT-VLM DefaultFrameSelector
uses `(end - start) / count` and targets `start + i * step` for i=0..count-1.

Executed the class extracted from the actual container source, with a 50-frame,
10-fps fixture and ten requested samples. Selected times were 0.0, 0.5, 1.0,
1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5 seconds. The final decoded frame at 4.9 seconds
was omitted. No CUDA, model or full decoder import was involved.

This is not proof of the placement hallucination's cause. The held box is also
visible earlier, and changing sampling has not been tested against inference.
It does establish that a final-frame question currently lacks guaranteed input
of the final decoded frame. The earlier successful answers remain observations,
not qualification of final-frame coverage.

Repro: `docker exec -i vss-memory-cosmos python3 < docs/qa/demo-transformation-2026-09-28/frame-selector-probe.py`.
The retained probe asserts final-frame inclusion and is expected to fail on the
current sampler. Next fix must reserve a sample slot for the last decoded frame
without increasing the configured frame budget, and cover end-of-stream,
variable frame rate and chunk boundaries at the actual decoder seam. Do not
blindly replace the final target with the clip duration: no frame may exist at
that timestamp. No model/runtime budget or sampler changes made in this pass.

## Native timestamp filter endpoint probe

The default recorded-file decoder uses a native `timestampfilter`, which can
send EOS when its targets are consumed. A Python-selector-only fix would miss
that path. The retained `native-endpoint-probe.py` runs a CPU-only 50-frame,
10-fps GStreamer fixture through the actual installed plugin. Both runs emitted
ten frames: baseline targets ended at 4.5 s; replacing the last target with the
known final PTS emitted 4.9 s. The probe passed without CUDA/model inference.

Read-only ffprobe of the ten-second source recording found its last frame at
9.9 s. Duration itself is not a valid substitute for the last decoded timestamp.
The native plugin has no advertised endpoint-retention property. Correct target
discovery for variable-rate files and chunk boundaries still needs a design;
no production decoder change or accuracy improvement is claimed.

## Endpoint discovery experiment: native demux timestamps

Re-ran the actual selector probe: it still fails final-frame inclusion (4.5 s
selected, final decoded frame 4.9 s). No production fix has been applied.

The Cosmos image lacks both ffprobe and the software avdec_h264 plugin. Rather
than installing dependencies or loading GPU inference, the retained
`endpoint-discovery-probe.py` uses the installed qtdemux/fakesink to collect
compressed MP4 timestamps. Host ffprobe provides an independent decoded-frame
reference. Tiny fixtures are generated in temporary storage and removed; the
real ten-second warehouse recording is read only. Run from the repository root:

```sh
python3 docs/qa/demo-transformation-2026-09-28/endpoint-discovery-probe.py
```

Four cases passed: constant rate with B-frames, variable rate with B-frames, a
nonzero start timestamp, and the actual warehouse recording. Assertions compare
all sorted normalized packet timestamps with decoded frame timestamps and the
last frame within two half-open chunk intervals. Raw measurements are retained
in `endpoint-discovery-results.json`.

The key result is a coordinate mismatch: native raw PTS ended at 5.1 s for the
constant-rate fixture and 5.5 s for variable rate, but both represent the final
4.9 s playback frame after segment conversion. The offset fixture maps raw 5.1 s
to stream time 6.9 s. A raw/stream-time mix would misplace the final sample. The
warehouse recording happens to have zero segment offset, so testing only it
would miss this defect.

Native demux runtime was 2.638–5.065 ms; complete Docker/Python probe invocation
was 170.938–191.481 ms. These are small-file measurements, not model latency or
a general performance guarantee. Host decoded inspection took 458.857 ms for
the warehouse file. No GPU inference was requested.

[Official ffprobe documentation](https://ffmpeg.org/ffprobe.html) distinguishes
packet inspection from frame inspection and notes that interval seeking is not
exact. Accordingly, this experiment scans each short fixture and filters its
timestamps explicitly rather than assuming a seek lands on the requested frame.

### Consequence for implementation

Native demux is a viable dependency-free candidate for this MP4 path, but not yet
a production solution. The next decoder test must exercise the actual post-seek
segment and the timestamp filter together, proving which coordinate system
reaches its input. Reserve one of the existing sample slots for the last eligible
frame; preserve the count and chunk boundaries. Handle short clips/one-frame
budgets, multiple segments, invalid PTS, unavailable files and bounded timeouts.
Do not silently claim endpoint coverage when discovery fails. The Python fallback
and native filter must agree. The current tests do not prove arbitrary codecs,
edit lists, corrupt packets, large files or GPU-decoded timestamp behavior.

This result advances the design and avoids an incorrect duration/fps or raw-PTS
patch. It does not establish that endpoint coverage will eliminate placement
hallucinations; inference accuracy and multi-clip speed remain separate gates.

## Hardware decoder and native filter experiment

The retained `decoder-endpoint-probe.py` runs 160×128 H.264 fixtures through the
installed qtdemux → h264parse → nvv4l2decoder → queue → timestampfilter → fakesink
chain. It does not load VLM weights or change production code/configuration.
Each invocation requires at least 48.5 GiB available; the 48 GiB guard remains
active. Temporary fixtures are removed even when a probe fails.

Nine cases completed normally: baseline, endpoint-aware targets and an accurate
seek for constant-rate, variable-rate and nonzero-start fixtures. The corrected
full-file targets selected exactly ten frames including the last; post-seek
targets selected exactly five including the last. Native raw PTS offsets from
the demux experiment persist through hardware decoding, confirming that segment
conversion is necessary at this seam. Raw results are in
`decoder-endpoint-results.jsonl`.

The first seek experiment returned only four of five targets: PAUSED preroll
consumed one before the seek. Resetting the target property in the filter sink's
SEGMENT event probe restored all five, with no increase in frame count. The
before-reset output is retained in `decoder-endpoint-before-reset.jsonl`. This
is a demonstrated component behavior, not yet a confirmed production defect:
the production appsink uses async=false and its deferred-seek/reuse logic differs
from the deliberately small fakesink harness. Its exact callback sequence needs
a regression test before adopting a reset blindly.

Sampled before/after available memory stayed above 48.84 GiB in the final run;
these are endpoint samples, not peak-memory evidence. All 31 core service roles
were still present without failures afterwards. No inference or live ingestion
was requested.

Next integration work must combine bounded endpoint discovery, segment-aware
target construction, and seek-state handling in the existing frame getter, with
the Python fallback agreeing. The hardware experiment uses known endpoint
metadata from the previous independent reference test; it is not automatic
production discovery, a full API run, or a model-accuracy qualification.

## Repository frame planner implemented and exercised

Added `services/rtvi/rt-vlm/src/utils/frame_sampling.py`. It retains both decoder
PTS and stream time, discovers local MP4 timestamps through installed GStreamer
without decoding images, and selects distinct temporal targets in a half-open
interval with the final eligible frame included. A one-frame budget selects the
endpoint; sparse clips may return fewer frames without duplication. Ambiguous
or nonmonotonic coordinate mappings are rejected. Discovery failures are explicit
`SamplingUnavailable` errors, not partial successful plans.

Default discovery limits: local file at most 64 MiB, at most 100,000 video packets,
and a two-second bus wait. The module explicitly does not promise a hard process
deadline for a wedged native plugin. There is no persistent cache, GPU decoder,
network URL support, or model import in discovery.

Validation:

- Nine standard-library unit tests passed, including CFR, VFR/reordered packets,
  chunk boundaries, start offsets, one-frame/sparse clips and invalid timelines.
  Command: `PYTHONPATH=services/rtvi/rt-vlm/src python3 -m unittest discover -s services/rtvi/rt-vlm/tests/frame_sampling`.
- Updated `decoder-endpoint-probe.py` to calculate targets using this actual module
  inside the installed container. Nine hardware/filter cases passed again; all
  corrected full-file/seek cases preserved exact counts and endpoint inclusion.
  Output: `decoder-planner-results.jsonl`. No hardcoded candidate targets remain.
- `native-frame-planner-check.py` passed six native checks: actual warehouse
  endpoint, missing file, size limit, packet limit, invalid deadline and invalid
  container. The first five-second warehouse interval returns ten targets ending
  at 4.9 s. Python syntax compilation passed.

**Integration status:** the module is tested repository code, but the production
frame getter does not call it yet and the container has not been remounted or
restarted to load it. Next integrate target coordinates and seek reset into that
caller, including frame-cache timestamps and the Python-selector fallback. No
claim of improved production answers or final-frame coverage is made yet.

## Decoder caller integration in repository source

`video_file_frame_getter.py` now calls the new planner for single local MP4,
video-only, fixed/fps-count file requests using DefaultFrameSelector. Live,
all-frame, audio-enabled, custom-selector and multi-file paths retain their
existing behavior. The rollback switch is `RTVI_INCLUDE_FILE_ENDPOINT=false`;
default is enabled once this source is deployed. Discovery rejection logs
“Final-frame coverage unavailable” and retains legacy sampling, so unsupported
inputs are not qualified for endpoint coverage.

The selector stores immutable planned decoder targets separately from its
consumable deque, uses decoder-coordinate bounds in the Python fallback, and
restores targets on a new file SEGMENT before either selection path consumes
buffers. Selected frames must share a compatible decoder-to-stream offset.
Returned video timestamps are converted to stream time before adding split-file
offsets, preserving citation coordinates. Each set_chunk clears the prior plan.

Validation: 15 focused tests passed, including actual selector code extracted
without CUDA imports, native/Python target agreement, consumed-target reset,
selector reuse, split-file offsets, invalid-plan atomicity and all-frame behavior.
The hardware probe now obtains targets from the actual repository selector plus
discovery module. All nine CFR/VFR/offset full/seek cases passed; output is in
`decoder-selector-results.jsonl`. Syntax compilation passed. This is component
validation, not a full frame-getter/model API test.

**Deployment pending:** the running image still uses its existing frame-getter
file, and frame_sampling.py is not mounted there. No service restart or model
request occurred in this pass. Next add both source mounts through the existing
runtime management workflow, validate full decoded output/cache timestamps and
then repeat the visual question under the memory guard. Do not describe current
running answers as using this fix until that deployment is verified.

## Post-deployment multi-clip retest: still fails accuracy and pacing

Core/API checks passed before the run with 50.25 GiB available. In the integrated
browser, retained E1 (0:00–0:05), searched “person climbing the green steps”, added
E2 (0:05–0:10), and repeated the original position-comparison question.

Both decoder receipts reported decoded=20/planned=20 and the expected endpoint:
E1 final_time=4.9; E2 extracted clip final_time=4.8. E2's extracted media is 4.9 s
long and its final displayed source time is 9.8 s. The shorter extraction is not
the sampler dropping the final frame.

First observation appeared by 19.235 s. Final answer appeared by 34.887 s, with
**32.4 seconds local analysis**. Structured synthesis succeeded, but the result
claimed E2 placed the box on shelf E and completed the action. Its underlying
visual observation already contained that claim; synthesis did not originate it.
The cited last frame shows the person on the platform with the box still at their
hands. Completed placement is not clearly established. Therefore this run fails
both the accuracy gate and the routine-under-30-seconds goal. Endpoint sampling
did not solve the semantic completion error. No report was saved.

Screenshots: `comparison-after-endpoint.png`, `comparison-endpoint-e2-final.png`.
After the comparison, core checks still passed with 49.39 GiB available.

### Focused-question diagnostic

Selected E2 alone (now labeled E1) and asked:
“How does the person’s position change during this clip? Describe only visible
movement and where the person is standing in the final frame.”

Fresh result: “The person climbs the green step ladder while holding a box. In
the final frame, they stand on the top platform of the ladder, still holding the
box.” Reported local analysis **11.1 s**, completion observed by 25.846 s. Decoder
again reported 20/20 and final_time=4.8. This bounded conclusion matches the
reviewed final state. Screenshot: `endpoint-focused-position.png`.

The code currently withholds the active question entirely for multi-clip visual
inspection, after an earlier version invented statements about unseen clips.
It asks for a general description instead; synthesis alone receives the actual
question. The fresh contrast supports investigating lost question focus, while
not proving causation from one pair (clip label and request scope also changed).
Next change should preserve the question's relevant visual task while keeping
per-clip scope explicit; do not simply restore the previously failing unrestricted
comparison prompt or add more generic completion warnings. No new prompt change
was made in this diagnostic pass.

## Question focus restored with explicit per-clip scope: partial result

Changed multi-clip visual prompts to include the active question, while explicitly
limiting each call to its own clip and reserving comparison for a separate step.
Single-clip prompts, word limits, temperature, frame budget and model configuration
are unchanged. Updated backend unit expectations and added the runnable
`inspection-question-scope-probe.py`, which exercises the actual inspection
function without heavy imports. Four cases passed: single, comparison, interaction
and query fallback, with exact source/time bounds and one tool invocation per
clip. Syntax passed. The full backend suite was not run at the limited headroom.

Restarted only Agent; all 31 core checks passed with 49.76 GiB available. Rebuilt
the original E1/E2 ordering through the integrated browser and submitted exactly
the same position-comparison question. Both decoder logs again showed 20/20
frames and final times 4.9/4.8 s. First observation visible by 15.280 s; completion
by 30.392 s. **Local analysis: 25.0 s**, down from the prior 32.4 s sample. This
is a sampled improvement, not a percentile or general latency qualification.

The summary correctly distinguishes beside versus on top of the ladder and says
the box is held. However, the underlying E2 observation still says the box was
placed on the shelf, so the result remains internally inconsistent and fails
accuracy. Neither observation describes the unseen clip, so per-clip scope held
in this run. Screenshot: `comparison-question-focus.png`. No report was saved.

Keeping question focus is appropriate request behavior, but is not sufficient
to fix temporal grounding. A correct-looking synthesis must not hide a wrong
source observation. Further work should distinguish a global comparison request
from the concrete single-clip visual question rather than asking a one-clip model
to interpret comparison language. Additional inference/latency costs of any
question-decomposition step must be measured, not assumed negligible.

## Local question-decomposition diagnostic

Ran `python3 docs/qa/demo-transformation-2026-09-28/question-decomposition-probe.py`
against the existing local Nemotron endpoint. This is a diagnostic text-only
planner, not an application change or a visual accuracy test. Exact inputs,
outputs and timings are in `question-decomposition-results.jsonl`.

Five sequential requests took 3.079, 2.189, 2.468, 1.217 and 1.455 seconds.
The position request retained movement and final position; entry counting
retained the exclusion of parked forklifts; separate helmet/blocked-aisle
questions were correctly assigned to E1/E2. The box question added “on the
surface,” which is unnecessary specificity and was not in the original request.
The identity case failed the explicit instruction: it returned “Is this the
same person in E1?” and the equivalent E2 question. Neither isolated clip can
answer that comparison. Structured JSON succeeded in all five cases, but valid
format does not establish semantic correctness.

Decision: do not integrate this planner yet. It adds 1.2–3.1 seconds in these
samples without any measured visual benefit, and the failed identity case shows
why blind rewriting is unsuitable. The next visual experiment can use the
recorded position rewrite as a diagnostic input, changing only that prompt
component while retaining the original footage and sampling. If grounding does
not improve, reject the additional planning step rather than expanding prompts.
If it does improve, broader preservation checks and the existing identity guard
must be addressed before integration. These five samples are not a latency
distribution or general planner qualification.

Runtime before the probe: all 31 core service checks passed, 49.72 GiB available.
Per-request readings remained above 49.7 GiB; no services were restarted, no
live source was started, and runtime/model/frame budgets were unchanged.
## Concise inspection instructions: first consistent comparison

After the single-clip prompt experiment improved focus, replaced the multi-clip
prompt's long general-description/completion-warning suffix with the same short
question-focused instruction. Kept its existing per-clip isolation, labels,
active question and separate comparison step. No planner or extra inference
added; model settings, clip ranges, sampling and synthesis unchanged.

Five-case actual-function scope probe and syntax passed. Restarted only Agent;
API and all 31 core checks passed before the UI request, 49.90 GiB available.
Rebuilt the original E1 0:00–0:05 / E2 0:05–0:10 selection through actual searches
in Codex's integrated browser and submitted the original position question.

- First observation visible by 11.604 s; complete observed by 28.796 s.
- Local analysis: **24.9 s**. This is effectively similar to the previous 25.0 s
  sample, not an established multi-clip speed improvement.
- Both decoded 20/20 frames: E1 final 4.9 s; E2 final 4.8 s within its extracted
  4.9 s video (source 9.8 s).
- E1: walks toward the shelves carrying a box, stops near the steps, stands
  holding the box. E2: climbs to the top platform, holding the box near the shelf.
- Summary correctly preserves near-versus-on-top and holding. Neither
  observation invents completed placement or describes the unseen clip.

Opened E2's actual citation and reviewed the last frame: person on the platform,
box at the hands near shelf E; currentTime/duration 4.9/4.9, ended true,
readyState 4, no media error. E1's same source/range was reviewed in the preceding
single-clip rehearsal. The requested position difference agrees with the
footage. This is the first consistent result for this exact comparison after
the documented failures, not general/repeated comparison qualification.

Screenshots: `concise-comparison-answer.png`, `concise-comparison-e2-final.png`.
No report saved. Post-check: all 31 roles passed, 50.12 GiB available. Keep the
concise suffix; next test ordering/question variation before promoting this as
a dependable presenter path. Full backend suite not run at limited headroom.
## Reversed-order check: completion claim returns

Kept the current concise prompt and question, but selected climbing footage
(0:05–0:10) as E1 and the earlier holding footage (0:00–0:05) as E2 through
the integrated browser. Pre-check: 31 core roles passed, 49.98 GiB available.
No source/model/sampling setting changed and no restart was performed.

First observation visible by 17.876 s; final response observed by 29.575 s.
Local analysis **23.0 s**. Both endpoint receipts were 20/20 frames, at 4.8 s
for climbing and 4.9 s for the earlier clip. Labels followed the selected clips
correctly. However, E1 said “They reach the top platform and place the box on the
shelf,” and the summary repeated placement. The earlier reviewed endpoint does
not establish completed release/placement. Thus the accurate preceding run is
not repeatable enough to qualify the comparison; reversing order and a new
generation are confounded, so this does not prove an ordering-specific cause.

Post-check: 31 roles passed, 50.13 GiB available. No report saved. Exact output
was captured in the browser accessibility transcript, but not in a screenshot
before the following hot reload reset the temporary selection. The image
`search-after-label-hot-reload.png` shows the reset search state, not the failure.

Also corrected EvidenceAnalysisPanel's “Observed” heading/checkmark to “AI
observations” with the AI icon, matching the report's terminology. These claims
are generated, not human-verified facts. The component suite passed 6/6. Because
hot reload reset the result, populated-browser verification of this label is
still pending; do not claim the screenshot proves it. This label correction
does not solve the visual grounding failure. Further quality work should use
varied clips/questions and examine model behavior, rather than more rounds of
generic warning text fitted only to the one successful warehouse example.

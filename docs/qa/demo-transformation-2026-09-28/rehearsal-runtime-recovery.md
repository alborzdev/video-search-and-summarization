# Restore headroom for fresh-answer rehearsal

September 28, 2026, beginning around 18:03 EDT. Prior turn made progress by
verifying saved-report navigation and playback; export delivery remains open.

Inspected the empty Insights view through Codex's integrated browser. It explains
that charts require incident records and does not equate an empty list with
camera uptime or a safe scene. No UI change was needed there.

Fresh vision testing had been deferred because available memory remained below
49 GiB. Inspected the actual Cosmos startup receipt: 3 GiB KV cache provides
21,840 tokens for a configured 16,384-token context (1.33 sequences). The prior
memory research records approximately 2.25 GiB minimum KV for that context.
Reducing to 2 GiB would violate capacity; no model/context/cache budget changed.

Used the documented idle recovery instead:

1. Stopped Agent, LVS, Cosmos, Embed and Nemotron; verified all five exited.
2. Verified `vss-memory-budget.service` remained active.
3. Performed one idle `drop_caches=2` through the documented local container
   invocation, with all models stopped. No periodic reclaim configured.
4. Started the existing core manager. Startup sample: 101.636 GiB available;
   boot ID unchanged (`ac75a3b5-980a-41c5-8301-200423326f72`).

Recovery is **in progress**, not a completed verification. Manager shell session
94981 remains live, currently starting Nemotron; resume that same session, not
another startup. Once complete, verify core/API health and the guard, then
rehearse a fresh single-clip answer with its actual playback and latency.
No sustained-capacity claim follows from recovery alone.

Update: the same manager reached Nemotron ready-settled at 18:04:41 EDT
(90.990 GiB available) and Embed ready-settled at 18:05:53 (84.943 GiB).
Cosmos began at 18:05:54 and was still loading at 18:06:11 (83.642 GiB).
Manager session 94981 remains live; Agent/LVS restoration and end-to-end
verification are still pending. Do not run another startup instance.

## Recovery completed and fresh questions exercised

The existing manager finished successfully at 18:11:48 EDT: all 31 core/API
checks passed, 51.87 GiB available. Guard remained active; no budget changes or
second startup instance. UI typecheck passed with a 1 GiB Node heap cap during
recovery, covering the recent readiness and evidence-label changes.

Opened a fresh integrated-browser tab and followed Home → box search → select
the 0:00–0:05 clip → “How does it end?” → submit. The answer took **14.7 s local
analysis**, still processing at 13.991 s and complete when observed at 20.120 s.
Decoder logged 20/20 frames through 4.9 s. It correctly described standing beside
the ladder holding the box, but also said “preparing to place” and “ready for
placement.” This unsupported future/intent inference fails the grounding gate.
Screenshot: `short-starter-answer.png`. Opened the citation and inspected the
4.9 s final frame: person beside the steps, box in hand, no completed placement.
Post-request core check passed, 50.69 GiB available.

Tested a literal follow-up, “What is visible in the final frame?” Same 20/20
endpoint receipt. **13.4 s local analysis**, complete when observed at 17.290 s.
It again gave a general motion summary ending in “preparing to place the box.”
Thus more literal starter wording alone did not remove the failure. No report
saved and no result edited to hide unsupported claims.

Source inspection shows the Agent tool's `user_prompt` is passed through its
message builder and the RTVI chat endpoint into the VLM query. The ISO tool has
no configured generic system prompt by default. This source review does not
capture the running model's exact request, but supplies no evidence that the
operator question is discarded. Next inspect/contrast the evidence prompt's
general scene-description instructions against a short question-only prompt;
do not adopt further starter wording changes as an accuracy fix without a
matching fresh-media result. Recovery improved immediate headroom, not sustained
qualification or model grounding.

# Endpoint sampling deployment — September 28

## Prepared change

The current manager uses `artifacts/thor-memory-2026-09-09/isolated-cosmos.yml`.
Added read-only source mounts for `vlm_pipeline/video_file_frame_getter.py` and
`utils/frame_sampling.py`. No model settings, token budgets or memory limits
changed. Compose configuration validation passed. Compared the installed decoder
with repository source: its only differences are this endpoint integration.
Fifteen scoped tests and syntax checks passed before restart.

Added an informational decoder receipt showing actual returned frame count and
final playback timestamp against the planned endpoint. This allows API validation
without presenting a planned target as proof of a decoded frame.

## Restart and recovery in progress

Stopped Cosmos only initially. Available memory reached 53.475 GiB, below the
manager's 48+15 GiB startup requirement. Followed documented recovery instead of
lowering the guard: stopped Agent, LVS, Embed and Nemotron; performed one idle
kernel-memory reclaim with all three models stopped; invoked
`python3 artifacts/thor-memory-2026-09-09/manage.py start --profile core`.
The guard was never disabled. First startup sample showed 101.784 GiB available.
Nemotron settled ready at 17:26:09 EDT with 90.908 GiB available; embedding startup
then began. Boot ID remains ac75a3b5-980a-41c5-8301-200423326f72.

The manager process is still running. Deployment is not yet verified. Continue
waiting on the existing process; do not launch a second startup. After completion,
verify both source hashes/mounts, core/API readiness and real decoded endpoint
logging before claiming the running model uses the fix. Then inspect the fresh
answer against footage and record latency. No live ingestion was enabled.

Embedding settled ready at 17:27:19 EDT (84.759 GiB available). Cosmos was
recreated and started at 17:27:22. Verified read-only mounts and SHA-256 hashes:

- frame getter: e5cf635638e0ca6d3b4c879d0cd64fcdacdb15fe97fb8dea362be5587ad9f9ca
- frame sampling: ac0bf4a6899f53118975d444adeab93c5a57792f3bba6fcf63526eb37dae7a0b

Cosmos loaded four checkpoint shards by 17:28:12; manager still waiting for
readiness. That sample showed 60.275 GiB available. Mount verification proves
the intended source is present, not successful end-to-end decoding/inference.

## Deployment completed and first app request verified

The existing startup manager exited successfully. Cosmos settled ready at
17:31:06 EDT; Agent settled at 17:33:10. Final manager check: 31 core service
roles, no service/API failures, 51.26 GiB available. No second startup process,
reboot or guard disable was used.

Through Codex's integrated browser, followed Home → Find a person carrying a box,
removed the second clip retained from the prior comparison, and submitted the
same rehearsed question for E1 (0:00–0:05):

> Describe only the person’s visible actions in this clip. Is the box still being held in the final frame?

Actual decoder log at 21:33:40 UTC:

```text
File endpoint sampling: decoded=20 planned=20 final_time=4.9 expected_final_time=4.900000000
```

This request's configured plan was **20 frames**, not the ten-frame diagnostic
fixture. It returned all 20 and the final 4.9 s timestamp. No frame count or model
budget configuration was increased. The downstream model client, when its cap
applies, uses inclusive linspace indices that retain the last frame.

The answer described carrying a box, approaching the green steps, and still
holding the box beside them. UI reported **14.8 seconds local analysis**. Browser
was still processing at 11.974 s and showed completion by 24.713 s; those are
observation bounds, not exact response latency.

Opened E1 and inspected the final frame: burned-in time 4.9 s, visible box still
held, player currentTime/duration 5/5 s, ended=true, readyState=4, no media error.
The bounded holding conclusion matches the footage. The answer's adjective
“securely” is not established by this review; this is not a safety judgment or
general model-accuracy certification. No new report was saved.

Afterward: 31 roles, no failures, 50.53 GiB available. Screenshots:
`endpoint-answer.png` and `endpoint-final-frame.png`. The full file decoder and
app request now exercise the deployed planner. Multi-clip placement claims,
other codecs/audio paths, latency distribution and sustained runtime remain
unqualified. One successful question previously worked even without this fix;
this receipt establishes endpoint delivery, not a measured accuracy improvement.

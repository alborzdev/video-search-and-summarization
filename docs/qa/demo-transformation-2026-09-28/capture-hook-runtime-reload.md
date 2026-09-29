# Capture hook staged reload — completed

Preflight: 31 core service checks passed, 52.39 GiB available, guard active,
zero RT-VLM streams and Alert Bridge rules, 15.67 GiB free disk. Boot ID remained
`ac75a3b5-980a-41c5-8301-200423326f72`. VIOS returned the conveyor replay at
port 30557. Both detectors remain excluded from the core profile.

Stopped the replay publisher, then used the documented `manage.py stop`.
Stop session 8032 completed successfully; idle reclaim increased available memory
from 72.73 to 112.40 GiB. Persistent data was preserved. Stop log:
`/tmp/capture-hook-stop.log`.

Started `manage.py start --profile core` with the opt-in capture directory
`/tmp/vss-live-input-capture-20260929` inside the Cosmos container and the exact
VIOS-returned RTSP source URL. Startup is running under exec session **86552**;
log: `/tmp/capture-hook-startup.log`. Poll that same handle; do not launch another
manager because observation times out. The app is temporarily unavailable.

## Required continuation

1. Wait for staged startup to terminate and inspect its final result. Preserve the
   48 GiB runtime floor and additional 15 GiB model-start headroom.
2. Restore the existing `vss-vios-nvstreamer` publisher. Verify APIs, boot ID,
   source-mounted UI mode, stopped detectors, empty AI stream/rule state and the
   new helper mount/environment. A source mount alone does not prove imported code.
3. Discover the source URL again. The prepared `live-input-capture-trial.py`
   refuses a URL different from the capture setting, missing/used capture
   directory, inactive guard, occupied AI streams/rules or low memory. It probes
   RTSP and limits the trial to 90 seconds after creation with early memory cutoff.
4. Run that single trial only after readiness. Retrieve captured arrays, input
   metadata and responses from the container before any recreation. Check actual
   array shape/strides, timestamps, prompt and sampling parameters; inspect the
   captured images and correlate each YES/NO. Measure export overhead separately.
5. Verify cleanup leaves zero rules and AI streams. Do not present this as accuracy
   qualification until input evidence supports it. Keep the UI cadence unchanged.

The prepared script passes Python syntax compilation; it has not yet run. Browser
review still awaits the requested user reopen of the policy-blocked error tab.

## Verified continuation, 22:49 EDT

Re-polled startup session 86552: still running. Redis, Postgres and Kafka settled;
Elasticsearch reached healthy, with 110.64 GiB available. No second manager was
started. Model loading and final API readiness remain pending.

Added `inspect-live-input-capture.py` to verify SHA256/shape/dtype, pair response
IDs, export lossless PNG previews and build a chronological review index. A
synthetic capture through the real helper produced four previews and one linked
response; deliberately altered pixels were rejected. This checks evidence-tool
integrity only, not live capture, model correctness or GPU performance.

## Verified continuation, approximately 23:05 EDT

The same startup session 86552 remains active. Supporting-service stages settled,
then Nemotron, embeddings and Cosmos each passed their monitored readiness stage.
Cosmos was recreated at `2026-09-29T03:01:12.74597872Z`; Docker inspection confirms
the new read-only helper mount, requested capture directory and exact expected
source restriction. Cosmos readiness requests returned HTTP200; last loading
sample was 58.866 GiB available. Support/LVS containers have started, but the final
application-service and whole-core checks are still pending. The publisher remains
stopped; no live trial has begun. Continue polling the original manager handle.

## Completion, approximately 23:10 EDT

Startup session86552 is terminal. Its only final failed probe was cold UI
compilation; independent core checks passed afterward. Publisher restored and
the first captured live trial completed with cleanup. See
[result and limitations](live-input-capture-result.md). Do not re-poll or restart
the completed manager. The historical continuation notes above describe earlier
states, not current outstanding processes.

# Final sprint runtime validation

This is a run plan, not a pass receipt. Run after the final images are deployed,
both cameras are ready, and all required containers are stable. Do not run a
second soak against an existing soak. Keep the simulator, detector, and UI
unchanged during the run. Existing source files and previous receipts remain
untouched.

The proposed 2,100-second window gives the monitor time to finish two scheduled
five-second video questions: one per camera, around 900 and 1,800 seconds. A
1,200–1,800-second window only allows one scheduled question to complete. The
questions test successful grounded response delivery; they do not certify that
all generated prose is correct.

## Commands

Run these observers concurrently from `/home/sparkdev/vss`, each with a fresh
output directory. The soak owns the scheduled model questions. The duplicate
audit only reads JPEG/metadata pairs that the running detector already produced.
The health observer reads the existing simulator state. None starts a detector.

```bash
python3 tools/smart-city/soak.py \
  --root /home/sparkdev/vss --device spark \
  --site-id isaac-intersection-a \
  --source-id 997d3a69-e052-45a4-a1ce-be1b046670c4 \
  --source-id 40af41ea-2180-4b7b-83d6-bb5d08ff094a \
  --observations /home/sparkdev/vss/.spark/city/state/live-observations.ndjson \
  --vss-origin http://127.0.0.1:7782 \
  --duration-seconds 2100 --sample-every-seconds 5 \
  --ask-every-seconds 900 --ask-timeout-seconds 55 \
  --require-processed-preview --pause-on-failure \
  --container vss-city-polish-ui \
  --container vss-city-polish-ingress \
  --container vss-agent-ui \
  --output-dir .spark/city/runtime/sprint-final-soak-20261023

python3 tools/smart-city/isaac_health.py \
  --seconds 2100 \
  --output .spark/city/runtime/sprint-final-isaac-health-20261023

python3 tools/smart-city/audit_preview_duplicates.py \
  --vss-origin http://127.0.0.1:7782 \
  --site-id isaac-intersection-a \
  --source-id 997d3a69-e052-45a4-a1ce-be1b046670c4 \
  --source-id 40af41ea-2180-4b7b-83d6-bb5d08ff094a \
  --expected-model-revision 'rfdetr-medium-fp16@sha256:9228a9c88bbde75a867b0ed92bd400da520e9b867baf855ea7343ce3c60866b0;postprocess=one-city-class-per-query-v1' \
  --duration-seconds 2100 --sample-every-seconds 10 \
  --output-dir .spark/city/runtime/sprint-final-preview-duplicates-20261023
```

The first command includes the standard native detector, city gateway, Agent,
VIOS, embedding, VLM, and language-model containers automatically. The three
explicit container arguments add UI process/restart/OOM coverage. Keep the
default five-second stale threshold, 0.9–1.1 clock ratio, and 5% duplicate-PTS
threshold. Do not enable `--trust-source-rtcp-utc` without a separate clock
qualification. Source clock rate is not a measurement of Isaac simulation speed.

The user disabled the separate 23 GiB Isaac stop floor. Confirm that
`isaacAvailableMemoryStopGiB` is null in the active policy; preserve the independent
20 GiB VSS guard and disk/process limits. If an observer fails, keep its receipt
and samples, inspect the specific failure, and preserve the soak's source-scoped
pause receipts. A completed companion observer does not override a failed soak.

## Identity evidence before and after

Capture these public or sanitized fields without saving environment variables,
credentials, or private request bodies:

- Container name, ID, immutable image ID, start time, state, restart count, OOM
  state, health, memory maximum, and cgroup OOM counters for every monitored
  container. The soak records these for comparison during its run.
- Native deployment receipt, worker executable SHA-256, loaded parser SHA-256,
  preserved preprocessing library SHA-256, and engine SHA-256. Compare the active
  process executable with the packaged worker, not just the mutable image tag.
- The model revision emitted in both cameras' preview envelopes. It must include
  `;postprocess=one-city-class-per-query-v1`. The base model command-line argument
  alone does not prove that the new parser is running.
- UI immutable image ID, production build receipt, and the source/package hashes
  captured by that receipt. Confirm the port-7782 front door serves that UI.
- Gateway deployed source identity; both source/session IDs; camera dimensions;
  calibration revisions; site map asset hash; requested/applied native rules
  revision and counter epoch. Keep the current camera-local identity mode honest;
  this run does not claim MV3DT fusion.
- Isaac unit state/PID and active runtime policy hash; exactly two render products
  and two streams; advancing simulation time; encoder queue and error counts.
- Saved 20 GiB reserve, active guard state/configuration identity, and minimum
  available memory during the run.

Root reported the following deployment candidates before this plan was written:

| Artifact | Immutable image ID |
| --- | --- |
| New native worker/parser | `sha256:4b26d3546d5122daa0429ef225b22ac7ed3d225d75d5f9069e9e730df2b800d7` |
| New isolated production UI | `sha256:90e551a93a71b16b09437d5d132c1b5c53bf9384ecd9bf3868cd7fa335d7898e` |

These are expected candidates, not independent final runtime verification.

## Reading the duplicate audit

The audit excludes predicted and stale tracks. It records exact equal rectangles
with distinct track IDs within one camera and one exact frame. Cross-class groups
are counted separately. It does not round rectangles, suppress objects, or compare
unrelated camera views.

The pre-change preview captures contained an observed truck/bus pair at the same
rectangle. The reference RF-DETR decoder permits several class labels from one
query. The new live parser keeps one winning city class per query; its CPU parser
controls and cached 100-image comparison provide direct evidence for that policy.
The public preview omits query IDs, so equal rectangles alone cannot establish
that two tracks came from one query. Different objects can legitimately overlap.
Keep any remaining groups for inspection rather than calling them an automatic
failure or changing thresholds to hide them. The policy does not correct the
truck-versus-bus label or other false detections.

The soak's `maximumDuplicateFraction` measures repeated source timestamps. It is
unrelated to the object-box diagnostic. Zero box groups in sampled previews is
not proof of zero duplicate objects across every processed frame.

## Completion evidence

Require a full successful soak receipt, two successful scheduled Ask receipts,
the full successful simulator-health receipt, and stable final artifact identities.
Retain the duplicate audit as diagnostic evidence. Copy sanitized receipts and
their sample hashes into this QA directory only after completion. Mark interrupted
or failed runs as such; do not combine partial runs into a full pass.

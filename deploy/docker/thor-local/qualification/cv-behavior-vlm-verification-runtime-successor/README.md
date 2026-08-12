# Thor CV → Behavior Analytics → VLM verification qualification

This package proves official capability rows 321–323 against the live unified Thor profile. It publishes the small checked-in Alert Bridge warmup clip as a temporary local RTSP camera, onboards it through VIOS, registers the VIOS proxy with RT-CV, and observes one tracked person candidate flow through the real Thor Behavior Analytics adapter and Alert Bridge into the local RT-VLM. The ordered candidate-before-verdict observation also proves post-alert verification: Alert Bridge re-evaluates an already-created upstream alert over its associated interval. The final record keeps separately addressable scene, time, object, and media context alongside—but not inside—the category/verdict/status decision fields.

The retained receipt requires the Behavior Analytics candidate and final Elasticsearch verdict to keep the same document/source ID, sensor identity, timestamp interval, object IDs, and object timeline while adding a confirmed verdict, reasoning, response code, and status. It also proves four VIOS snapshots were downloaded and sent to the local RT-VLM as base64 data URLs, avoiding localhost URL/SSRF ambiguity.

Run from the repository root:

```bash
python3 deploy/docker/thor-local/qualification/cv-behavior-vlm-verification-runtime-successor/harness.py \
  --acknowledgement I_AUTHORIZE_OWNED_CV_BEHAVIOR_VLM_VERIFICATION \
  --run-id row321-current-thor \
  --output deploy/docker/thor-local/qualification/cv-behavior-vlm-verification-runtime-successor/runtime-receipt.json

python3 deploy/docker/thor-local/qualification/cv-behavior-vlm-verification-runtime-successor/verify.py
```

The harness refuses to begin below 10 GiB free. Its `finally` path removes the RT-CV source, publisher, active VIOS sensor, exact recording interval, every exact sensor-tagged Elasticsearch document, and exact-prefix VIOS temporary files. The full active-service projection must match its pre-run digest before it can pass. VIOS may retain its normal removed-sensor tombstone; the active catalog, proxy catalog, recordings, and temporary media are restored exactly.

No Agent `/generate` request, external network request, or warehouse sample bundle is used.

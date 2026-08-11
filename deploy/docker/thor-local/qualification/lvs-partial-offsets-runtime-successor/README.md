# LVS partial-video offsets runtime successor

This package closes `manifest-entry.video-summarization-file.06-partial-video-offsets` against the current local Thor LVS service.

One deterministic nine-second video has three unmistakable moving-square phases: blue before the selected range, green inside it, and red after it. The positive request selects offsets 3–6 seconds. Admission requires exact response `media_info`, original-timeline event timestamps within that interval, the green motion marker, and complete absence of the blue/red out-of-range markers. A second request reverses the range and must be rejected with HTTP 422 before inference.

The ten-action budget includes preflight catalog/readiness/model checks, exact upload/readback, the positive and negative requests, exact deletion, catalog restoration, and final readiness. The receipt retains no raw ID, prompt, or semantic response.

```bash
python3 deploy/docker/thor-local/qualification/lvs-partial-offsets-runtime-successor/execute.py plan
pytest -q deploy/docker/thor-local/qualification/lvs-partial-offsets-runtime-successor/tests/test_execute.py
```

Live execution requires the exact acknowledgement recorded in `contract.json`.

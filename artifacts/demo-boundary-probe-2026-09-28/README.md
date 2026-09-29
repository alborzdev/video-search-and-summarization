# Box-presence boundary regression fixtures

Nine retained intervals from the September 28 ten-second conveyor replay trial.
These local diagnostic clips occupy approximately 29 MB. `fixtures.json`
checks their SHA-256 hashes before use. They are not generated replacement
footage or a public benchmark.

Run with the existing Cosmos service idle and the memory guard active:

```sh
python3 artifacts/demo-boundary-probe-2026-09-28/probe.py --prompt any-frame --output /tmp/box-presence-results.json
```

The original wording is a known red baseline:

```sh
python3 artifacts/demo-boundary-probe-2026-09-28/probe.py --prompt original --output /tmp/box-presence-baseline.json
```

The probe uses the local RT-VLM chat API with four 512×512 frames, no reasoning
or audio, temperature zero and seed 42. It refuses active RT-VLM streams or
starting memory below 49.3 GiB; the persistent guard must already be active.
It does not start/stop services or change budgets. Maximum three repeats.

Expected YES for windows 0,1,2,3,5,7 is supported by visibly present boxes.
Expected NO for 4,6,8 is based on the four empty sampled review frames; the
entire intervals have not been exhaustively annotated. Thus PASS means agreement
with these reviewed fixture labels, not demonstrated whole-video accuracy.
The response and exact-model-input sampling paths differ from live RTSP.

See [diagnosis](../../docs/qa/demo-transformation-2026-09-28/alert-boundary-diagnosis.md)
for measured outcomes and live-transfer limits.

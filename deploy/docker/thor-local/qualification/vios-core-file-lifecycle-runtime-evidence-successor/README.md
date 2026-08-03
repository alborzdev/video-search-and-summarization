# VIOS core file-lifecycle producer

This immutable producer locks six warehouse-free VIOS/NvStreamer capability
contracts, Local20 remediation inputs, exact implementation/BDD sources, and
repository-recorded image identities. Its only command compiles an inert future
runtime plan:

```bash
python3 deploy/docker/thor-local/qualification/vios-core-file-lifecycle-runtime-evidence-successor/producer.py
```

It has no execute mode and makes no network, Docker, service, product, model,
subprocess, FFmpeg, or warehouse-data call. Every result is explicitly
`runtime_evidence=false`, nonpromotable, and has an empty eligible-ID set.

The plan records conservative future bounds and adjacent negatives. It verifies
the source correction that enforces the configured NvStreamer upload limit
before raw-media handling: a missing `Content-Length` fails closed, the exact
limit is accepted, and one byte over selects the HTTP 413 error path. This is a
per-request `Content-Length` gate, so multipart envelope overhead counts toward
the limit and multiple requests are not treated as one aggregate upload. Equal
current limits (nginx `25G`, NvStreamer `25600MB`) still require both asymmetric
limit orderings under separately authorized, reversible low-limit configuration
before runtime qualification.

Other blockers remain explicit: all three NvStreamer input surfaces plus RTSP,
actual WebRTC, and removal; three BDD-enumerated sensor conflicts; two-download
at-rest identity rather than upload-byte identity; 30fps remediation evidence;
and H.264/H.265/AAC hardware-versus-software element selection. Recorded image
digests do not include the sensor service and are not live identity readbacks.

The source locks cover the sensor-conflict and full-file implementations,
NvStreamer uploader/UI/RTSP/WebRTC controls, the Thor Compose topology, and the
CPU multimedia branch controls—not only their planning metadata.

Run focused tests with:

```bash
pytest -q deploy/docker/thor-local/qualification/vios-core-file-lifecycle-runtime-evidence-successor/tests
```

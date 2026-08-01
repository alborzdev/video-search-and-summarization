# Local20 deterministic candidate fixture pack

This isolated, Warehouse-free package supplies deterministic candidate-input
contracts for nine non-Warehouse local runtime rows:

| Requirement | Candidate contract |
| --- | --- |
| `tiny-agent-media` | Tiny H.264 MP4 and MKV identities |
| `hitl-state-transcript` | Generate, refine, cancel, restart, and persistence state transcript |
| `lvs-multi-file` | Two distinct tiny media identities |
| `search-documents-and-bboxes` | Two documents and exact text, image, object, and selected-bbox routes |
| `candidate-alerts` | Verified and rejected candidate-alert verdicts |
| `tiny-alert-stream` | Tiny loopable media identity plus deterministic alert records; no RTSP service is started |
| `smartcity-ui-incidents` | Synthetic incident, sensor, report, and dashboard references |
| `smartcity-synthetic-tracks` | Speed, flow, collision, stall, and wrong-way track inputs |
| `systems-vios-playback-remediation` | B-frame failing/reference media pair and remediation metadata |

The four media recipe IDs are `tiny-identity-mp4-v1`,
`tiny-identity-mkv-v1`, `tiny-bframe-failing-mp4-v1`, and
`tiny-bframe-reference-mp4-v1`. No media binary is checked in. The four JSON
fixtures are checked in, strict-schema validated, semantically cross-checked,
size bounded, and bound to the manifest by their raw SHA-256 hashes.

## Inert default and read-only validation

The default command only prints a plan. It does not read the pack, resolve a
tool, write a file, or start a subprocess:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/local20-fixture-pack/fixture_pack.py
```

Static validation is explicitly selected and remains read-only:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/local20-fixture-pack/fixture_pack.py \
  validate
```

The validator pins eight raw sources: the manifest, three strict schemas, and
four fixture payloads. It rejects duplicate JSON keys, unknown properties,
hash drift, path escape, invalid bounding boxes or references, incomplete
route/event sets, changed HITL transitions, and an invalid B-frame pair.

## Optional local media materialization

This task did **not** run media generation. A future operator may explicitly
materialize the four recipes using only a trusted local `ffmpeg`:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/local20-fixture-pack/fixture_pack.py \
  generate-media \
  --output-dir /tmp/vss-local20-media \
  --acknowledgement \
  I_ACKNOWLEDGE_GENERATING_BOUNDED_LOCAL20_MEDIA_OUTSIDE_THE_REPOSITORY
```

The output directory must be an absolute, absent path outside the repository
whose parent already exists. The command creates that directory mode 0700 and
pins it by an open descriptor. It accepts only root-owned, executable,
non-group/world-writable `/usr/local/bin/ffmpeg` or `/usr/bin/ffmpeg`. Each
fixed command uses argument arrays, `shell=False`, a null stdin, discarded
bounded logs, a minimal environment, a 30-second timeout, no overwrite, the
`file,pipe` protocol whitelist, and an output below 2,000,000 bytes. Total media
is bounded to 8,000,000 bytes.

Only the four expected media names and one strict receipt are admitted. On a
failure, cleanup unlinks only those names through the pinned directory
descriptor. Unexpected content is preserved and prevents directory removal.
The operation has no network, Docker, download, credential, model, Warehouse,
or service-lifecycle path.

There is intentionally no media `verify` mode in this fixture-only package.
The generation receipt identifies and hashes candidate bytes, but does not
probe codecs or prove VIOS behavior. Future runtime executors must independently
probe/admit the media and capture the actual workflow response.

## Tests

The default test suite mocks every generation subprocess; it never runs
FFmpeg and creates no retained media:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  deploy/docker/thor-local/qualification/local20-fixture-pack/tests
```

## Qualification boundary

This pack is deliberately `candidate_inputs_only_non_promoting`. Its schemas
cannot contain runtime evidence, and validation reports both
`runtime_evidence: false` and `capabilities_promoted: false`. It does not start
VSS, RTSP, Elasticsearch, VIOS, an agent, or any other service. Materializing
or validating these fixtures cannot close or promote any requirement.

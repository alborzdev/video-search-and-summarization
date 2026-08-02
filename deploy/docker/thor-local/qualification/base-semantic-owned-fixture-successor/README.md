# Base semantic owned-fixture successor

This additive, Warehouse-free package closes semantic holes left by
`base-semantic-full-envelope-successor` without changing or promoting the
selected Metadata-500 rows. It preserves the predecessor's exact HTTP report
reads, exact deletes, individual 404 postconditions, numeric-loopback target,
and explicit authorization gate, then adds two independent evidence layers.

First, it source-locks the tracked non-Warehouse audio/video synchronization
clip at `services/vios/test/bdd_tests/data/test_video.mp4` by its exact
2,617,799-byte SHA-256. The reviewed Agent media ID and digest must appear in
the VQA and report request bodies. A separately reviewed local Matroska remux
must also be a regular `.mkv` file with the declared size, SHA-256, and EBML
signature. Output facts are deliberately forbidden from the request bodies,
so the executor cannot pass by copying its expected answers from the prompt.

The tiny-media case requires all of the following from live responses and the
served Markdown report:

- a pixel-dependent description of the predominantly green disk and its white
  sector;
- rejection of the absent blue-square distractor;
- a follow-up that locates the small white circle to the right;
- exact `## Summary`, `## Visual Timeline`, and `## Findings` sections;
- beginning and ending visual-event fact groups with paraphrase-tolerant
  fragments; and
- exclusion of the absent event from the report.

Second, the executor inventories report objects through the Thor profile's
host side of `/vss-agent/agent_reports`. It reads only bounded regular report
objects matching the production `agent_report_*` / `vss_report_*` layouts and
their bounded metadata sidecars. Names and bytes are retained only as hashes
in receipts. The report-object inventory must be empty before the first HTTP
request. This strong precondition is intentional: production uses
timestamp-derived upserts, so checking a response-derived key after generation
would detect a collision too late. An empty, dedicated qualification store
proves every possible returned report key was absent before creation and
prevents overwriting a foreign report.

Snapshots immediately before, immediately after, and two seconds after each
rejected/cancelled operation must be identical. The successful report pair
must be absent from the prestate, must be the exact pair read and deleted by
the predecessor, and the final inventory must exactly equal the empty
prestate. Non-report files are neither read as evidence nor mutated.

The default command is inert:

```bash
python3 deploy/docker/thor-local/qualification/base-semantic-owned-fixture-successor/executor.py plan
```

After separately preparing a dedicated empty Agent report store, reviewing a
closed request manifest, provisioning the exact MP4/MKV media IDs, and
confirming an already-running local Agent, execution requires the exact
acknowledgement:

```bash
python3 deploy/docker/thor-local/qualification/base-semantic-owned-fixture-successor/executor.py \
  execute-http --manifest /absolute/reviewed.json --run-id RUN \
  --origin http://127.0.0.1:8000 \
  --acknowledgement I_ACK_BASE_OWNED_FIXTURE_LOCAL_RUNTIME
```

The checked-in tests never run that command, call a network endpoint, access
Docker, or write the real report store. They use fake HTTP responses and a
temporary object store:

```bash
pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/base-semantic-owned-fixture-successor/tests
```

## Honest remaining boundary

The executor verifies both local fixture byte streams and binds their reviewed
Agent media IDs/digests into every relevant request. The current Agent/VST
surface does not return the stored media object's SHA-256 during VQA, so the
receipt explicitly records `agent_media_digest_readback_proven: false`.
Provisioning must therefore be independently reviewed until a digest-readback
or candidate-owned upload/readback lane is added. No live receipt is checked
in, the current Thor report directory is not assumed empty, and this package
does not establish model identity, service quiescence beyond its bounded
two-second negative window, canonical binding, or promotion.

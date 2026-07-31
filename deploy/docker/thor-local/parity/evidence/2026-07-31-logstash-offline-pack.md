# Thor Logstash protobuf offline-pack evidence (2026-07-31)

## Gap

NVIDIA's shared `logstash` service starts the stock Logstash 9.3.3 image and,
for Kafka profiles, runs `logstash-plugin install logstash-codec-protobuf` on
every fresh container. A cold or forced Thor recreation therefore depended on
Rubygems even when every VSS image and model was already staged locally.

## Thor-only source closure

- The immutable ARM64 base is pinned to
  `docker.elastic.co/logstash/logstash:9.3.3@sha256:a7ad817ec23e2f9c41f8fcd09bcce3c87710890f93612d4fd51de45074d7af2e`.
- Connected staging requests `logstash-codec-protobuf` exactly at `1.3.0` and
  exports Logstash's official offline-plugin ZIP.
- The staging verifier rejects dependency drift from the versions observed in
  the previously working Thor container:
  `logstash-codec-protobuf 1.3.0-java`, `google-protobuf 3.23.4-java`, and
  `ruby-protocol-buffers 1.6.1`.
- The complete ZIP is locked in source at SHA-256
  `f9f35aa8b54e3728fbfea6b9a71d77a572d443823903ff0dd3352b07440dd8fd`.
  Both connected staging and the runtime Dockerfile require the generated
  sidecar to equal that checked-in lock. The runtime image then installs only
  the `file://` pack and checks the resulting `Gemfile.lock`.
- The Thor Compose build uses `network: none` and clears the shared startup
  command, so recreation cannot fall back to an online plugin install.
- The shared service definition is untouched; non-Thor profiles retain
  upstream behavior. Thor is explicitly Kafka-only in this override.

## Static verification

```text
bash deploy/docker/test-scripts/test-thor-logstash-offline.sh
Ran 5 tests
OK
Thor Logstash offline-pack source checks passed.
Resolved Thor Logstash override OK
```

The second line came from a full two-file Thor Compose render using the
protected generated environment; the resolved service retained `command: []`,
`STREAM_TYPE=kafka`, and `build.network=none`.

## Current staged/build evidence

Connected staging produced the ignored local ZIP and sidecar at the locked
digest above. An initial derivative build, before the source-controlled digest
gate was added, produced image
`sha256:2345228a7e484c3510e40758123625ded11d3dcb3837a02c15b598bf04e6e595`.

The first guarded rebuild correctly exposed a base-image compatibility bug:
Logstash's minimal 9.3.3 image does not contain `cmp`. It failed before plugin
installation. The gate was changed to compare the two parsed SHA-256 fields
using the base-available shell `test` and `awk`; the focused suite now rejects
reintroduction of `cmp`, `diff`, or `comm` in this runtime Dockerfile.

The fixed guarded rebuild then succeeded with its build network set to `none`:

```text
image: vss-logstash-protobuf:9.3.3-codec-1.3.0-thor-local
id: sha256:b234e31f3c3cf3d42092281709cf6ce448f546a0c42796223e41832638db444f
architecture: arm64
offline pack checksum: OK
offline file installation: successful
```

Build output verified the checksum, local `file://` installation, and exact
dependency versions without network access. Read-only image inspection
confirmed ARM64 and the source-declared labels:
`logstash-codec-protobuf=1.3.0-java`, `google-protobuf=3.23.4-java`, and
`ruby-protocol-buffers=1.6.1`.

Runtime acceptance remains open. It requires a clean Logstash container start
with external network access unavailable and successful Kafka protobuf
ingestion into Elasticsearch. Do not promote this family to `passed_current`
until that end-to-end evidence succeeds.

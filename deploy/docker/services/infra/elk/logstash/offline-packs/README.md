# Thor Logstash offline pack

This directory intentionally does not commit generated plugin archives. Stage
the checksum-locked pack once while connected:

```bash
deploy/docker/services/infra/elk/logstash/stage-protobuf-offline-pack.sh
```

The command produces these ignored local artifacts:

- `logstash-codec-protobuf-1.3.0-logstash-9.3.3.zip`
- `logstash-codec-protobuf-1.3.0-logstash-9.3.3.zip.sha256`

The generated checksum must match the checked-in
`logstash-codec-protobuf-1.3.0-logstash-9.3.3.zip.expected.sha256` lock. Staging
and the Thor runtime derivative both fail closed on digest drift. The runtime
image installs the archive with its build network set to `none`; missing,
modified, or dependency-drifted packs cannot trigger an online fallback.
Non-Thor profiles keep NVIDIA's upstream Logstash behavior.

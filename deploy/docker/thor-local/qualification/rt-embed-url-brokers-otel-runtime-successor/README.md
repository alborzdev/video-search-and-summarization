# RT-Embed URL, broker, and OpenTelemetry runtime successor

This bounded Thor-local qualifier closes the official VSS 3.2.1 runtime gaps at
indices 370 (`URL and inline base64 video`) and 372
(`Kafka/Redis/OpenTelemetry`). It uses the existing H.264 warmup clip, serves
the bytes from an owned HTTP listener bound only to Docker's private host
gateway, and sends the identical bytes as an RFC 2397 `data:` URI.

The same run consumes the resulting protobuf records from the pre-existing
local Kafka topic without creating a consumer group, subscribes to the local
Redis error channel, triggers one deterministic closed-port acquisition error,
and parses console-exported OpenTelemetry spans in memory. The receipt retains
only aggregate booleans and counts: no vectors, URLs, resource/request/trace
identifiers, broker offsets, prompts, or credentials.

The default command is inert:

```bash
python3 execute.py plan
```

The bounded runtime proof requires the exact acknowledgement in
`contract.json`:

```bash
python3 execute.py execute \
  --ack I_ACK_TWO_LOCAL_EMBEDDINGS_ONE_LOCAL_ERROR_AND_BROKER_OBSERVATION
```

The executor performs no image pull, image build, service lifecycle action,
Agent call, RT-CV/VIOS stream mutation, or Warehouse sample operation. It
requires at least 10 GiB free and restores the RT-Embed file, asset, and stream
catalogs exactly.

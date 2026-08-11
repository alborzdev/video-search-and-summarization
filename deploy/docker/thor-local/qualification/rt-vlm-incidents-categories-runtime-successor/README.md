# RT-VLM incidents and categories runtime successor

This package proves VSS 3.2.1 advertised RT-VLM entries `incidents` and
`categories` against the local Thor runtime. It uploads one deterministic
75 KB video, runs one positive local VLM request with an exact category, and
decodes the resulting NVIDIA `Incident` protobuf from local Kafka.

The owned file and observer process are removed and the RT-VLM catalog is
restored exactly. Kafka topics are append-only: the run intentionally leaves
one tiny, uniquely categorized qualification record in `mdx-vlm-incidents`.
The receipt records this boundary explicitly and retains no raw prompt,
caption, protobuf, resource identity, or credential.

```bash
python3 deploy/docker/thor-local/qualification/rt-vlm-incidents-categories-runtime-successor/execute.py plan
```

```bash
python3 deploy/docker/thor-local/qualification/rt-vlm-incidents-categories-runtime-successor/execute.py execute \
  --ack I_ACK_ONE_APPEND_ONLY_LOCAL_KAFKA_INCIDENT_RECORD
```

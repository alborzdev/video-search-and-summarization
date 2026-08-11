# LVS REST current-runtime qualification

This package proves the complete current NVIDIA VSS 3.2.1 LVS REST surface on
Thor. NVIDIA documents 17 operations; the Thor-local compatibility layer adds
`GET /files/{file_id}`, yielding the exact 18-operation deployed OpenAPI set.

The bounded executor uses a two-second generated H.264 clip and a disposable
private MediaMTX relay. It positively exercises every operation, including
file upload/readback/deletion, VLM captions, both summary aliases, Neo4j-backed
visual Q&A, live caption delivery through Kafka/Logstash/Elasticsearch, and
live-stream summarization. Six reviewed schema/model negatives are included.

The relay runs only on the existing private RT-VLM Compose network and
loopback host port. The executor does not call the VSS Agent `/generate`
endpoint, does not add a VIOS or RT-CV sample stream, and does not use the
Warehouse sample bundle. It retains only counts, sizes, booleans, and hashes.

Run the bounded transaction with:

```bash
python3 executor.py \
  --ack I_AUTHORIZE_LVS_18_OPERATION_DISPOSABLE_RUNTIME_AND_EXACT_CLEANUP
```

Validate the sealed receipt offline with:

```bash
python3 verify.py
pytest -q tests
```

The capability matrix consumes the stricter canonical projection. Regenerate
and byte-check it only after the ledger and oracle promotion are present:

```bash
python3 build_capability_evidence.py --write
pytest -q tests/test_capability_evidence.py
```

Authentication is recorded honestly: the upstream OpenAPI declares bearer
authentication, while the local development LVS process does not itself
enforce it. Thor keeps LVS on trusted loopback; broader access is governed by
the host firewall/reverse-proxy boundary.

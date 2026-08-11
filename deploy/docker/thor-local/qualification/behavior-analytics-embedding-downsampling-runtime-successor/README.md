# Behavior Analytics embedding-downsampling runtime successor

This package qualifies exact Metadata500 capability index 207, `runtime.behavior.embedding-downsampling`, against the released VSS 3.2.1 arm64 Behavior Analytics image on Thor. It launches the real `FusionSearchAnalyticsApp` twice and sends 13 serialized `nv.VisionLLM` embeddings through Kafka in each run.

The sliding-window configuration retained frame IDs `0, 1, 2, 12`; the SDT configuration retained `0, 11, 12`. Both therefore reduced the stream while preserving its first sample and the orthogonal final transition. SDT's pending final candidate was observed after graceful service shutdown, proving the application close/flush path as well as the live downsampler.

The probe uses isolated topics and disposable containers. It does not stop the normal Behavior Analytics services, mutate RT-CV or VIOS, call VSS Agent `/generate`, download assets, or use the Warehouse sample. It does not claim the complete bbox/tracking/embedding pipeline, all output families across every broker sink, embedding quality, or multi-replica performance.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/behavior-analytics-embedding-downsampling-runtime-successor/verifier.py check
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  deploy/docker/thor-local/qualification/behavior-analytics-embedding-downsampling-runtime-successor/tests/test_receipt.py
```

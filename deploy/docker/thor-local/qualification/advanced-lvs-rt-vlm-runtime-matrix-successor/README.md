# Advanced LVS and RT-VLM runtime matrix successor

This read-only successor binds forty-seven advertised capability rows to current-Thor live receipts. Overlay 22 adds four bounded VIOS codec rows: B-frame handling, HEVC multislice/RFC7798, H.264/H.265, and audio RTSP republish. The retained isolated Thor run decoded B-frame H.264 and four-slice HEVC through RTSP, exercised hardware and software H.264/H.265 paths, and republished AAC on the supported H.264/HEVC paths with a proven transcode substitute for the bounded direct B-frame+AAC limitation. Audio recording remains explicitly unclaimed. Overlay 21's WebRTC row and the prior 42 rows retain their exact evidence.

Each receipt is hash-locked, validated against its own JSON Schema, bound to its exact package contract, checked for required cleanup and policy assertions, and mapped to the exact row/index in the selected 500-row metadata set. The resulting `matrix.json` truthfully records `passed_current_thor` runtime evidence.

The canonical candidate-admission system still records these rows as `not_qualified` because it has no trusted admission receipts. This overlay does not rewrite that separate state or claim canonical promotion. It provides evidence-based local feature accounting while keeping the protected admission drafts untouched. VSS Agent `/generate` calls and the Warehouse sample are excluded. Row 377 binds 1,536 dimensions to the exact signed RADIO-CLIP v1.0 artifact despite conflicting NVIDIA documentation. The row-378 claim is appearance-based re-association rather than legacy tracker-ID continuity. The row-379 claim remains P6-PPM-scoped; the separately observed Thor JPEG decoder defect remains open and is not represented as passing.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/advanced-lvs-rt-vlm-runtime-matrix-successor/compiler.py check
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  deploy/docker/thor-local/qualification/advanced-lvs-rt-vlm-runtime-matrix-successor/tests/test_compiler.py
```

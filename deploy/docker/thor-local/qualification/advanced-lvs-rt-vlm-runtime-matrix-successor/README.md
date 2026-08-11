# Advanced LVS and RT-VLM runtime matrix successor

This read-only successor binds twenty advertised capability rows to current-Thor live receipts. Overlay 8 adds production RT-VLM asset pressure eviction, hard-cap enforcement, in-use protection, and TTL expiry to the nineteen previously proven advanced LVS and RT-VLM rows. The bounded proof uses isolated temporary catalogs inside the healthy RT-VLM container and leaves the main catalog unchanged.

Each receipt is hash-locked, validated against its own JSON Schema, bound to its exact package contract, checked for required cleanup and policy assertions, and mapped to the exact row/index in the selected 500-row metadata set. The resulting `matrix.json` truthfully records `passed_current_thor` runtime evidence.

The canonical candidate-admission system still records these rows as `not_qualified` because it has no trusted admission receipts. This overlay does not rewrite that separate state or claim canonical promotion. It provides evidence-based local feature accounting while keeping the protected admission drafts untouched. VSS Agent `/generate` calls and the Warehouse sample are excluded.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/advanced-lvs-rt-vlm-runtime-matrix-successor/compiler.py check
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  deploy/docker/thor-local/qualification/advanced-lvs-rt-vlm-runtime-matrix-successor/tests/test_compiler.py
```

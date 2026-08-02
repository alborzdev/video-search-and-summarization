# Advertised-entry 71 current-source rebase successor

This additive package rebases the retained 71 advertised-entry candidates onto
the current checkout without changing or relabeling the immutable
`advertised-entry-executors-74-successor` inventory or execution receipt.

The exact partition is 44 rows whose complete historical source-lock sets still
match and 27 rows affected by an exact nine-path current-source overlay. All 182
retained row/source references resolve against either their immutable historical
digest or the overlay digest. The historical dispatcher is never imported or
replayed.

The validator additionally proves two semantics that changed with those files:

- Kafka chunk publication follows `_on_vlm_chunk_response` →
  `_publish_chunk_messages_if_active` → `_send_protobuf_to_kafka`. The guarded
  publisher holds the handler lock, checks `abort_requested` or `finalized`
  first, and contains both protobuf send sites. The response callback has two
  pre-publication terminal checks and no direct protobuf-send bypass.
- The current NAT/agent inventory has exactly 56 unique operations: the former
  44-operation denominator plus 12 exact Search attribute/fusion/image routes.
  The eight generate/chat routes required by the immutable Wave 6 executor are
  all still present.

This is static, candidate-only current-source provenance. Runtime evidence is
empty, promotion remains false, official capability state is unchanged, and
the Warehouse sample is excluded.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/advertised-entry-executors-71-current-source-rebase-successor/validator.py \
  --check

PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/advertised-entry-executors-71-current-source-rebase-successor/tests
```

The validator performs bounded regular-file reads, SHA-256 comparisons, strict
JSON parsing, and Python AST inspection only. It performs no network, Docker,
subprocess, credential, download, service-lifecycle, browser, or host mutation.

# Retained evidence

`runtime-receipt.json` is produced only by a successful live run of `harness.py` on Thor and is validated against `receipt.schema.json` by `verify.py` and the package tests.

The receipt binds to exact official Metadata500 rows 321 and 322 and the source-locked host/live-container implementation. Its required assertions cover:

- RT-CV person metadata in `mdx-raw`;
- a real Behavior Analytics `FOV Count Violation` candidate;
- the same candidate ID and source ID in `mdx-incidents` and `mdx-vlm-incidents`;
- candidate observation before VLM verification, proving post-alert rather than pre-alert classification;
- preserved sensor identity, evidence interval, object IDs, and object timeline;
- four correlated VIOS snapshots inlined as base64;
- a local RT-VLM chat-completion HTTP 200 plus confirmed verdict, reasoning, and `OK` status;
- exact active runtime-state restoration and complete owned-artifact cleanup.

Only hashes and bounded booleans/counts are retained; the temporary VIOS UUID and raw media URLs are not retained.

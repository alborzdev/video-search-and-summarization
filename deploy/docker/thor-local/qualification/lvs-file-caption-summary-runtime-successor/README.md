# LVS file caption and summary runtime qualification

This package proves official rows 296 and 297 against the deployed Thor LVS
service using the checked-in 10-second warehouse clip. One owned upload is
split into four exact `3/3/3/1`-second caption intervals, then summarized by
the released `/v1/summarize` API with plain-caption parsing explicitly selected.

Acceptance requires the first chunk to identify the worker carrying a box, the
last chunk to identify the worker on the green ladder at the shelf,
and the aggregate summary to preserve both events in chronological order while
excluding the absent forklift control. Raw semantic output is represented only
by hashes and boolean oracle results in the retained receipt. File, graph,
runtime, and running-container baselines must be restored exactly.

```bash
python3 deploy/docker/thor-local/qualification/lvs-file-caption-summary-runtime-successor/harness.py \
  --ack I_ACK_ONE_OWNED_LVS_FILE_AND_TWO_LOCAL_CAPTION_SUMMARY_REQUESTS
python3 deploy/docker/thor-local/qualification/lvs-file-caption-summary-runtime-successor/verify.py
python3 -m pytest -q \
  deploy/docker/thor-local/qualification/lvs-file-caption-summary-runtime-successor/tests/test_package.py
```

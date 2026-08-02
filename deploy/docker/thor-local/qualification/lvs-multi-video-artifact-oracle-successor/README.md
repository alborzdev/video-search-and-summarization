# LVS multi-video per-artifact semantic oracle

This provider-free successor closes the static portion of the advertised
`multi-video report` gap. It binds two ordered 61/62-second video recipes with
disjoint planted events, exercises the checked-in production correlation
helpers, and requires one Markdown/PDF pair per source. Each artifact must:

- retain the shared `report_correlation_id`;
- identify the exact requested source and source index;
- contain that source's planted event and its sensor identity;
- exclude the other source's event; and
- match its semantic-text digest and same-stem Markdown/PDF partner.

The production helper is exercised with deliberately reversed provider
completion order. The observable API result must restore request order and
expose exact source-to-artifact keys. A missing, duplicate, foreign, swapped,
or cross-contaminated artifact fails closed.

This package is static candidate evidence only. The video recipes are not
rendered, their `materialized_video_sha256` values remain null, and the
semantic texts are fixture-owned oracle observations. No VST registration,
LVS/RT-VLM inference, Agent WebSocket call, report readback, PDF extraction,
cleanup, runtime receipt, admission, or canonical promotion is claimed.
Warehouse remains excluded.

Run from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/lvs-multi-video-artifact-oracle-successor/executor.py \
  --json

PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/lvs-multi-video-artifact-oracle-successor/tests
```

The executor is read-only and performs no network, Docker, subprocess,
download, service lifecycle, model, credential, or Warehouse operation.

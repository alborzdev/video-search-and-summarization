# Advertised-entry candidate bindings: Wave 3

This additive static overlay connects ten exact advertised-entry candidate rows
to the strongest new semantic packages without changing the authoritative
candidate mapping:

- five **partial executor candidate** links: Base visual Q&A, Base VLM report,
  LVS multi-video report, LVS object/event/scenario focus, and UI chunked-upload
  plus RTSP management;
- five **static blocker** links: Search natural-language, CV-attribute,
  fusion, image, and archive-management rows.

No row is a concrete/full binding. The Base, LVS, and UI packages leave exact
semantic negatives, ownership/pre-state, dependency identity, bounds, or live
receipts open. The Search package has no transport or executor: its links say
that safe exact fixture provisioning and rollback are blockers, not that the
five Search features work.

The compiler requires all ten authoritative mapping rows to retain
`binding_kind: none` and `no_receipt_not_admitted_not_executable`. It also
source-locks the exact advertised contracts, the Wave-2 registry, and the four
candidate packages. Canonical binding changes, admissions, executable rows,
runtime receipts, and promotions are all exactly zero.

Run from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/advertised-candidate-bindings-wave3-successor/compiler.py \
  check

PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/advertised-candidate-bindings-wave3-successor/tests
```

`compile` writes only deterministic JSON to stdout. There is no execute,
network, Docker, browser, service, download, credential, or repository-write
mode. The optional Warehouse sample remains excluded.

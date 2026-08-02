# Advertised-entry 74 immutable drift observer

This read-only successor preserves the published 74-successor inventory and
execution receipt as immutable candidate evidence. It verifies their raw
identities, every historical Wave 1–7 inventory/executor identity, and the
receipt's non-promotion boundary.

It deliberately does not invoke the historical compiler, executor, adapters,
or tests. The old cases bind implementation bytes that have since evolved, so
replaying them would confuse immutable evidence with current qualification.
Instead, the observer compares all 88 old source locks with the checkout and
reports drift without requiring current bytes to match.

The preserved receipt remains the guarded-observer input consumed downstream.
No historical inventory, receipt, source lock, result, or oracle is rewritten.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/advertised-entry-executors-74-drift-observation-successor/validator.py \
  --check

PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/advertised-entry-executors-74-drift-observation-successor/tests
```

The validator performs regular-file reads and SHA-256 comparisons only. It has
no import or execution path into the historical dispatcher and performs no
network, subprocess, Docker, service lifecycle, write, or Warehouse action.

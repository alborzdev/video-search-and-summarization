# Host-prerequisite evidence package — implementation record

This record describes the isolated collector implementation. It is not a live
host evidence payload and does not promote any parity or runtime state.

Implemented boundaries:

- exactly four prerequisite capability/oracle pairs are canonical-hash bound;
- default execution is an inert, schema-validated plan;
- inspect mode requires the exact read-only acknowledgement;
- the result schema is raw-byte self-locked by the collector;
- external commands, host files, and sysfs network reads are closed and
  informational;
- NGC discovery occurs only after acknowledgement and source validation, uses
  only fixed root-owned non-writable system candidates, and rejects symlinks
  and user-home executables;
- Docker lifecycle, Compose application operations, network requests,
  credentials, raw probe output, host mutation, and VSS-state mutation are
  prohibited;
- physical-link capacity and active-route diagnostics have separate semantics;
- advertised total-capacity satisfaction is independent of current free
  memory/disk operational admission;
- emitted records are strict-schema validated and canonically hashed;
- runtime feature qualification is fixed to `false`.

Focused verification:

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  deploy/docker/thor-local/qualification/host-prerequisite-evidence/tests

.........................                                                [100%]
25 passed
```

No live inspect command was run while creating this package. No container was
started, stopped, restarted, created, removed, built, or pulled. No shared
parity ledger, inventory, lane plan, or acceptance artifact was edited.

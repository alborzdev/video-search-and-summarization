# Thor architecture-gap contracts

This package freezes the current architecture decision boundary for four open
VSS 3.2.1 Thor-local acceptance rows:

| Acceptance row | Current blocker | Required implementation direction |
| --- | --- | --- |
| `smartcity-manual-calibration` | The released legacy calibration server has only an amd64 runnable child. The Thor importer is not the interactive legacy UI/server. | A content-locked native ARM64 legacy calibration UI/server supporting the four project types and manual workflow. |
| `smartcity-gis-calibration` | The official UI consumes Google Maps; the local SVG is a deliberately non-identical provider-free alternate. | A native provider-free interactive GIS editor with homography, ROI, road-link, validation, export, and explicit alternate identity. |
| `systems-alert-worker-scaling` | `num_workers` is in-process concurrency. The service also fixes its container name and uses host networking. | A replica-safe Compose service with unique identities, non-host networking, Kafka partition coverage, and measured backpressure. |
| `systems-vios-scaling` | Stream processors reuse one fixed name, host port, and storage layout. | Replica-safe stream processors with isolated identity/storage/routing while Sensor remains exactly one instance. |

The package is inert. `validator.py` reads only bounded, non-symlink files in
the checkout. It has no Docker, network, download, subprocess, host inspection,
or service-lifecycle code. Validation never changes the current parity status.

Run the static source-lock check:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/architecture-gap-contracts/validator.py \
  check
```

Run the adversarial tests:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  deploy/docker/thor-local/qualification/architecture-gap-contracts/tests
```

## Decision and acceptance records

`decision.schema.json` describes a future implementation decision. It must
select every exact design, enumerate every required change, acknowledge every
forbidden shortcut, contain no runtime evidence, and keep all runtime claims
false.

`acceptance.schema.json` describes a later, separately authorized runtime run.
It requires six digest-locked runtime observations per row, exact replica
counts, timestamps within the run, successful cleanup, no Warehouse sample,
and one Sensor instance for VIOS. `validate-acceptance` validates such a
receipt; it still does not update the parity ledger. Explicit review and
integration are separate operations.

## Non-equivalence guardrails

- AutoMagicCalib is not the legacy manual calibration toolkit.
- Imported calibration JSON is not evidence of interactive calibration.
- The local SVG map is not the official Google Maps UI.
- `num_workers`, a rendered `deploy.replicas`, or other static configuration is
  not runtime scaling evidence.
- An emulated amd64 image is not a native Thor artifact.
- A scalable VIOS topology scales stream processing, not Sensor.

The Warehouse sample bundle is excluded throughout. Generated or
operator-custom minimal fixtures are the acceptance inputs.

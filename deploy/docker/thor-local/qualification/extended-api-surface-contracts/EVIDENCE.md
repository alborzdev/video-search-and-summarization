# Extended API surface static evidence — 2026-08-01

## Scope and safety

This evidence was collected read-only on NVIDIA Jetson Thor. The audit used
checkout inspection, `docker image inspect`, and streamed `docker image save`
archives. OCI layers were parsed in memory to enumerate schemas/decorators and
hash selected files. It did not create, start, stop, restart, or remove a
container; pull an image; download an artifact; or copy proprietary source into
the repository.

The Warehouse sample bundle was not used and is not a prerequisite for this
contract.

## Immutable image evidence

The following staged images were ARM64/Linux at audit time:

| Component | Immutable reference | Local size |
|---|---|---:|
| VSS Configurator | `nvcr.io/nvidia/vss-core/vss-configurator@sha256:35e3e31e7d9e62b298d6dbcb91244d54b0686845227f26e46f886493e9fe4504` | 149,205,524 B |
| SDRC | `nvcr.io/nvidia/vss-core/sdr-mw-l@sha256:7f98d296295a60ccd59c23b4c23ff0c72bfa01a669279c43896ed8d196f14069` | 1,214,578,191 B |
| DeepStream Configurator | `nvcr.io/nvidia/vss-core/vss-rt-config-adaptor@sha256:f7967b26377313fe0131c251ae203f70b9743b3edf61fa5b68d21f822dbbb340` | 33,689,003 B |

`contract.json` records the exact selected inner-file SHA-256 values and sizes.
Those descriptors are sufficient for static replay; Docker is deliberately not
queried by `validate.py` or the tests.

## Recovered contracts

### VSS Configurator — 7

The pinned image has no OpenAPI document. AST extraction of Flask decorators in
the locked implementation source recovered:

- `POST /calibration`;
- `GET /download`, `/cameras`, `/groups`, `/healthz`, `/readyz`, and
  `/video-upload-status`.

### SDRC — 46 across three surfaces

- Controller: 7 operations, identical between the locked controller OpenAPI
  document and implementation decorators.
- Router: 16 operations from the locked programmatic OpenAPI 3.0.3 document.
- Workload coordinator: 23 implementation routes.

The workload-coordinator Swagger declares only 17. The exact six omitted
implementation routes are:

- `GET /openapi.json`;
- `GET /`;
- `GET /redis_cache_data`;
- `POST /remove_stream`;
- `GET /pod_list`;
- `GET /down_pods`.

The discrepancy is preserved rather than hiding implemented routes. `GET
/reset` is explicitly classified as mutating.

### DeepStream Configurator — 1

The pinned image has no OpenAPI document. AST extraction recovered exactly
`POST /config`. Its implementation writes mounted CSV/YAML state and schedules
process exit after returning, so future qualification requires a disposable
fixture and cannot be a generic read-only probe.

### AutoMagicCalib — 26

The backend image was absent. The exact 26-operation contract comes from the
checked-in `REQUIRED_OPENAPI` dictionary in the Thor auto-calibration qualifier.
The validator independently parses that dictionary with AST on every run. The
catalog covers readiness, project creation/uploads/configuration,
verify/run/stop/status/delete, results/logs, VGGT, and RTSP capture lifecycle.

This proves a static catalog only. It does not prove the absent backend starts
or that any calibration completes.

### Legacy calibration — authoritative unknown, lower bound 14

`nvcr.io/nvidia/vss-core/calibration:3.2.1` was not staged. The checkout contains
deployment configuration and a UI client, but no authoritative server source,
OpenAPI document, or URL table. Literal client calls prove 14 distinct
method/path pairs. They do not prove that the server has only 14 operations.

Accordingly:

- `operation_count` is `null`;
- `contract_state` is `authoritative_unknown`;
- `minimum_operation_count` is 14;
- formulas retain the symbol `L` instead of inventing an exact count;
- `complete_product_api` remains false.

## Validation evidence

Focused validation on 2026-08-01:

```text
PASS: validated 7 extended API surfaces — 6 exact descriptors / 80 operations; legacy remains authoritative_unknown with L>=14

Ran 17 tests
OK
```

The adversarial suite covers duplicate keys, strict-schema rejection,
contract-hash drift, removed/substituted routes after hash recomputation,
invented legacy totals, reduced legacy lower bounds, false complete-product
claims, image digest drift, checkout source drift, the mutating `GET /reset`
guard, the six-route SDRC discrepancy, AMC catalog parity, and absence of Docker
or subprocess dependencies in the validator.

## Qualification boundary

This package closes only the static discovery gap for six surfaces. It does not
integrate shared ledgers, prove network exposure, execute a route, or qualify a
service at runtime. The legacy server contract remains the authoritative blocker
to a final complete API denominator.

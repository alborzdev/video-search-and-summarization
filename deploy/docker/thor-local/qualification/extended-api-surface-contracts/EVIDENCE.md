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

### Absent legacy image registry evidence

The stable VSS 3.2.1 checkout selects
`nvcr.io/nvidia/vss-core/calibration:3.2.1`. Read-only public NGC repository
metadata reported:

| Field | Observed value |
|---|---|
| Runnable child reference | `nvcr.io/nvidia/vss-core/calibration@sha256:92dc91595316e10a85d0e6bc0bf9c2f2921b07030a246f9c0854ae6b61426ad8` |
| Runnable child platform | `linux/amd64` |
| Compressed size | 981,287,603 B |
| Native Thor `linux/arm64` child | absent |
| Non-runtime descriptor | `sha256:a1660162ab57e5639a2a838b8b5a791327d2584801e00847f85dae6db059856b`, `unknown/unknown`, 1,166 B |
| Local image presence | absent |
| Tag-index digest | unresolved (`null`) |
| Unpacked size | unresolved (`null`) |
| Manifest access | denied |

The repository-level `isMultiArchitecture: true` flag is not treated as proof
of ARM64 support. Its published runnable variants contain only the amd64 child,
so the absent image is architecture-blocked for native execution on this
aarch64 Thor host. The unknown/unknown descriptor is preserved as non-runtime
metadata and is not guessed to be an executable platform.

No image was pulled. Registry provenance is sufficient to lock the exact child
identity and compressed transfer size, but it cannot recover server routes or
set the legacy operation count. The tag-index digest requires authenticated
manifest metadata, and exact unpacked size requires further artifact evidence.

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

The exact amd64 child metadata above does not change that conclusion. It proves
artifact identity, platform, and compressed size only; it does not prove an API
route or Thor runtime behavior.

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

Ran 23 tests
OK
```

The adversarial suite covers duplicate keys, strict-schema rejection,
contract-hash drift, removed/substituted routes after hash recomputation,
invented legacy totals, reduced legacy lower bounds, false complete-product
claims, image digest drift, checkout source drift, the mutating `GET /reset`
guard, the six-route SDRC discrepancy, AMC catalog parity, and absence of Docker
or subprocess dependencies in the validator. Registry-specific adversarial
tests reject child-digest drift, invented ARM64 support, invented index or
unpacked sizes, false local presence/runtime claims, weakened pull boundaries,
and bypass of the registry-provenance link.

## Approval and lifecycle boundary

The audit did not authorize or perform a pull. After a fresh metadata and disk
review, static staging requires explicit approval for exactly:

```bash
docker pull --platform=linux/amd64 \
  nvcr.io/nvidia/vss-core/calibration@sha256:92dc91595316e10a85d0e6bc0bf9c2f2921b07030a246f9c0854ae6b61426ad8
```

That approval would cover the pinned amd64 image pull only. Container creation
or execution, host emulation installation/configuration, image removal, and
Docker pruning each remain separate approval boundaries. Registry metadata
alone never authorizes runtime qualification.

After an approved pull, route recovery can remain containerless: first stream
`docker image save --platform=linux/amd64` to collect the OCI manifest and layer
order, then stream it a second time to inspect only ordered layer tar members,
apply whiteouts, and hash candidate server/OpenAPI/route files in memory. No
large temporary image archive or server process is required.

## Qualification boundary

This package closes only the static discovery gap for six surfaces. It does not
integrate shared ledgers, prove network exposure, execute a route, or qualify a
service at runtime. The legacy server contract remains the authoritative blocker
to a final complete API denominator.

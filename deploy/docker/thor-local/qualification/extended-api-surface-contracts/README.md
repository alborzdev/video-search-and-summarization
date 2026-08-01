# Thor extended API surface contracts

This isolated package records the official VSS configuration and calibration
API surfaces that are intentionally outside the current 17-surface core API
inventory. It does **not** modify that inventory, increase shared totals, or
claim complete-product API coverage.

## Denominator

The five advertised claim families resolve to seven independently addressable
REST surfaces because the SDRC claim contains controller, router, and
workload-coordinator APIs.

| Surface | Static contract state | Operations |
|---|---|---:|
| VSS Configurator sensor API | exact descriptor | 7 |
| SDRC controller | exact descriptor | 7 |
| SDRC router | exact descriptor | 16 |
| SDRC workload coordinator | exact descriptor | 23 |
| DeepStream Configurator | exact descriptor | 1 |
| AutoMagicCalib | exact descriptor | 26 |
| Legacy calibration UI/server | `authoritative_unknown` | `L >= 14` |

The six recoverable surfaces total exactly 80 operations. The legacy UI client
proves 14 distinct method/path pairs, but the absent official server image and
absent server schema mean that 14 is only a lower bound. `L` must remain
unresolved until an authoritative server route table is captured.

Relative to the observed 17-surface core inventory, the complete totals can
currently be expressed only as:

- declared REST operations: `407 + L` (minimum 421);
- normalized REST operations: `406 + L` (minimum 420).

Neither minimum is a complete total.

## Trust model

[`contract.json`](contract.json) contains normalized operation descriptors and
two types of provenance:

1. `pinned_local_image_snapshot` records immutable NGC image digest, ARM64
   platform, local image size, inner-file path, content hash, and extraction
   method observed during the read-only audit. Tests never require those images.
2. `checked_in_source_snapshot` records repository path, SHA-256, and Git blob
   identity. The validator re-hashes these files every run. AutoMagicCalib's
   `REQUIRED_OPENAPI` dictionary is also parsed with Python AST and compared to
   the 26-operation descriptor.

No proprietary implementation source or schema content is copied into this
package. Only normalized method/path descriptors, cryptographic identities,
sizes, roles, and limitations are retained.

The workload-coordinator contract deliberately uses its 23 implemented routes,
not only the 17 routes in its published Swagger. Six implementation-only routes
are locked as a reviewed discrepancy. In particular, `GET /reset` is marked
mutating; HTTP method alone is not used to decide whether a future probe is
safe.

## Validate

From the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/extended-api-surface-contracts/validate.py

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s deploy/docker/thor-local/qualification/extended-api-surface-contracts/tests \
  -p 'test_*.py' -v
```

The validator is fail-closed:

- JSON Schema rejects missing or additional fields;
- duplicate JSON keys are rejected;
- the canonical contract hash locks the complete document;
- hard-coded reviewed operation sets reject a rewritten descriptor even if its
  hash is recomputed;
- image digests, image IDs, ARM64 platform, sizes, and inner-file hashes are
  locked without consulting Docker;
- checked-in source hashes and Git blob identities are revalidated;
- legacy calibration cannot be promoted from `authoritative_unknown` or assigned
  `operation_count: 14`;
- runtime state must remain `not_qualified` with no runtime evidence;
- `complete_product_api`, Warehouse-sample requirements, and shared-ledger
  integration must all remain false.

## What remains

This is static contract recovery only. Complete closure still requires:

1. approval to stage and inspect the official legacy `calibration:3.2.1` image
   after its size and disk impact are known;
2. an exact legacy server route/schema capture, replacing `L` with an
   authoritative count;
3. loopback-safe or private-network Thor deployment contracts for each service;
4. isolated mutation fixtures and cleanup, especially for mutating GET routes;
5. custom-data runtime qualification of every operation and workflow;
6. a separately reviewed integration that updates shared API inventories and
   denominators only after the legacy count is exact.

The roughly 100 GB Warehouse sample bundle is excluded. Operator-owned custom
data is sufficient for the future runtime lanes; the small optional AMC fixture
is a separate artifact.

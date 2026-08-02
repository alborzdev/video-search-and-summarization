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

Public NGC repository metadata narrows the legacy-image blocker without closing
it. The exact published runnable child for `calibration:3.2.1` is
`linux/amd64` at digest
`sha256:92dc91595316e10a85d0e6bc0bf9c2f2921b07030a246f9c0854ae6b61426ad8`
and compressed size 981,287,603 bytes. No runnable `linux/arm64` child is
published, even though the repository-level metadata says multi-architecture.
The image was absent locally, so native Thor runtime remains architecture
blocked. Registry denial left the tag-index digest and unpacked size unresolved.

The current 17-surface core inventory is byte-locked at 342 declared and 341
normalized-unique REST operations. Relative to that exact denominator, the
complete totals can currently be expressed only as:

- declared REST operations: `422 + L` (minimum 436);
- normalized REST operations: `421 + L` (minimum 435).

Neither minimum is a complete total.

## Trust model

[`contract.json`](contract.json) contains normalized operation descriptors and
three types of provenance:

1. `pinned_local_image_snapshot` records immutable NGC image digest, ARM64
   platform, local image size, inner-file path, content hash, and extraction
   method observed during the read-only audit. Tests never require those images.
2. `checked_in_source_snapshot` records repository path, SHA-256, and Git blob
identity. The validator re-hashes these files every run. It parses the current
core API inventory to derive the 342/341 denominator and formulas, then parses
AutoMagicCalib's `REQUIRED_OPENAPI` dictionary with Python AST and compares it
to the 26-operation descriptor.
3. `registry_image_metadata` records the absent legacy image's exact runnable
   child digest, platform, compressed size, non-runtime descriptor, local
   absence, unresolved fields, architecture block, and approval boundaries.
   It is registry provenance only: it does not claim a local snapshot, extracted
   server source, runtime evidence, or an authoritative operation count.

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
- legacy registry provenance is locked to the exact amd64 child and compressed
  size, with `arm64_variant_present: false`, local absence, and an architecture
  block;
- the unresolved tag-index digest and unpacked size must remain `null` while
  manifest access remains denied;
- no image pull is approved or performed; a future pinned amd64 pull requires
  explicit approval, while container lifecycle, host emulation, and image
  removal or Docker pruning each require separate approval;
- checked-in source hashes and Git blob identities are revalidated;
- legacy calibration cannot be promoted from `authoritative_unknown` or assigned
  `operation_count: 14`;
- runtime state must remain `not_qualified` with no runtime evidence;
- `complete_product_api`, Warehouse-sample requirements, and shared-ledger
  integration must all remain false.

## What remains

This is static contract recovery only. Complete closure still requires:

1. authenticated manifest metadata access to resolve the tag-index descriptor,
   followed by a fresh disk-impact review;
2. explicit approval to stage only the exact amd64 child for static inspection:
   `docker pull --platform=linux/amd64 nvcr.io/nvidia/vss-core/calibration@sha256:92dc91595316e10a85d0e6bc0bf9c2f2921b07030a246f9c0854ae6b61426ad8`;
3. a containerless, streamed layer inspection to capture an exact legacy server
   route/schema table and replace `L` with an authoritative count;
4. a native ARM64 artifact from NVIDIA, or a separately approved and qualified
   emulation lane, before legacy calibration can run locally on Thor;
5. loopback-safe or private-network Thor deployment contracts for each service;
6. isolated mutation fixtures and cleanup, especially for mutating GET routes;
7. custom-data runtime qualification of every operation and workflow;
8. a separately reviewed integration that updates shared API inventories and
   denominators only after the legacy count is exact.

The roughly 100 GB Warehouse sample bundle is excluded. Operator-owned custom
data is sufficient for the future runtime lanes; the small optional AMC fixture
is a separate artifact.

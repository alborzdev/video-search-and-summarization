# Evidence boundary

Status: **canonical source wiring observed; non-advancing**.

| Index | Literal | Proposed capability | Static state | Future oracle |
|---:|---|---|---|---|
| 00 | calibration and camera grouping | `manifest-entry.spatial-ai-utils.00-calibration-and-camera-grouping` | `wired/not_qualified` | Real grouping/reassignment on a digest-bound calibration |
| 01 | 3D/2D geometry | `manifest-entry.spatial-ai-utils.01-3d-2d-geometry` | `wired/not_qualified` | Real projection CLI with positive and legacy-shape negative |
| 02 | multiview visualization | `manifest-entry.spatial-ai-utils.02-multiview-visualization` | `wired/not_qualified` | Real two-camera plus BEV rendering |
| 03 | detection mAP | `manifest-entry.spatial-ai-utils.03-detection-map` | `wired/not_qualified` | Real production loader/evaluator/save path, not reference AP |
| 04 | tracking HOTA/CLEAR/identity/count | `manifest-entry.spatial-ai-utils.04-tracking-hota-clear-identity-count` | `wired/not_qualified` | Real metric classes on positive and mismatch tracks |
| 05 | NVSchema conversion | `manifest-entry.spatial-ai-utils.05-nvschema-conversion` | `wired/not_qualified` | Real converter plus strict JSONL loader roundtrip |
| 06 | video/frame tools | `manifest-entry.spatial-ai-utils.06-video-frame-tools` | `wired/not_qualified` | Real local codec encode/decode roundtrip |
| 07 | AWS/GCS validation | `manifest-entry.spatial-ai-utils.07-aws-gcs-validation` | `external_optional/not_applicable` | Authorized actual-provider upload/read/validate/cleanup attestation |

All local entries retain oracle type `offline_tool_execution`, state
`open_unexecuted`, and the exact required evidence tuple
`input_digest`, `command_contract`, `output_digest`, and
`semantic_output_assertion`. The AWS/GCS entry retains oracle type
`external_optional_boundary`, state `external_boundary_unexecuted`, and requires
an authorized endpoint transcript plus validation result.

The deterministic result reports eight entries, 34 unique source locks, seven
local wired-but-unqualified mappings, one external boundary, and zero runtime
evidence. SHA-256 and AST/text assertions fail closed on source drift. The
schemas reject reordered entries, state promotion, evidence insertion, unknown
fields, and policy relaxation.

Every oracle ID follows the live compiler identity rule
`oracle.{full capability id}`. For example, entry `03` binds to
`oracle.manifest-entry.spatial-ai-utils.03-detection-map`; short numeric-only
oracle aliases are not accepted.

This package intentionally does not consume the older candidate executor as a
pass receipt. That executor is bound to a predecessor gap-plan digest, and its
historical successor record states that it was identity-verified rather than
re-executed. Likewise, the dedicated detection-mAP static executor is useful
candidate evidence but explicitly does not execute the production evaluator.

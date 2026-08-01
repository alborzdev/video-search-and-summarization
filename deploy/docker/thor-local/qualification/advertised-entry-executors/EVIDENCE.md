# Evidence map

Every row below preserves the exact gap-plan entry ID and manifest pointer. “Proof”
means only the narrow, digest-bound, in-memory observation described in the last
column. It is not runtime evidence and does not imply whole-family completion.

| Manifest pointer | Exact entry ID | Candidate proof (subset only) |
|---|---|---|
| `/features/15/advertised/5` | `manifest-gap.rt-cv-3d-mv3dt.05-associated-skill` | Parses the locked skill frontmatter and confirms MV3DT mode, calibrated multi-camera scope, explicit sample/video/RTSP routing, configure/deploy/verify references, and that an unspecified source does not imply the sample. It does not deploy MV3DT. |
| `/features/29/advertised/0` | `manifest-gap.spatial-ai-utils.00-calibration-and-camera-grouping` | Runs the checked-in move parser and group reassignment bodies on two in-memory calibration sensors; confirms template reassignment and malformed-input rejection. |
| `/features/29/advertised/1` | `manifest-gap.spatial-ai-utils.01-3d-2d-geometry` | Runs checked-in 9-DoF box-corner and 3D-to-2D projection bodies; confirms exact extents/shapes, positive depth, finite pixels, and legacy 7-DoF rejection. |
| `/features/29/advertised/2` | `manifest-gap.spatial-ai-utils.02-multiview-visualization` | Runs checked-in camera, BEV, and multi-camera composition bodies for two in-memory images; confirms a `64x192x3` composite, rendered pixels in all panels, and unchanged inputs. |
| `/features/29/advertised/4` | `manifest-gap.spatial-ai-utils.04-tracking-hota-clear-identity-count` | Runs the checked-in HOTA, CLEAR, Identity, and Count classes on a two-frame perfect single track; confirms unit scores and exact detection/identity counts. |
| `/features/29/advertised/5` | `manifest-gap.spatial-ai-utils.05-nvschema-conversion` | Runs the checked-in Sparse4D converter with memory-only `open`, fixed UTC time, and one object; confirms NVSchema 4.0 JSONL semantics, size-axis swap, identity rotation, class mapping, confidence, and embedding. |
| `/features/29/advertised/6` | `manifest-gap.spatial-ai-utils.06-video-frame-tools` | Runs checked-in frame sorting/assembly and video extraction bodies with memory-only OpenCV/filesystem adapters; confirms numeric ordering, downsample, frame-skip extraction, statuses, and zero real writes. |
| `/features/30/advertised/1` | `manifest-gap.synthetic-data-tools.01-dataset-checks` | Runs checked-in overflow and velocity-check bodies; confirms normal/extreme coordinate classification, an exact 30 m/s horizontal and 15 m/s vertical result, and invalid-step rejection. |

## Interpretation

The output hashes bind fixture inputs and semantic summaries, while `source_locks`
bind the source bodies. If a source, manifest literal, proposed ID, plan entry, or
denominator changes, execution stops before the corresponding adapter runs.

The source plan remains authoritative for all 87 entries. This package does not edit
it, and its 8 observations leave all 87 live gap states untouched until a separate,
authorized acceptance/oracle integration decides how candidate evidence is consumed.

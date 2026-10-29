# East crossing pedestrian story

Use the East crossing for the booth question: “How long do people wait, and is someone still on the crossing?” The southwest camera covers both approach points and the full crossing in the retained static scene audit. The South crossing measurements remain saved as rules and in the rollback configuration.

The three new rules belong to the southwest camera, `997d3a69-e052-45a4-a1ce-be1b046670c4`:

| Rule | Ground geometry in metres |
| --- | --- |
| `mobility-isaac-east-waiting-south` | x −12.2 to −10.2; y 69.2 to 72.0 |
| `mobility-isaac-east-crossing-measurement` | Exact painted `XW_E`: x −13.2 to −9.2; y 72.0 to 86.4 |
| `mobility-isaac-east-waiting-north` | x −12.2 to −10.2; y 86.4 to 90.4 |

The waiting rules cover two visible bands. They do not claim to cover each full sidewalk. A four-metre-wide south pad extended outside the protected camera image, so it was not used. Every selected ROI vertex has a valid person-ground projection. New rules inherit the existing person-rule conditions, including the one-second real-observation continuity limit. No existing ROI or threshold is relaxed.

Select only `east-crossing-south-north` and `east-crossing-north-south` in the walking panel. Each uses its own waiting rule and the shared painted crossing rule. Both can show current crossing occupancy. A completed journey still requires the same actual local camera handle to cross the appropriate far edge. A missing or replaced ID does not establish an exit.

The authored finite booth binding template is:

```json
{
  "east-crossing": {
    "crosswalkId": "XW_E",
    "signalGroup": "ped_cross_EW",
    "points": [[-11.2, 70.0, 0], [-11.2, 79.2, 0], [-11.2, 88.4, 0]]
  }
}
```

The catalog selects this binding on a normal fresh scenario setup. The runtime reads the exact survey crossing and signal group. It checks opposite ends, path direction, lateral clearance, actual native actor radius, the full available WALK window and the crossing’s actual conflicting lanes (`EB_1`, `WB_1`). It verifies the actual final position outside the selected crossing and normal program restoration. Unknown crossing IDs, mismatched signals or changed owned binding points fail closed. Legacy South list bindings remain compatible. The new explicit East binding requires the owned booth phases; the old fixed-wait `people.crossing` operation cannot promise a valid signal when its wait ends.

A read-only native NavMesh check used Character_02 radius 0.25515 m and height 1.82250 m. Both directions have native paths, with total lengths about 18.47 and 18.50 m. The static scene audit has 15 clear southwest camera rays at five route positions and three heights. These checks establish navigation and sampled static visibility. They do not establish live detector accuracy, continuous local IDs, moving-vehicle visibility or completed camera-derived crossings.

## Current native result and earlier camera-completion evidence

On the final native-SEI worker/UI, a fresh episode completed/restored in **42.7099 wall seconds**, with **SUCCEEDED** native endpoint, **0.03830 m** error and position outside the crossing. Camera completion stayed **0→0**, and pre-existing incomplete stayed **3→3**; these are not three new episode failures. The same camera-local ID persisted, but fresh-object **1.137 s/1.871 s** observation gaps exceeded the unchanged one-second evidence bound. Thus no current camera completion qualifies. [Native/camera result](qa/smart-city-2026-10-26/native-sei-final-pedestrian.json). [Continuity audit](qa/smart-city-2026-10-26/native-sei-pedestrian-camera-continuity.json) confirms camera frames continued and does not claim a visually proved occluder or detector/tracker root cause. Final health passed. The bounded booth prototype is accepted with the stated evidence limits.

The earlier pre-clock-repair UI episode passed in **97.123 wall seconds**. Its endpoint task was **SUCCEEDED**, error **0.03796m**, the person was outside the crossing and its normal program was restored. Independently, the East north-to-south camera completed counter advanced **0→1**. [Earlier native/camera receipt](qa/smart-city-2026-10-26/v3-final-pedestrian-live-ui.json). This remains one actual episode on its recorded artifacts, not an all-click/all-day/identity score.

The JSON above remains the authored template. The current runtime chooses a
finite free entry/landing point inside the same unchanged waiting pads using
actual native bodies, verifies the full native path and preserves WALK,
arrival-tolerance and total-time guards. The successful actual points were
`[-10.85,87.4,0] → [-11.2,79.2,0] → [-10.85,70.0,0]`.
These are native actor commands, not positions supplied to VSS analytics.

The earlier waiting-drift failure at 41.344 s and WALK-budget failure at 107.976 s remain preserved. Same-entry reapproach has focused source controls but did not trigger in the earlier 97.123 s pass. First-seen approach time stays a lower bound, not signal delay or the scenario timer; unrelated incomplete/lost tracks remain visible. The final native SEI clock/preview/map transport has bounded evidence: all 11 latest pairs met 150 ms, and [final dashboard pixels](qa/smart-city-2026-10-26/native-sei-final-dashboard.jpg) and accessibility separately reported one guarded shared person. The earlier shared-person screenshot 0/later accessibility 1 remain different instants. Physical exposure/browser clocks and shared-ID accuracy remain unqualified. [Current paired/display evidence](qa/smart-city-2026-10-26/native-sei-qualified-shared-pair.json). Camera-local crossing completion must still be observed independently.

## Prepare and review

`tools/smart-city/prepare_east_pedestrian_story.py` has no network or apply operation. Supply fresh full GET `site`, `rules` and `mobility` responses as one snapshot, the matching camera export, actual survey and static visibility audit. Use a new output directory:

```bash
python3 /home/sparkdev/vss/tools/smart-city/prepare_east_pedestrian_story.py \
  --snapshot /absolute/path/fresh-snapshot.json \
  --camera-export /home/sparkdev/isaac_city_sim/logs/vss-integration/camera-map-export.json \
  --survey /home/sparkdev/isaac_city_sim/config/survey_intersection_A.json \
  --static-visibility-audit /home/sparkdev/isaac_city_sim/logs/vss-integration/rebuild-20261026/pedestrian-pocket-static-audit.json \
  --output /absolute/path/new-review-directory
```

Review `manifest.json`, `rules-put.json`, `mobility-put.json` and `proposed-pedestrian-bindings.json`. The tool preserves every existing rule and all movement, queue and curb configuration. It replaces only the two known South crossing selections. Custom selections or conflicting East IDs require separate review. It saves the complete previous state, a correctly named previous selection, and rollback bodies whose deliberately invalid revision placeholders force a fresh revision check. A South selection archive is emitted only when South was actually selected.

Finish or cancel active scenarios before applying. Keep both sources registered. Compare the fresh input fingerprints and revisions, then PUT the reviewed rules and wait for the exact native acknowledgement. PUT the mobility selection with its own expected revision. Reload the reviewed scenario source through normal setup, with no active actor lease. Do not use `importlib.reload` or blindly replay old PUT bodies. No UI image build is needed for this backend selection and controller change.

The first reviewed bundle is retained at `.spark/city/runtime/east-pedestrian-review-20261026/review`. Root applied it on the existing v2 scene: all 19 rules were acknowledged at revision 415 and the two East cards were selected at mobility revision 6. The read-only receipt records that setup separately from any later scene migration or live pedestrian acceptance. If the scene wrapper changes, use the geometry-identical calibration migration with the explicit 19-rule count and eight pinned tracker files; keep the East selection. A future explicit calibration refresh that regenerates default rules also requires a reviewed measurement migration.

## Verify and restore

Run the actual “People wait, cross, and clear” booth control after fresh setup. Check a visible person at the selected waiting point, the actual WALK gate, observed crossing occupancy, the same local ID at the far edge and restored normal motion. Native arrival is simulator evidence; it is not a camera count. Keep incomplete results visible if the detector loses the person or the local ID changes.

For rollback, use the retained full rules and mobility bodies with fresh API revisions. Restore the catalog/controller selection only through a reviewed normal setup with no active lease. The South operator rules and original selection are preserved; no global vector deletion, camera change or model rebuild is involved.

See [preparation and first hot-apply receipt](qa/smart-city-2026-10-26/east-pedestrian-preparation-and-hot-apply.json) for hashes and validation. The pure tests exercise the actual mobility state machine in both directions and prove that a new ID across the far boundary cannot create a completed crossing.

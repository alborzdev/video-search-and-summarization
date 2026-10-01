# Guided demo browser rehearsal — September 30, 2026

Target: `http://10.88.9.91:7777/?workspace=guided`, exercised in the Codex
in-app browser against the running Spark backend. Camera: Spark Hospital Corridor,
`3688c328-7e71-493c-a1c7-011ad2fb3893`, publishing
`rtsp://10.88.9.91:8554/digital-twin`.

## Actual checks

| Step | Observed result |
| --- | --- |
| Watch | Connected live preview, recording already enabled, fresh indexing. Segment count increased through 6,188; coverage advanced to 23:04:46 EDT. |
| Ask | Real question submission and replay of its 25-second inspected interval worked. A people question returned “Yes”; a broader answer described a distant dark figure. Accuracy was not established by the ambiguous preview. |
| Find | Source-scoped semantic query “hospital beds and medical carts” returned 12 candidate clips. Guide defaults to Last 15 minutes; final replay showed a 22:48:56 EDT interval. |
| Follow | Detector inspection displayed a recorded Person 20 box. Appearance search returned “not in the visual-similarity index.” Read-only backend audit found no object embedding vectors for this source. Final guide action says Inspect detected objects and qualifies appearance search. |
| Monitor | Rule builder preselected the hospital camera. Medical cart visible preset retained its name and actual condition through review. Existing cart rule resumed into the one visual reasoning slot, produced real matches, then was paused again. |
| Review | New source-scoped cart events appeared at 22:51–22:54 EDT. The latest event’s recorded condition and 22.501-second video loaded correctly at 1280×720, readyState 4. |
| Reports | Seven source-scoped saved reports were available behind Show saved reports. Report links open separately, preserving the guide. |
| Finish | Back to the live scene returned to Watch. Notes are optional; chapter navigation does not submit model requests or activate rules. |

The desk stays mounted across Watch and Ask, and Find / Follow share their search
state. Changing cameras starts a fresh journey for that source. Monitoring and
Review reload their data on chapter entry. Mobile 390×844 layout had no horizontal
overflow; extra bottom clearance prevents the existing app navigation from covering
the end of the guide. Temporary viewport override was reset.

## Fixes and validation

- Added Guided demo navigation and the explainer’s Try the real demo entry.
- Kept actual tools, one selected source, manual feature actions and short presenter cues.
- Scoped rules, events and saved reports to the selected source.
- Added a visibly testable medical-cart condition for the static Sim; fixed preset names being replaced during wizard advancement.
- Preserved Refresh, collapsed report history initially, and made report links retain the guide.
- Clarified detection evidence versus separately indexed object embeddings.

Eight affected Jest suites initially passed with 72 tests; the subsequent cart
preset regression suite passed with 12 tests. Final report/review suites passed
with 18 tests; final GuidedDemo / Investigate suites passed with 25 tests. Strict
app TypeScript check and `git diff --check` passed. Final browser warning/error
log checkpoint was empty. These are overlapping checks, not additive test counts.

Source-mounted hot reload was used. No model or memory budgets changed, no full
image build or model restart. Both rehearsal visual rules were paused at the end;
capture and indexing remain enabled for user testing.

## Limits for presenters

This guide organizes real functionality; it does not guarantee model accuracy.
Check answers, detector labels and model matches against their footage. Hospital
detector labels, avatar entrances/exits, object appearance search, multi-camera
capacity and a full show-day soak are not qualified by this rehearsal. The current
hospital source has no indexed object embeddings; skip appearance search until
that separate pipeline is populated and verified. Repeated cart matches represent
a continuing visible condition, not a count of unique carts.

Use the [presenter playbook](../demo-presenter-runbook.md). Screenshot evidence:
`/home/spark/.codex/visualizations/2026/09/30/vss-guided-demo/guided-demo.png`,
`alert-evidence.png` and `mobile.png` in the same directory.
